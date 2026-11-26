"""Convert format 4 smart glyph axes into the format 3 form.

Format 3 describes a smart glyph with ``partsSettings`` - one
``{name, bottomValue, topValue}`` entry per property - and marks each layer
that takes part with ``partSelection``, ``1`` for the bottom of a property and
``2`` for the top. Format 4 replaced that with real axes on the glyph
(``glyph.axes``, ``{name, tag, default, hidden}``), and a pole is now an
ordinary layer associated with a master whose ``attr.coordinates`` carries the
glyph's own axes after the font axes. The master layer itself sits at each
axis ``default``, which the schema defaults to 0. There is no min/max: the
range is whatever the layers span.

That is the same model whenever every axis has exactly two positions - the
default and one other - and every pole layer sits on its master in the font
axes. Anything else has no format 3 equivalent and is refused:

* a third position on an axis (format 3 only has a bottom and a top),
* a non-integer position (``bottomValue`` / ``topValue`` are i32),
* a smart layer that is also an intermediate, bracket or colour layer,
* two layers of one master at the same smart location,
* masters whose poles differ. glyphsLib builds one small model per master,
  and a master without the poles of the others would quietly draw the plain
  default there, where Glyphs 4 interpolates across the whole designspace.

An axis that no layer moves along - a smart glyph with ``axes`` but no pole
layers - varies nothing, so it is dropped instead, and the glyph becomes a
plain glyph when that leaves no axis at all. Leaving it in would make
glyphsLib look for poles it does not have.

glyphsLib's smart component code (``builder/smart_components.py``) is what
reads the result. It takes the first layer of a master with a
``partSelection`` as that master's default - the master layer, since
``GSGlyph.layers`` lists master layers first - and it normalises every key of
a component's ``piece`` through the glyph's ``partsSettings``, raising
``KeyError`` on a key that is not one.

Glyphs 4 also writes *font* axis names into ``piece``. Usually the value is
just the location of the layer the component sits on, which changes nothing,
and those keys are removed - see :func:`clean_piece_values`. But Glyphs 4
reads them: a value that differs makes it draw the part as it is at *that*
font location (checked against a VF exported by Glyphs 4.2). Format 3 and
glyphsLib have nothing for that, so :func:`relocated_pieces` finds them for
the refusal.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

#: A parsed .glyphs mapping, as openstep_plist returns it.
_Dict = dict[str, Any]

#: The format 4 coordinate meaning "use this axis' default".
_DEFAULT_MARKER = "-"

#: partSelection values, as in the format 3 schema.
_BOTTOM = 1
_TOP = 2

#: Layer attributes that make a layer something other than a smart pole: a
#: bracket layer, or one of the colour layer kinds.
_OTHER_LAYER_KINDS = frozenset(("axisRules", "color", "colorPalette", "svg", "sbixSize"))


@dataclass
class _SmartLayer:
    layer: _Dict
    master_id: str
    is_master_layer: bool
    position: list[float]


@dataclass
class SmartPlan:
    """How one smart glyph converts. Built by :func:`plan_smart_glyph`."""

    #: The format 3 ``partsSettings`` - only the axes some layer moves along.
    parts_settings: list[_Dict]
    #: ``(layer, partSelection)`` for every master and pole layer.
    selections: list[tuple[_Dict, _Dict]]
    #: The pole layers, whose ``attr.coordinates`` must go: left in place,
    #: glyphsLib would read each as an intermediate layer.
    pole_layers: list[_Dict] = field(default_factory=list)
    #: Smart axes no layer moves along, which are dropped.
    inert_axes: set[str] = field(default_factory=set)

    @property
    def axis_names(self) -> set[str]:
        return {axis["name"] for axis in self.parts_settings}


@dataclass
class FontAxes:
    """What the smart glyph conversion needs to know about the font."""

    #: The font axis names, in order.
    names: list[str]
    #: ``{master id: [font axis coordinate, ...]}``, or None where a master
    #: does not state one coordinate per axis.
    master_locations: dict[str, list[float] | None]
    #: ``{master id: master name}``, for the messages.
    master_names: dict[str, str] = field(default_factory=dict)

    def describe(self, layer: _Dict) -> str:
        """``"'Bold'"`` for a master layer, ``"'Oct 26' (master 'Bold')"``
        otherwise: Glyphs names layers after their date, so a name alone is
        often the same on every master.
        """
        layer_id = layer.get("layerId")
        master_id = layer.get("associatedMasterId") or layer_id
        master = self.master_names.get(master_id)  # type: ignore[arg-type]
        if master is None:
            return repr(_layer_name(layer))
        if master_id == layer_id:
            return repr(master)
        return f"{_layer_name(layer)!r} (master {master!r})"

    @classmethod
    def of(cls, source: _Dict) -> FontAxes:
        names = [str(axis.get("name") or axis.get("tag") or "")
                 for axis in _dicts(source.get("axes"))]
        locations: dict[str, list[float] | None] = {}
        master_names: dict[str, str] = {}
        for master in _dicts(source.get("fontMaster")):
            master_id = master.get("id")
            if not isinstance(master_id, str):
                continue
            master_names[master_id] = str(master.get("name") or master_id)
            values = master.get("axesValues")
            if not isinstance(values, list):
                values = []
            numbers = [_number(value) for value in values]
            if len(numbers) == len(names) and all(n is not None for n in numbers):
                locations[master_id] = [n for n in numbers if n is not None]
            else:
                locations[master_id] = None
        return cls(names, locations, master_names)


def plan_smart_glyph(glyph: _Dict, font: FontAxes) -> SmartPlan | str:
    """Work out how a glyph with format 4 ``axes`` converts.

    Pure - does not modify ``glyph``.

    :returns: The plan, or the reason the glyph cannot be converted, worded to
        follow ``"glyph 'x': "`` in the error message.
    """
    axes = _dicts(glyph.get("axes"))
    if glyph.get("partsSettings"):
        return "has both format 3 partsSettings and format 4 axes"
    if not all(isinstance(axis.get("name"), str) and axis["name"] for axis in axes):
        return "a smart axis has no name"
    names: list[str] = [axis["name"] for axis in axes]
    if len(set(names)) != len(names):
        return "two smart axes share a name"
    defaults: list[float] = []
    for axis in axes:
        default = _number(axis.get("default", 0))
        if default is None:
            return f"smart axis {axis['name']!r} has a non-numeric default"
        defaults.append(default)

    font_count = len(font.names)
    smart_layers: list[_SmartLayer] = []
    for layer in _dicts(glyph.get("layers")):
        if layer.get("partSelection"):
            return "a layer has both partSelection and format 4 smart axes"
        layer_id = layer.get("layerId")
        associated = layer.get("associatedMasterId")
        coordinates = _coordinates(layer)
        is_master_layer = (isinstance(layer_id, str) and layer_id in font.master_locations
                           and associated in (None, layer_id))
        if is_master_layer:
            assert isinstance(layer_id, str)
            if coordinates is not None:
                return f"master layer {layer_id!r} has coordinates"
            smart_layers.append(_SmartLayer(layer, layer_id, True, list(defaults)))
            continue
        if coordinates is None:
            continue  # a backup, bracket or colour layer - not part of the model
        where = f"layer {font.describe(layer)}"
        if _OTHER_LAYER_KINDS & set(layer["attr"]):
            return f"{where} is also a bracket or colour layer"
        if associated not in font.master_locations:
            return f"{where} is not associated with a master"
        if len(coordinates) != font_count + len(axes):
            return (f"{where} has {len(coordinates)} coordinates for "
                    f"{font_count} font axes and {len(axes)} smart axes")
        master_location = font.master_locations[associated]
        if master_location is None:
            return f"the location of master {associated!r} is incomplete"
        font_part = [_number(value) for value in coordinates[:font_count]]
        if not all(value is not None and math.isclose(value, expected)
                   for (value, expected) in zip(font_part, master_location, strict=True)):
            return f"{where} is an intermediate layer between masters"
        position: list[float] = []
        for (value, default) in zip(coordinates[font_count:], defaults, strict=True):
            number = default if value == _DEFAULT_MARKER else _number(value)
            if number is None:
                return f"{where} has a non-numeric smart axis coordinate {value!r}"
            position.append(number)
        smart_layers.append(_SmartLayer(layer, associated, False, position))

    seen: set[tuple[str, tuple[float, ...]]] = set()
    for smart in smart_layers:
        key = (smart.master_id, tuple(smart.position))
        if key in seen:
            return f"two layers of master {smart.master_id!r} share a smart location"
        seen.add(key)
    masters_with_layer = {s.master_id for s in smart_layers if s.is_master_layer}
    for smart in smart_layers:
        if smart.master_id not in masters_with_layer:
            return f"master {smart.master_id!r} has pole layers but no master layer"
    poles_by_master: dict[str, set[tuple[float, ...]]] = {m: set() for m in masters_with_layer}
    for smart in smart_layers:
        if not smart.is_master_layer:
            poles_by_master[smart.master_id].add(tuple(smart.position))
    if len({frozenset(poles) for poles in poles_by_master.values()}) > 1:
        (first, *rest) = sorted(poles_by_master)
        other = next(m for m in rest if poles_by_master[m] != poles_by_master[first])
        return f"masters {first!r} and {other!r} have different smart poles"

    parts_settings: list[_Dict] = []
    kept: list[tuple[int, str, float, float]] = []
    inert: set[str] = set()
    for (index, (name, default)) in enumerate(zip(names, defaults, strict=True)):
        values = sorted({default} | {s.position[index] for s in smart_layers})
        if len(values) == 1:
            inert.add(name)  # nothing moves along this axis
            continue
        if len(values) > 2:
            shown = ", ".join(_format(v) for v in values)
            return (f"smart axis {name!r} has {len(values)} positions ({shown}); "
                    "format 3 has only a bottom and a top")
        (bottom, top) = values
        if not (bottom.is_integer() and top.is_integer()):
            return (f"smart axis {name!r} spans {_format(bottom)}..{_format(top)}; "
                    "format 3 stores whole numbers only")
        parts_settings.append({"name": name, "bottomValue": int(bottom),
                               "topValue": int(top)})
        kept.append((index, name, bottom, top))

    selections: list[tuple[_Dict, _Dict]] = []
    pole_layers: list[_Dict] = []
    for smart in smart_layers:
        if not smart.is_master_layer:
            pole_layers.append(smart.layer)
        if not kept:
            continue
        selection = {name: (_BOTTOM if math.isclose(smart.position[index], bottom) else _TOP)
                     for (index, name, bottom, _top) in kept}
        selections.append((smart.layer, selection))

    return SmartPlan(parts_settings, selections, pole_layers, inert)


def apply_smart_plan(glyph: _Dict, plan: SmartPlan) -> None:
    """Rewrite ``glyph`` in place as :func:`plan_smart_glyph` worked out."""
    glyph.pop("axes", None)
    if plan.parts_settings:
        glyph["partsSettings"] = plan.parts_settings
    for (layer, selection) in plan.selections:
        layer["partSelection"] = selection
    for layer in plan.pole_layers:
        attr = layer.get("attr")
        if isinstance(attr, dict):
            attr.pop("coordinates", None)
            if not attr:
                del layer["attr"]


@dataclass
class PieceCleanup:
    """What :func:`clean_piece_values` removed."""

    #: Keys that change nothing, see :func:`clean_piece_values`.
    inert: int = 0
    #: Keys that move the part to another font location, as
    #: ``"glyph 'a' layer 'b': Weight=0"``. Refused by find_unsupported, so
    #: only non-empty when the caller skipped that.
    relocated: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.inert + len(self.relocated)


def smart_axes_by_glyph(source: _Dict,
                        plans: dict[str, SmartPlan]) -> dict[str, tuple[set[str], set[str]]]:
    """``{glyph name: (smart axis names, dropped axis names)}`` for every smart
    glyph after conversion - the converted ones and those a format 4 file still
    describes the format 3 way, with ``partsSettings``, which is legal there.
    """
    axes = {name: (plan.axis_names, plan.inert_axes) for (name, plan) in plans.items()}
    for glyph in _dicts(source.get("glyphs")):
        name = glyph.get("glyphname")
        settings = _dicts(glyph.get("partsSettings"))
        if isinstance(name, str) and name not in axes and settings:
            axes[name] = ({str(s.get("name")) for s in settings}, set())
    return axes


def relocated_pieces(source: _Dict, axes_by_glyph: dict[str, tuple[set[str], set[str]]],
                     font: FontAxes) -> list[str]:
    """The ``piece`` keys that place a part at another font location.

    Pure. :returns: ``"glyph 'a' layer 'b': Weight=0"`` for each, in file order.
    """
    return [where for (_piece, _key, where) in _foreign_piece_keys(source, axes_by_glyph, font)
            if where is not None]


def clean_piece_values(source: _Dict, axes_by_glyph: dict[str, tuple[set[str], set[str]]],
                       font: FontAxes) -> PieceCleanup:
    """Remove ``piece`` keys that name no smart axis of the referenced glyph.

    :param axes_by_glyph: As :func:`smart_axes_by_glyph` returns it.

    glyphsLib raises ``KeyError`` on such a key. Most change nothing: a key
    naming a dropped axis no layer moves along, a font axis key with the
    location of the layer the component sits on, any key in a background, and
    a name that is no axis at all. A font axis key with another value does
    change the outline in Glyphs 4 (see :func:`relocated_pieces`); it is
    removed too, but listed separately so the caller can say so.
    """
    cleanup = PieceCleanup()
    found = list(_foreign_piece_keys(source, axes_by_glyph, font))
    for (piece, key, where) in found:
        del piece[key]
        if where is None:
            cleanup.inert += 1
        else:
            cleanup.relocated.append(where)
    for glyph in _dicts(source.get("glyphs")):
        for (layer, _location, _background) in _layers_with_location(glyph, font):
            for shape in _dicts(layer.get("shapes")):
                if shape.get("piece") == {} and shape.get("ref") in axes_by_glyph:
                    del shape["piece"]
    return cleanup


def _foreign_piece_keys(
    source: _Dict, axes_by_glyph: dict[str, tuple[set[str], set[str]]], font: FontAxes
) -> Iterator[tuple[_Dict, str, str | None]]:
    """``(piece, key, where)`` for every piece key that is no smart axis of the
    referenced glyph. ``where`` is None for a key that changes nothing.
    """
    for glyph in _dicts(source.get("glyphs")):
        for (layer, location, background) in _layers_with_location(glyph, font):
            for shape in _dicts(layer.get("shapes")):
                ref = shape.get("ref")
                piece = shape.get("piece")
                if not (isinstance(ref, str) and ref in axes_by_glyph
                        and isinstance(piece, dict)):
                    continue
                (smart_axes, dropped_axes) = axes_by_glyph[ref]
                for (key, value) in piece.items():
                    if key in smart_axes:
                        continue
                    relocates = (not background and key not in dropped_axes
                                 and key in font.names
                                 and not _matches_location(key, value, font, location))
                    where = (f"glyph {glyph.get('glyphname', '?')!r} "
                             f"layer {font.describe(layer)}: {key}={_format(value)}"
                             if relocates else None)
                    yield (piece, key, where)


def _layers_with_location(
    glyph: _Dict, font: FontAxes
) -> Iterator[tuple[_Dict, list[float] | None, bool]]:
    """Every layer and background with its font axis location, where known,
    and whether it is a background.
    """
    for layer in _dicts(glyph.get("layers")):
        master_id = layer.get("associatedMasterId") or layer.get("layerId")
        location = font.master_locations.get(master_id)  # type: ignore[arg-type]
        coordinates = _coordinates(layer)
        if coordinates is not None and len(coordinates) >= len(font.names):
            numbers = [_number(value) for value in coordinates[:len(font.names)]]
            location = ([n for n in numbers if n is not None]
                        if all(n is not None for n in numbers) else None)
        yield (layer, location, False)
        background = layer.get("background")
        if isinstance(background, dict):
            yield (background, location, True)


def _matches_location(key: str, value: Any, font: FontAxes,
                      location: list[float] | None) -> bool:
    if location is None or key not in font.names:
        return False
    number = _number(value)
    return number is not None and math.isclose(number, location[font.names.index(key)])


def _coordinates(layer: _Dict) -> list[Any] | None:
    attr = layer.get("attr")
    if not isinstance(attr, dict):
        return None
    coordinates = attr.get("coordinates")
    return coordinates if isinstance(coordinates, list) and coordinates else None


def _layer_name(layer: _Dict) -> str:
    return str(layer.get("name") or layer.get("layerId") or "?")


def _number(value: Any) -> float | None:
    """A coordinate as a float. Glyphs writes numbers bare or quoted."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _dicts(value: Any) -> list[_Dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


__all__ = [
    "FontAxes",
    "PieceCleanup",
    "SmartPlan",
    "apply_smart_plan",
    "clean_piece_values",
    "plan_smart_glyph",
    "relocated_pieces",
    "smart_axes_by_glyph",
]
