"""
Audit the bucket lists of glyphs4to3.buckets against a real
glyphs-4.schema.json.

Skipped unless a schema is pointed at, so the normal test run stays offline
and needs no checkout of GlyphsSDK::

    git clone -b Glyphs4 https://github.com/schriftgestalt/GlyphsSDK
    GLYPHS4_SCHEMA=GlyphsSDK/GlyphsFileFormat/Schemas/glyphs-4.schema.json \
        pytest tests/test_schema_audit.py

A failure means Glyphs grew (or renamed) a format version 4 element. Classify
it in buckets.EDITOR_ONLY, UNSUPPORTED or IGNORED, refresh the
"audited on" line in the buckets module docstring, and add a case to
tests/test_normalize.py if it is refused or normalized.

This is the only defence against a new version 4 key being read as an inert
attribute: GSBase.__setitem__ is a plain setattr, so glyphsLib accepts any key
without complaint and the font builds with a default. Do not delete this file
as dead weight.
"""
import json
import os

import pytest

from glyphs4to3 import buckets

SCHEMA_ENV = "GLYPHS4_SCHEMA"

#: Group A relocations that the schema marks as version 4 elements. The other
#: two (familyNames, styleNames) live in "properties" lists, which exist in
#: version 3 already and are therefore not marked.
NORMALIZED = {"axis.names"}


@pytest.fixture
def schema():
    path = os.environ.get(SCHEMA_ENV)
    if not path:
        pytest.skip(f"set {SCHEMA_ENV} to a glyphs-4.schema.json to run the audit")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def classify(parts):
    """
    Turn a path inside the schema into the "<scope>.<key>" shape the glyphs4
    bucket lists use.
    """
    scope = None
    keys = []
    for (i, part) in enumerate(parts):
        if part == "$defs" and i + 1 < len(parts):
            scope = parts[i + 1]
        if part == "properties" and i + 1 < len(parts):
            keys.append(parts[i + 1])
    if scope:
        return f"{scope}.{keys[-1]}" if keys else scope
    if len(keys) >= 2:
        return f"{keys[-2]}.{keys[-1]}"
    return keys[-1] if keys else "<root>"


def collect_v4_only(schema):
    """
    :returns: The classification keys of every element the schema marks with
        ``"glyphsCondition": {"minVersion": 4}``.
    """
    found = set()

    def walk(node, parts):
        if isinstance(node, dict):
            condition = node.get("glyphsCondition")
            if isinstance(condition, dict):
                minimum = (condition.get("minVersion")
                           or (condition.get("regular") or {}).get("minVersion"))
                if minimum == 4:
                    found.add(classify(parts))
            for (key, value) in node.items():
                walk(value, parts + [key])
        elif isinstance(node, list):
            for (index, value) in enumerate(node):
                walk(value, parts + [str(index)])

    walk(schema, [])
    return found


def known_keys():
    return (set(buckets.EDITOR_ONLY)
            | set(buckets.UNSUPPORTED)
            | set(buckets.IGNORED)
            | NORMALIZED)


def test_buckets_are_disjoint():
    """Needs no schema, so this one runs in every test pass."""
    b = set(buckets.EDITOR_ONLY)
    c = set(buckets.UNSUPPORTED)
    ignored = set(buckets.IGNORED)
    assert not (b & c), "in both EDITOR_ONLY and UNSUPPORTED: %s" % (b & c)
    assert not (b & ignored), "in both EDITOR_ONLY and IGNORED"
    assert not (c & ignored), "in both UNSUPPORTED and IGNORED"


def test_bucket_b_paths_are_scoped():
    """The walk indexes group B by "scope.key", so every entry needs both."""
    for path in buckets.EDITOR_ONLY:
        assert "." in path, f"{path} is not scoped"
        assert path.split(".", 1)[0] in buckets.editor_only_by_scope()


def test_every_v4_element_is_classified(schema):
    v4_only = collect_v4_only(schema)
    assert v4_only, "no minVersion:4 elements found - did the schema shape change?"
    unclassified = v4_only - known_keys()
    assert not unclassified, (
        f"unclassified Glyphs 4 elements: {sorted(unclassified)}. Put each in EDITOR_ONLY, "
        "UNSUPPORTED or IGNORED.")


def test_no_stale_entries(schema):
    """An entry the schema no longer knows about is dead code or a typo."""
    stale = known_keys() - collect_v4_only(schema)
    assert not stale, (
        f"these are no longer marked minVersion:4 in the schema: {sorted(stale)}")
