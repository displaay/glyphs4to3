"""Rewrite a parsed Glyphs 4 source into the format 3 shape."""

from __future__ import annotations

import collections
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .buckets import (
    EDITOR_ONLY,
    IGNORED,
    NODE_TYPE_NAMES,
    READABLE_NODE_TYPES,
    UNSUPPORTED,
    UNSUPPORTED_VALUES,
    editor_only_by_scope,
)
from .exceptions import UnknownFormatVersionError

LOGGER = logging.getLogger(__name__)

#: A parsed .glyphs file, as openstep_plist returns it.
PlistDict = dict[str, Any]

#: The format version glyphsLib is told to read. Format 4 uses the format 3
#: node and code point representation, so this is a relabel, not a conversion.
TARGET_FORMAT_VERSION = 3

#: The newest format version this package has been verified against.
NEWEST_KNOWN_FORMAT_VERSION = 4

#: How many locations a single feature names in the error message. The message
#: is usually stored or reported verbatim, so it must not grow with the source.
MAX_REPORTED_LOCATIONS = 10

_EDITOR_ONLY_BY_SCOPE = editor_only_by_scope()

#: A format 3 GSPath serialises "nodes" only when it has some, so a shape with
#: neither "ref" nor "nodes" is not necessarily a format 4 group - it may be an
#: empty path. These are the keys such an empty path may still carry.
_EMPTY_PATH_KEYS = frozenset(("closed", "attr"))

#: The serialiser-level boolean forms a Glyphs 4 source can write where both
#: schemas say 1/0. openstep_plist yields them as plain strings.
_BOOLEAN_LITERALS = {":true": 1, ":false": 0}

#: Keys whose subtree the literal scan does not enter - see
#: :func:`_coerce_boolean_literals`.
_BOOLEAN_SCAN_SKIP = frozenset(("userData", "nodes"))

_UNSUPPORTED_INTRO = (
    "Unsupported Glyphs 4 source: this file uses features that have no "
    "equivalent in the Glyphs 3 format, and dropping them would produce a "
    "font with wrong outlines or lost kerning. Re-save the source from Glyphs "
    "with these removed, or export it as Glyphs 3."
)


@dataclass(frozen=True)
class Finding:
    """One format 4 construct that has no format 3 equivalent.

    :param feature: A key of :data:`glyphs4to3.buckets.UNSUPPORTED`.
    :param where: ``"glyph 'a' layer 'Bold'"``, or None for a font-level find.
    """

    feature: str
    where: str | None = None

    def __str__(self) -> str:
        return "{} ({})".format(self.feature, self.where or "font level")


@dataclass
class NormalizeReport:
    """What :func:`normalize` did.

    ``converted`` is False for a format 2 or 3 source, which is left alone.
    """

    source_version: int
    converted: bool = False
    renamed: list[str] = field(default_factory=list)
    dropped: collections.Counter[str] = field(default_factory=collections.Counter)

    def summary(self) -> str:
        """A single line describing the conversion."""
        parts = [f"format {self.source_version} -> {TARGET_FORMAT_VERSION}"]
        if self.renamed:
            parts.append("; ".join(self.renamed))
        if self.dropped:
            parts.append(f"{sum(self.dropped.values())} editor-only keys dropped")
        return ", ".join(parts)

    def dropped_lines(self) -> list[str]:
        """One line per dropped key path with its count.

        Never one line per occurrence: ``layer.active`` is on every layer of
        every glyph, and a 600-glyph source would produce tens of thousands.
        """
        return [f"{path}: {count}" for (path, count) in sorted(self.dropped.items())]


def source_format_version(source: PlistDict) -> int:
    """The format version of a parsed source.

    :returns: 2 when the key is absent, which is how Glyphs 2 files are written.
    :raises UnknownFormatVersionError: The version is newer than this package
        has been verified against, or is not a version number at all.
    """
    version = source.get(".formatVersion", 2)
    if not isinstance(version, int) or isinstance(version, bool) or version < 2:
        raise UnknownFormatVersionError(
            f"Unsupported Glyphs source: .formatVersion is {version!r}."
        )
    if version > NEWEST_KNOWN_FORMAT_VERSION:
        raise UnknownFormatVersionError(
            f"Unsupported Glyphs source: format version {version}. This package reads "
            "format versions 2, 3 and 4 (4 is read as 3)."
        )
    return version


def find_unsupported(source: PlistDict) -> list[Finding]:
    """Look for format 4 constructs that cannot be converted.

    Pure - does not modify ``source``. Collects *everything* in one pass, so
    that a file with two problems reports both at once rather than making the
    author fix them one round trip at a time.

    :returns: A list of :class:`Finding`, empty for a format 2 or 3 source.
    :raises UnknownFormatVersionError: see :func:`source_format_version`.
    """
    if source_format_version(source) < 4:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, str | None]] = set()

    def add(feature: str, where: str | None = None) -> None:
        if (feature, where) in seen:
            return
        seen.add((feature, where))
        findings.append(Finding(feature, where))

    # by value, not by presence: an empty kerningContext carries no kerning to
    # lose, and Glyphs may well write the key unconditionally
    if source.get("kerningContext"):
        add("kerningContext")

    for glyph in _dicts(source.get("glyphs")):
        name = glyph.get("glyphname", "?")
        if glyph.get("axes"):
            # Not a rename of partsSettings: that key still exists in format 4
            # and holds {name, bottomValue, topValue}, while these are full
            # axes of {name, tag, default, hidden}.
            add("glyph.axes", f"glyph {name!r}")
        for (layer_name, layer) in _layers(glyph):
            where = f"glyph {name!r} layer {layer_name!r}"
            if _has_deferred_coordinates(layer):
                add("layerAttr.coordinates", where)
            for shape in _dicts(layer.get("shapes")):
                if _is_shape_group(shape):
                    add("shapeGroup", where)
                for node in _nodes(shape.get("nodes")):
                    if _has_node_attributes(node):
                        add("nodeAttr.hoi", where)
                    unmapped = _unmapped_node_type(node)
                    if unmapped is not None:
                        add("node.type", f"{where} ({unmapped})")
    return findings


def unsupported_message(findings: list[Finding]) -> str:
    """The message for :class:`UnsupportedSourceError`.

    One line per feature - never per occurrence - naming at most
    :data:`MAX_REPORTED_LOCATIONS` locations.
    """
    by_feature: dict[str, list[str | None]] = {}
    for finding in findings:
        by_feature.setdefault(finding.feature, []).append(finding.where)

    lines = [_UNSUPPORTED_INTRO]
    for (feature, locations) in by_feature.items():
        described = UNSUPPORTED.get(feature) or UNSUPPORTED_VALUES.get(feature, feature)
        named = [where for where in locations if where]
        if not named:
            lines.append(f"- {described} ({feature}): font level")
            continue
        shown = named[:MAX_REPORTED_LOCATIONS]
        text = ", ".join(shown)
        if len(named) > len(shown):
            text += f" and {len(named) - len(shown)} more"
        lines.append(f"- {described} ({feature}): {text}")
    return "\n".join(lines)


def normalize(source: PlistDict) -> NormalizeReport:
    """Rewrite a format 4 source **in place** into the format 3 shape.

    Does not call :func:`find_unsupported` - the caller owns that policy. A
    format 2 or 3 source is left completely untouched, key order included.

    That last part also means a ``:true`` / ``:false`` literal in a *format 3*
    document written by Glyphs 4 would not be coerced. Considered and left
    alone deliberately: format 3 output is meant to be readable by Glyphs 3,
    which cannot parse the literal either, so it is very unlikely to be
    written there - and "version 2 and 3 sources are untouched" is a documented
    invariant worth more than covering a case nobody has seen.

    In place because a parsed 20 MB source is hundreds of thousands of small
    dicts and a copy would double peak memory for nothing; the dict is
    normally thrown away as soon as it has been handed to a parser.
    """
    report = NormalizeReport(source_format_version(source))
    if report.source_version < 4:
        return report

    _coerce_boolean_literals(source, report)
    _rename_family_name(source, report)
    _rename_instance_names(source, report)
    _rename_axis_names(source, report)
    _drop_editor_only(source, report)
    _coerce_app_version(source, report)
    _set_format_version_first(source)
    report.converted = True
    return report


# -- the conversions -------------------------------------------------------

def _rename_family_name(source: PlistDict, report: NormalizeReport) -> None:
    """GSFont.familyName is a plain attribute read from the top-level key and
    defaulting to "Unnamed font". Only GSInstance falls back to properties, so
    without this a format 4 font loses its name.
    """
    if source.get("familyName"):
        return
    name = _property_text(source.get("properties"), "familyNames")
    if not name:
        return
    source["familyName"] = name
    report.renamed.append("properties/familyNames -> familyName")


def _rename_instance_names(source: PlistDict, report: NormalizeReport) -> None:
    """Format 4 instances carry no "name" key at all; without this every
    instance would be called "Regular".
    """
    renamed = 0
    for instance in _dicts(source.get("instances")):
        if instance.get("name"):
            continue
        name = _property_text(instance.get("properties"), "styleNames")
        if not name:
            continue
        instance["name"] = name
        renamed += 1
    if renamed:
        report.renamed.append(
            f"instance properties/styleNames -> instance name ({renamed})"
        )


def _rename_axis_names(source: PlistDict, report: NormalizeReport) -> None:
    """GSAxis parses only "tag" and "hidden", so a format 4 "names" list stays
    an inert attribute and the axis ends up unnamed in the designspace.
    """
    renamed = 0
    for axis in _dicts(source.get("axes")):
        if axis.get("name"):
            continue
        name = _localized(axis.get("names"))
        if not name:
            continue
        axis["name"] = name
        renamed += 1
    if renamed:
        report.renamed.append(f"axis names -> axis name ({renamed})")


def _coerce_boolean_literals(source: PlistDict, report: NormalizeReport) -> None:
    """Turn the ``:true`` / ``:false`` literals into 1 / 0, everywhere.

    Both published schemas say a boolean is the integer 1 or 0, but a Glyphs 4
    source writes ``keepAlternatesTogether = :true`` - openstep_plist hands
    that over as the *string* ``":true"``. This is a serialiser-level form
    rather than a schema element (it is not in the ``minVersion: 4`` set that
    :mod:`glyphs4to3.buckets` audits), so it turns up wherever Glyphs writes a
    boolean, not only in "settings".

    Leaving it alone is silently destructive, and worst in the ``:false``
    direction, because Glyphs only serialises a boolean that differs from its
    default - so a written ``:false`` lands on exactly the keys that default to
    true. ``glyph.export = :false`` loads as ``export == True`` (glyphsLib
    applies ``bool()`` to a non-empty string), which compiles every
    non-exporting helper glyph into the font; a custom parameter
    ``Use Typo Metrics = :false`` sets the OS/2 bit the source explicitly turns
    off.

    ``userData`` is skipped: that is where free-form author content lives and
    the literal there could conceivably be a real string. ``nodes`` is skipped
    for cost - it is the bulk of a source (16 200 nodes in the file this was
    measured on, and walking them doubled the load time) and holds
    coordinates, a type string and, in format 4, an attribute dict whose only
    key that matters here is ``hoi``, which is refused outright. Everywhere
    else the value ``":false"`` has no legitimate meaning.
    """
    coerced = _coerce_booleans_in(source)
    if coerced:
        report.renamed.append(f"boolean literals coerced ({coerced})")


def _coerce_booleans_in(node: Any) -> int:
    """Recurse, replacing the literals. :returns: How many were replaced."""
    coerced = 0
    if isinstance(node, dict):
        for (key, value) in list(node.items()):
            if key in _BOOLEAN_SCAN_SKIP:
                continue
            replacement = _BOOLEAN_LITERALS.get(value) if isinstance(value, str) else None
            if replacement is not None:
                node[key] = replacement
                coerced += 1
            else:
                coerced += _coerce_booleans_in(value)
    elif isinstance(node, list):
        for (index, value) in enumerate(node):
            replacement = _BOOLEAN_LITERALS.get(value) if isinstance(value, str) else None
            if replacement is not None:
                node[index] = replacement
                coerced += 1
            else:
                coerced += _coerce_booleans_in(value)
    return coerced


def _coerce_app_version(source: PlistDict, report: NormalizeReport) -> None:
    """glyphsLib's UFO builder does ``int(font.appVersion) < 895``. A
    non-numeric .appVersion would fail there, far away from the load.
    """
    app_version = source.get(".appVersion")
    if app_version is None:
        return
    try:
        int(app_version)
    except (TypeError, ValueError):
        LOGGER.warning("Coercing non-numeric .appVersion %r", app_version)
        source[".appVersion"] = "3300"
        report.renamed.append("non-numeric .appVersion coerced")


def _set_format_version_first(source: PlistDict) -> None:
    """Put ".formatVersion" first.

    It is what sets ``GSFont.format_version`` and ``Parser.format_version``,
    and glyphsLib's ``_parse_dict_into_object`` walks the keys in insertion
    order - so a source with the version at the end would have its nodes read
    by the format 2 reader. Only the top-level mapping is rebuilt; the values
    are the same objects.
    """
    rest = [(key, value) for (key, value) in source.items() if key != ".formatVersion"]
    source.clear()
    source[".formatVersion"] = TARGET_FORMAT_VERSION
    source.update(rest)


def _drop_editor_only(source: PlistDict, report: NormalizeReport) -> None:
    """Remove the editor-state keys.

    The walk is deliberately explicit rather than a generic recursion:
    userData and customParameters hold author-written content, and a source
    with ``userData = {"active": 1}`` must not have it eaten. A naive
    recursion would also miss "nodes", which is a list of lists.
    """
    settings = source.get("settings")
    if isinstance(settings, dict):
        _drop_keys(settings, "settings", report)

    for master in _dicts(source.get("fontMaster")):
        _drop_keys(master, "fontMaster", report)
        for guide in _dicts(master.get("guides")):
            _drop_keys(guide, "guide", report)

    for instance in _dicts(source.get("instances")):
        _drop_keys(instance, "instance", report)

    for glyph in _dicts(source.get("glyphs")):
        _drop_keys(glyph, "glyph", report)
        for (_name, layer) in _layers(glyph):
            _drop_keys(layer, "layer", report)
            for anchor in _dicts(layer.get("anchors")):
                _drop_keys(anchor, "anchor", report)
            for guide in _dicts(layer.get("guides")):
                _drop_keys(guide, "guide", report)
            image = layer.get("backgroundImage")
            if isinstance(image, dict):
                _drop_keys(image, "image", report)
            for shape in _dicts(layer.get("shapes")):
                attr = shape.get("attr")
                if isinstance(attr, dict):
                    _drop_keys(attr, "shapeAttr", report)


def _drop_keys(container: PlistDict, scope: str, report: NormalizeReport) -> None:
    for key in _EDITOR_ONLY_BY_SCOPE.get(scope, ()):
        if key in container:
            del container[key]
            report.dropped[f"{scope}.{key}"] += 1


# -- walking ---------------------------------------------------------------

def _dicts(value: Any) -> list[PlistDict]:
    """The dict items of a .glyphs list.

    An absent list parses as None and a malformed one as something that is not
    a list; both are treated as empty. Nodes are lists rather than dicts, so
    they need :func:`_nodes`.
    """
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _nodes(value: Any) -> list[Any]:
    """The items of a "nodes" list, which are themselves lists."""
    if isinstance(value, list):
        return value
    return []


def _layers(glyph: PlistDict) -> Iterator[tuple[str, PlistDict]]:
    """Yield ``(name, layer)`` for every layer of ``glyph`` and for its
    background layer, which holds shapes and nodes of its own.
    """
    for layer in _dicts(glyph.get("layers")):
        name = layer.get("name") or layer.get("layerId") or "?"
        yield (name, layer)
        background = layer.get("background")
        if isinstance(background, dict):
            yield (name, background)


def _is_shape_group(shape: PlistDict) -> bool:
    """Whether a shape is a format 4 shape group.

    ``GSLayer._parse_shapes_dict`` branches on ``"ref" in shape_dict`` and
    otherwise builds a GSPath, so a group would become an empty path and its
    nested outlines would vanish without an error - which is why this also
    catches a shape that is neither a component nor a path, without needing to
    know the name of whatever it is.
    """
    if "groupId" in shape:
        return True
    if "ref" in shape or "nodes" in shape:
        return False
    # An empty path is legal and serialises without "nodes".
    return bool(set(shape) - _EMPTY_PATH_KEYS)


def _has_node_attributes(node: Any) -> bool:
    """Whether a node carries format 4 higher-order interpolation.

    ``GSNode.read_v3`` already accepts a fourth element - it reads it as
    userData - so only the ``hoi`` key is a problem.
    """
    if not isinstance(node, list) or len(node) < 4:
        return False
    return isinstance(node[3], dict) and "hoi" in node[3]


def _unmapped_node_type(node: Any) -> str | None:
    """The node's type letter, when no Glyphs 3 reader maps it.

    ``GSNode.read_v3`` branches on the first character (c/o/l/q, with a
    trailing "s" for smooth) and leaves everything else as ``type=None``. A
    node with no curve type does not fail the build - it silently draws the
    wrong outline - so this is refused for the same reason as ``hoi``.

    :returns: ``"h (Hobby)"``-style text for the message, or None when the
        node is readable or is not a node at all.
    """
    if not isinstance(node, list) or len(node) < 3:
        return None
    token = node[2]
    if not isinstance(token, str) or not token:
        return None
    if token[0] in READABLE_NODE_TYPES:
        return None
    name = NODE_TYPE_NAMES.get(token[0])
    return f"{token} ({name})" if name else token


def _has_deferred_coordinates(layer: PlistDict) -> bool:
    """Whether a layer defers a brace/bracket coordinate to an axis default.

    Format 4 may write "use the axis default" where format 3 wants a number.
    """
    attr = layer.get("attr")
    if not isinstance(attr, dict):
        return False
    coordinates = attr.get("coordinates")
    if not isinstance(coordinates, list):
        return False
    return any(not _is_number(value) for value in coordinates)


def _is_number(value: Any) -> bool:
    """Whether a value is a coordinate rather than a marker.

    Glyphs writes numbers in ``attr`` as bare numbers or as quoted strings and
    glyphsLib copes with both - ``_brace_coordinates()`` does ``float(v)`` and
    ``_bracket_axis_rules()`` converts a str axis bound - so a numeric string
    is not the format 4 "defer to the axis default" marker.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _property_text(properties: Any, key: str) -> str | None:
    """Read one entry out of a format 3 / 4 ``properties`` list."""
    for entry in _dicts(properties):
        if entry.get("key") != key:
            continue
        value = entry.get("value")
        if value:
            return str(value)
        return _localized(entry.get("values"))
    return None


def _localized(values: Any) -> str | None:
    """Pick a language out of ``{"language": ..., "value": ...}`` entries.

    Uses the order ``GSFontInfoValue.value`` uses.
    """
    entries = _dicts(values)
    by_language = {entry.get("language"): entry.get("value") for entry in entries}
    for language in ("dflt", "default", "ENG"):
        chosen = by_language.get(language)
        if chosen:
            return str(chosen)
    for entry in entries:
        value = entry.get("value")
        if value:
            return str(value)
    return None


__all__ = [
    "EDITOR_ONLY",
    "IGNORED",
    "MAX_REPORTED_LOCATIONS",
    "NEWEST_KNOWN_FORMAT_VERSION",
    "TARGET_FORMAT_VERSION",
    "UNSUPPORTED",
    "Finding",
    "NormalizeReport",
    "PlistDict",
    "find_unsupported",
    "normalize",
    "source_format_version",
    "unsupported_message",
]
