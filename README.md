# glyphs4to3

Read a **Glyphs 4** source (`.formatVersion = 4`) with a parser that only knows
Glyphs 3.

> **This package is deliberately transitional.** It exists only until the
> parsers themselves read format 4. See [When to delete this](#when-to-delete-this).

## The problem

Glyphs 4 writes `.formatVersion = 4` whenever a document uses a feature that
needs it. Neither [glyphsLib](https://github.com/googlefonts/glyphsLib) nor
fontc's `glyphs-reader` supports that version. glyphsLib fails deep inside the
node parser:

```
File "glyphsLib/classes.py", line 2259, in _parse_nodes_dict
File "glyphsLib/classes.py", line 2111, in read
TypeError: expected string or bytes-like object, got 'list'
```

which says nothing about the format version. (fontc is clearer — it refuses
with `"'3' is the only known format version"` — but equally cannot read the
file.)

## The fix

The failure is narrow. For *reading*, glyphsLib branches on the format version
in exactly two places: the node shape and decimal-versus-hex code points.
Format 4 uses the format 3 form for **both**, so telling the parser the source
is format 3 is correct rather than a workaround.

What actually differs is a handful of relocated keys, some editor state, and
five constructs with no format 3 equivalent. This package converts the first,
drops the second and refuses the third.

`glyphsLib.parser.loads()` is only `openstep_plist.loads()` followed by
`Parser.parse_into_object(GSFont(), the_dict)`. Since `parse_into_object` takes
an already-parsed dict, the conversion slots in between the two steps — the
plist layer is version agnostic, so no text is ever re-serialised and glyphsLib
is not patched.

## Installation

Not on PyPI on purpose: this package is meant to be deleted once upstream catches up, and a PyPI name cannot be freed again once taken. Releases are wheels attached to a GitHub Release, so pin the asset URL:

```
glyphs4to3 @ https://github.com/displaay/glyphs4to3/releases/download/v0.1.0/glyphs4to3-0.1.0-py3-none-any.whl
```

pip fetches a built wheel over plain HTTPS - no git needed in the build image, and it caches like any other wheel. For local work:

```bash
pip install -e .
```

## Usage

Drop-in for the glyphsLib calls:

```python
import glyphs4to3

font = glyphs4to3.load("Font.glyphs")      # like glyphsLib.load() / GSFont(path)
font = glyphs4to3.loads(text)              # like glyphsLib.loads()
```

Both return a `glyphsLib.classes.GSFont`, and a format 2 or 3 source takes the
same path glyphsLib would have taken — the result is indistinguishable.

Keep the report when you want to log what happened:

```python
(font, report) = glyphs4to3.load_with_report("Font.glyphs")
if report.converted:
    print(report.summary())
    # format 4 -> 3, properties/familyNames -> familyName;
    # instance properties/styleNames -> instance name (72),
    # 72 editor-only keys dropped
    for line in report.dropped_lines():
        print(line)                        # instance.id: 72
```

Or work on the parsed dict directly, without glyphsLib:

```python
import openstep_plist
from glyphs4to3 import find_unsupported, normalize

source = openstep_plist.loads(text, use_numbers=True)
problems = find_unsupported(source)        # [] when the source is convertible
report = normalize(source)                 # rewrites `source` in place
```

## What it converts

Taken from the published schemas in
[GlyphsSDK](https://github.com/schriftgestalt/GlyphsSDK/tree/Glyphs4/GlyphsFileFormat),
where every format 4 element carries `"glyphsCondition": {"minVersion": 4}`.

**Relocated — converted losslessly.** Each is conditional: the target is only
filled in when it is missing, so a value the source states explicitly always
wins.

| format 4 | format 3 |
|---|---|
| `properties` → `familyNames` | top-level `familyName` |
| `instances[].properties` → `styleNames` | `instances[].name` |
| `axes[].names` | `axes[].name` |

Without these a format 4 font loads as `"Unnamed font"` with every instance
called `"Regular"` and unnamed designspace axes.

**Serialiser quirks — normalised.** Both schemas say a boolean is `1` or `0`,
but a Glyphs 4 source writes `keepAlternatesTogether = :true`, which arrives
from the plist parser as the *string* `":true"`. glyphsLib then applies
`bool()` to it, which is right for `":true"` by luck and **wrong** for
`":false"` — any non-empty string is truthy. Glyphs only serialises a boolean
that differs from its default, so a written `":false"` lands on exactly the
keys that default to true: `glyph.export = :false` would load as `export ==
True` and compile every non-exporting helper glyph into the font, and a custom
parameter `Use Typo Metrics = :false` would set the OS/2 bit the source turns
off. Coerced everywhere except `userData` (free-form author content) and
`nodes` (cost — and their only format 4 addition is refused anyway).

**Editor state — dropped and counted.** `fontMaster.active`, `layer.active`,
`glyph.group`, `glyph.groupIdx`, `anchor.attr`, `guide.attr`, `guide.slope`,
`image.attr`, `settings.dependencies`, `shapeAttr.hidden`, `instances[].id`.
None of these can affect a compiled font.

**No format 3 equivalent — refused.** A source using one of these raises
`UnsupportedSourceError`:

| construct | how it is recognised |
|---|---|
| shape groups | a shape that is neither a component nor a path |
| higher-order interpolation | a node whose fourth element carries `hoi` |
| contextual kerning | a non-empty top-level `kerningContext` |
| format 4 smart glyph axes | `glyphs[].axes` |
| deferred layer coordinates | a brace coordinate that is not a number |

These are refused rather than dropped on purpose: a discarded shape group or
higher-order interpolation node produces a font that compiles, validates and
has the wrong outlines, and a discarded `kerningContext` one with silently
missing kerning. A loud failure is the better outcome — and it is what a parser
with full format 4 support would have to do anyway, since designspace
interpolates linearly and has nowhere to put higher-order interpolation either.

The message names every offending feature and the glyphs and layers it was
found on, because the caller usually has nothing else to report.

**Deliberately not refused.** The format 4 additions to a shape's `attr` dict —
new gradient forms, `opacity`, `compositing`, `mask`, `strokeGradient`, new
line joins, expression-valued stroke sizes. glyphsLib reads a shape's
attributes only when building COLR layers, so on a monochrome outline build
they change nothing, and refusing them would be stricter than the format 3 path
which carries the same keys through today.

**Unchanged between 3 and 4**, which is why the conversion is small: nodes
(still `(x, y, type)`, with an optional fourth element that `GSNode.read_v3`
already accepts), code points (still decimal), the grid (still in `settings`),
and the overall shapes/layers/masters/instances layout.

## Maintenance

The bucket lists are curated constants in `buckets.py` rather than a vendored
copy of the schema, because the reasoning behind each entry — *why* a key is
safe to drop, or why it is not — is the part worth maintaining, and that is not
in the schema.

`tests/test_schema_audit.py` re-checks them against a newer schema on demand.
It is skipped unless one is pointed at, so the normal test run stays offline:

```bash
git clone -b Glyphs4 https://github.com/schriftgestalt/GlyphsSDK
GLYPHS4_SCHEMA=GlyphsSDK/GlyphsFileFormat/Schemas/glyphs-4.schema.json pytest
```

A failure means Glyphs grew or renamed a format 4 element. **Do not delete that
test as dead weight:** glyphsLib's `GSBase.__setitem__` is a plain `setattr`, so
it accepts any unknown key without complaint and the font then builds with a
default. The audit is the only defence against a new format 4 key being read as
an inert attribute.

On a glyphsLib bump, re-check that:

* `Parser.__init__` still takes `format_version`,
* `parser.loads()` still does nothing but `openstep_plist.loads()` plus
  `parse_into_object()`,
* those two `parser.format_version == 3` read guards are still the only
  exact-match ones on the read path.

### Known unknowns

* `component.traverseAnchors` is classified as ignorable but is **not**
  verified — no format 4 source using it has turned up yet.
* `kerningContext` is refused rather than ignored because it is unknown
  whether Glyphs 4 keeps writing ordinary kerning to `kerningLTR` or moves it.
  Losing kerning silently is the worse failure, so this errs toward refusing.
* `.glyphspackage` directories are not handled; `load()` raises on one.

## When to delete this

Check whether glyphsLib reads format 4 yet:

```python
import glyphsLib
glyphsLib.loads(open("SomeGlyphs4Font.glyphs", encoding="utf-8").read())
```

If that works, this package has done its job. Replace `glyphs4to3.load` with
`glyphsLib.load` and drop the dependency. The refusal list is the only part
worth reading first — a parser that reads format 4 still has to decide what to
do with a shape group or a higher-order interpolation node, and it may differ
from the choice made here.

Upstream tracking: glyphsLib has no format 4 issue as of 2026-09-08.

## Licence

MIT
