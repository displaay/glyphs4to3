"""Typed exceptions raised while reading a Glyphs 4 source."""

from __future__ import annotations


class Glyphs4Error(ValueError):
    """Base class for every error this package raises."""


class UnsupportedSourceError(Glyphs4Error):
    """The source uses a Glyphs 4 construct that has no format 3 equivalent.

    Raised instead of dropping the construct: a shape group, a higher-order
    interpolation node or contextual kerning that is silently discarded yields
    a font that compiles, validates, and has wrong outlines or missing
    kerning. The message names every offending feature and the glyphs and
    layers it was found on, because the caller usually has nothing else to
    report - nothing has been parsed at the point this is raised.
    """


class UnknownFormatVersionError(Glyphs4Error):
    """The source is a format version this package has not been verified for.

    Refused rather than guessed at: the whole premise of the conversion is a
    delta somebody actually checked against the published schemas.
    """
