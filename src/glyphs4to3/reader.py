"""Drop-in replacements for ``glyphsLib.load()`` / ``glyphsLib.loads()`` that
understand Glyphs 4 sources.

``glyphsLib.parser.loads()`` is only ``openstep_plist.loads()`` followed by
``Parser.parse_into_object(GSFont(), the_dict)``. Since ``parse_into_object``
takes an already-parsed dict, the conversion in :mod:`glyphs4to3.normalize`
slots in between the two steps: openstep_plist reads format 4 happily - the
plist layer is version agnostic - so no text is ever re-serialised.
"""

from __future__ import annotations

import os
from typing import IO, Any, Union

import glyphsLib.classes
import openstep_plist
from glyphsLib.classes import GSFont
from glyphsLib.parser import Parser

from .exceptions import UnsupportedSourceError
from .normalize import (
    NormalizeReport,
    PlistDict,
    find_unsupported,
    normalize,
    unsupported_message,
)

#: Anything :func:`load` accepts: a path, or an open text/binary file.
Source = Union[str, "os.PathLike[str]", IO[str], IO[bytes]]


def loads_with_report(text: str) -> tuple[GSFont, NormalizeReport]:
    """Read a .glyphs source from a string, converting Glyphs 4 if needed.

    :param text: The text content of the .glyphs file.
    :returns: ``(font, report)``. ``report.converted`` is False for a format 2
        or 3 source, which takes the same path glyphsLib would have taken.
    :raises UnsupportedSourceError: The source uses a format 4 construct that
        has no format 3 equivalent.
    :raises UnknownFormatVersionError: The format version is newer than 4.
    """
    # The same call glyphsLib.parser.loads() makes. Note that it does not
    # apply Parser._fl7_format_clean() either, so FontLab 7 sources behave
    # exactly as they do through glyphsLib.
    source: PlistDict = openstep_plist.loads(text, use_numbers=True)

    findings = find_unsupported(source)
    if findings:
        raise UnsupportedSourceError(unsupported_message(findings))

    report = normalize(source)

    # Hand the effective version to the Parser up front. Its default is 2 and
    # ".formatVersion" is what raises it, so glyphsLib's own loads() reads the
    # nodes of a source that puts the version last with the format 2 reader.
    # This does not; _set_format_version_first() is the other half of that
    # defence, for GSFont.format_version, which the UFO builder reads.
    parser = Parser(
        current_type=glyphsLib.classes.GSFont,
        format_version=(3 if report.source_version >= 3 else 2),
    )
    font = glyphsLib.classes.GSFont()
    parser.parse_into_object(font, source)
    return (font, report)


def loads(text: str) -> GSFont:
    """Read a .glyphs source from a string. Drop-in for ``glyphsLib.loads()``.

    Discards the conversion report; use :func:`loads_with_report` to keep it.
    """
    return loads_with_report(text)[0]


def load_with_report(source: Source) -> tuple[GSFont, NormalizeReport]:
    """Read a .glyphs source from a path or open file.

    :param source: A filesystem path, or a file open in text or binary mode.
    :returns: ``(font, report)``, as :func:`loads_with_report`.
    """
    return loads_with_report(_read_text(source))


def load(source: Source) -> GSFont:
    """Read a .glyphs source from a path or open file.

    Drop-in for ``glyphsLib.load()`` and for ``GSFont(path)``. Discards the
    conversion report; use :func:`load_with_report` to keep it.
    """
    return load_with_report(source)[0]


def _read_text(source: Source) -> str:
    read = getattr(source, "read", None)
    if callable(read):
        data: Any = read()
        return data.decode("utf-8") if isinstance(data, bytes) else str(data)
    path = os.fspath(source)  # type: ignore[arg-type]
    if os.path.isdir(path):
        # A .glyphspackage is a directory of plists; glyphsLib reads it with
        # load_glyphspackage() and this package has not been verified for it.
        raise IsADirectoryError(
            f"{path} looks like a .glyphspackage; glyphs4to3 reads single-file "
            ".glyphs sources only."
        )
    with open(path, encoding="utf-8") as handle:
        return handle.read()


__all__ = ["Source", "load", "load_with_report", "loads", "loads_with_report"]
