"""What changed between Glyphs file format 3 and 4, as three curated lists.

Taken from the published schemas in ``github.com/schriftgestalt/GlyphsSDK``,
branch ``Glyphs4``, ``GlyphsFileFormat/Schemas/glyphs-{3,4}.schema.json``,
where every format 4 element carries ``"glyphsCondition": {"minVersion": 4}``.
There are 41 such elements once the schema paths are collapsed to the
``<scope>.<key>`` shape used here.

These are curated constants rather than a vendored copy of the schema,
because the reasoning behind each entry - *why* a key is safe to drop, or why
it cannot be - is the part worth maintaining, and that reasoning is not in the
schema. ``tests/test_schema_audit.py`` re-checks the lists against a schema on
demand and is the only defence against a new format 4 key being read as an
inert attribute; glyphsLib's ``GSBase.__setitem__`` is a plain ``setattr``, so
it accepts any key without complaint and the font then builds with a default.

Audited against glyphs-4.schema.json on 2026-09-08.
"""

from __future__ import annotations

from typing import Final

#: Editor state. Dropping these cannot change the compiled font. Keyed by
#: ``"<scope>.<key>"``, where the scope is the schema ``$defs`` name.
EDITOR_ONLY: Final[dict[str, str]] = {
    "fontMaster.active": "whether the master is shown in the editor",
    "instance.id": "an editor-side identifier; instances are matched by name",
    "glyph.group": "the glyph's group in the font view sidebar",
    "glyph.groupIdx": "the glyph's position within that group",
    "layer.active": "whether the layer is shown in the editor",
    "anchor.attr": "editor-side anchor attributes; the position is separate",
    "guide.attr": "editor-side guide attributes",
    "guide.slope": "an editor guide property; guides never reach the outlines",
    "image.attr": "attributes of the placed background image",
    "settings.dependencies": "the dependency class names shown in the UI",
    "shapeAttr.hidden": "whether the shape is hidden in the editor",
}

#: Constructs with no format 3 equivalent, mapped to the wording used in the
#: error message. Refused rather than dropped - see UnsupportedSourceError.
UNSUPPORTED: Final[dict[str, str]] = {
    "kerningContext": "contextual kerning",
    "glyph.axes": "smart glyph axes in the format 4 form",
    "shapeGroup": "shape groups",
    "nodeAttr.hoi": "higher-order interpolation nodes",
    "layerAttr.coordinates": "layer coordinates that defer to an axis default",
}

#: Format 4 additions that are *values* rather than schema elements. The
#: schema marks elements with ``"glyphsCondition": {"minVersion": 4}``, so a
#: new legal value for an existing element carries no marker and the audit in
#: tests/test_schema_audit.py cannot see it - which is exactly why these are
#: kept out of the three audited buckets and listed separately here. The
#: ``:true`` / ``:false`` serialiser literals are the other member of this
#: category; they are coerced in normalize() rather than refused.
UNSUPPORTED_VALUES: Final[dict[str, str]] = {
    "node.type": "node curve types that no Glyphs 3 reader maps",
}

#: The node type letters ``GSNode.read_v3`` maps. It branches on the first
#: character only - a trailing "s" means smooth - and every other letter falls
#: through to ``node_type = None``, which is a node with no curve type: the
#: outline is silently wrong rather than refused. Kept as an allowlist so a
#: letter Glyphs adds tomorrow is refused too, not just the three seen so far.
READABLE_NODE_TYPES: Final[frozenset[str]] = frozenset("colq")

#: Human names for the format 4 node type letters seen so far, for the error
#: message. An unlisted letter is still refused, just not named.
NODE_TYPE_NAMES: Final[dict[str, str]] = {
    "u": "quartic",
    "h": "Hobby",
    "r": "Raph New Spiral",
}

#: The format 4 additions to a shape's ``attr`` dict - new gradient forms, new
#: stroke and line-join values, opacity, compositing, masking.
_SHAPE_ATTR: Final[str] = (
    "a shape attribute; glyphsLib reads these only when building COLR layers, "
    "so they do not affect a monochrome outline build"
)

#: Format 4 elements that are deliberately neither converted nor refused, with
#: the reason. Nothing reads this at run time; it exists so the schema audit
#: can be exact about what is accounted for.
IGNORED: Final[dict[str, str]] = {
    "axis.names": "converted: filled into axis.name when that is missing",
    "axis.userData": "editor-side data hanging off an axis",
    "color": "the format 4 0..1 component form of an editor swatch or a COLR "
             "palette entry",
    "palettes": "the format 4 form of the Color Palettes custom parameter",
    "lineCap": "new stroke cap alignment modes",
    "hint.type": "new hint types; Glyphs hints do not survive into a compiled "
                 "font here anyway",
    "component.traverseAnchors": "a component flag about anchor propagation. "
                                 "NOT verified against a real source - no "
                                 "format 4 sample using it has turned up yet",
    "node": "the node tuple gained an optional fourth element; "
            "GSNode.read_v3 already accepts one and reads it as userData. The "
            "*type* letter also gained format 4 values, but those are values "
            "rather than schema elements - see UNSUPPORTED_VALUES",
    "nodeAttr": "the fourth node element itself; only its 'hoi' key has no "
                "format 3 equivalent, and that is in UNSUPPORTED",
    "shape": "the shape union gained the shapeGroup member, which is refused "
             "under 'shapeGroup'",
    "gradient": _SHAPE_ATTR,
    "gradient.type": _SHAPE_ATTR,
    "gradient.angle": _SHAPE_ATTR,
    "gradient.startRadius": _SHAPE_ATTR,
    "gradient.endRadius": _SHAPE_ATTR,
    "gradientExtend": _SHAPE_ATTR,
    "shapeAttr.group": _SHAPE_ATTR + "; a shape group itself is still refused",
    "shapeAttr.opacity": _SHAPE_ATTR,
    "shapeAttr.compositing": _SHAPE_ATTR,
    "shapeAttr.strokeGradient": _SHAPE_ATTR,
    "shapeAttr.mask": _SHAPE_ATTR,
    "shapeAttr.lineJoin": _SHAPE_ATTR,
    "shapeAttr.strokeWidth": _SHAPE_ATTR,
    "shapeAttr.strokePos": _SHAPE_ATTR,
    "shapeAttr.strokeHeight": _SHAPE_ATTR,
}


def editor_only_by_scope() -> dict[str, set[str]]:
    """Group :data:`EDITOR_ONLY` into ``{scope: {key, ...}}`` for the walk."""
    index: dict[str, set[str]] = {}
    for path in EDITOR_ONLY:
        (scope, key) = path.split(".", 1)
        index.setdefault(scope, set()).add(key)
    return index
