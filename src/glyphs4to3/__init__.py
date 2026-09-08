"""glyphs4to3 -- read a Glyphs 4 source with a parser that only knows
Glyphs 3.

Glyphs 4 writes ``.formatVersion = 4`` whenever a document uses a feature that
needs it. Neither glyphsLib nor fontc's glyphs-reader supports that version, so
such a source fails deep inside the node parser with ``TypeError: expected
string or bytes-like object, got 'list'`` -- a message that says nothing about
the format version.

The failure is narrow. For *reading*, glyphsLib branches on the format version
in exactly two places: the node shape and decimal-versus-hex code points. Format
4 uses the format 3 form for both, so telling the parser the source is format 3
is correct rather than a workaround. What actually differs is a handful of
relocated keys, some editor state, and five constructs with no format 3
equivalent.

Use it wherever you would have called glyphsLib::

    import glyphs4to3
    font = glyphs4to3.load("Font.glyphs")       # like glyphsLib.load()
    font = glyphs4to3.loads(text)               # like glyphsLib.loads()

or keep the report of what was converted::

    (font, report) = glyphs4to3.load_with_report("Font.glyphs")
    if report.converted:
        print(report.summary())

A source using a construct that cannot be downgraded raises
:class:`UnsupportedSourceError` rather than losing it silently -- a dropped
shape group or higher-order interpolation node yields a font that compiles,
validates, and is wrong.

**This package is deliberately transitional.** It exists only until the parsers
themselves read format 4; when glyphsLib does, delete it and call glyphsLib
directly. See the README for how to check.
"""

from __future__ import annotations

from .buckets import (
    EDITOR_ONLY,
    IGNORED,
    NODE_TYPE_NAMES,
    READABLE_NODE_TYPES,
    UNSUPPORTED,
    UNSUPPORTED_VALUES,
)
from .exceptions import (
    Glyphs4Error,
    UnknownFormatVersionError,
    UnsupportedSourceError,
)
from .normalize import (
    MAX_REPORTED_LOCATIONS,
    NEWEST_KNOWN_FORMAT_VERSION,
    TARGET_FORMAT_VERSION,
    Finding,
    NormalizeReport,
    PlistDict,
    find_unsupported,
    normalize,
    source_format_version,
    unsupported_message,
)
from .reader import Source, load, load_with_report, loads, loads_with_report

__version__ = "0.3.0"

__all__ = [
    "EDITOR_ONLY",
    "NODE_TYPE_NAMES",
    "READABLE_NODE_TYPES",
    "UNSUPPORTED_VALUES",
    "IGNORED",
    "MAX_REPORTED_LOCATIONS",
    "NEWEST_KNOWN_FORMAT_VERSION",
    "TARGET_FORMAT_VERSION",
    "UNSUPPORTED",
    "Finding",
    "Glyphs4Error",
    "NormalizeReport",
    "PlistDict",
    "Source",
    "UnknownFormatVersionError",
    "UnsupportedSourceError",
    "__version__",
    "find_unsupported",
    "load",
    "load_with_report",
    "loads",
    "loads_with_report",
    "normalize",
    "source_format_version",
    "unsupported_message",
]
