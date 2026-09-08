"""
Unit tests of the Glyphs 4 -> Glyphs 3 conversion.

The conversion takes an already-parsed dict, so most fixtures are dict
literals. Only the tests that go through loads() need .glyphs text, and that
text is the smallest source glyphsLib will read.
"""
import copy

import glyphsLib
import openstep_plist
import pytest

import glyphs4to3


def v4_dict(**overrides):
    """
    A minimal parsed version 4 source: one axis, one master, one instance and
    one glyph with a single three-node path.
    """
    d = {
        ".appVersion": "4004",
        ".formatVersion": 4,
        "axes": [{"tag": "wght",
                  "names": [{"language": "dflt", "value": "Weight"}]}],
        "fontMaster": [{"axesValues": [100], "id": "m01"}],
        "glyphs": [{
            "glyphname": "A",
            "unicode": 65,
            "layers": [{
                "layerId": "m01",
                "width": 500,
                "shapes": [{"closed": 1,
                            "nodes": [[100, 200, "l"], [300, 400, "l"],
                                      [300, 200, "l"]]}],
            }],
        }],
        "instances": [{
            "axesValues": [100],
            "properties": [{"key": "styleNames",
                            "values": [{"language": "dflt", "value": "Condensed"}]}],
        }],
        "properties": [{"key": "familyNames",
                        "values": [{"language": "dflt", "value": "Roobert"}]}],
        "unitsPerEm": 1000,
    }
    d.update(overrides)
    return d


def v3_dict(**overrides):
    """
    The same source as a version 3 one, with the names where v3 puts them.
    """
    d = v4_dict()
    d[".appVersion"] = "3300"
    d[".formatVersion"] = 3
    d["familyName"] = "Roobert"
    d["axes"] = [{"tag": "wght", "name": "Weight"}]
    d["instances"] = [{"axesValues": [100], "name": "Condensed"}]
    del d["properties"]
    d.update(overrides)
    return d


def to_text(d):
    """
    Serialize a fixture dict back to .glyphs text, for the loads() tests.

    sort_keys=False on purpose: the key order is what the ".formatVersion"
    ordering test is about, and dumps() would otherwise sort it back to the
    front.
    """
    return openstep_plist.dumps(d, sort_keys=False)


def only_layer(d):
    return d["glyphs"][0]["layers"][0]


def only_shape(d):
    return only_layer(d)["shapes"][0]


# -- group A: the relocations ----------------------------------------------

def test_family_name_is_lifted_from_properties():
    d = v4_dict()
    result = glyphs4to3.normalize(d)
    assert d["familyName"] == "Roobert"
    assert result.converted is True
    assert any("familyName" in line for line in result.renamed)


def test_family_name_is_not_overwritten():
    """An explicit top-level familyName wins - we only fill in what is missing."""
    d = v4_dict(familyName="Explicit")
    glyphs4to3.normalize(d)
    assert d["familyName"] == "Explicit"


def test_family_name_prefers_the_default_language():
    d = v4_dict(properties=[{"key": "familyNames", "values": [
        {"language": "ENG", "value": "English"},
        {"language": "dflt", "value": "Default"},
        {"language": "CZE", "value": "Czech"},
    ]}])
    glyphs4to3.normalize(d)
    assert d["familyName"] == "Default"


def test_family_name_falls_back_to_eng_then_first():
    d = v4_dict(properties=[{"key": "familyNames", "values": [
        {"language": "CZE", "value": "Czech"},
        {"language": "ENG", "value": "English"},
    ]}])
    glyphs4to3.normalize(d)
    assert d["familyName"] == "English"

    d = v4_dict(properties=[{"key": "familyNames", "values": [
        {"language": "CZE", "value": "Czech"},
    ]}])
    glyphs4to3.normalize(d)
    assert d["familyName"] == "Czech"


def test_instance_name_is_lifted_from_properties():
    """Without this every version 4 instance would be called "Regular"."""
    d = v4_dict()
    result = glyphs4to3.normalize(d)
    assert d["instances"][0]["name"] == "Condensed"
    assert any("instance" in line for line in result.renamed)


def test_instance_name_is_not_overwritten():
    d = v4_dict()
    d["instances"][0]["name"] = "Explicit"
    glyphs4to3.normalize(d)
    assert d["instances"][0]["name"] == "Explicit"


def test_axis_name_is_lifted_from_names():
    """GSAxis parses only tag/hidden, so "names" would stay inert."""
    d = v4_dict()
    result = glyphs4to3.normalize(d)
    assert d["axes"][0]["name"] == "Weight"
    assert any("axis" in line for line in result.renamed)


def test_axis_name_is_not_overwritten():
    d = v4_dict()
    d["axes"][0]["name"] = "Explicit"
    glyphs4to3.normalize(d)
    assert d["axes"][0]["name"] == "Explicit"


def test_non_numeric_app_version_is_coerced():
    """glyphsLib's builder does int(font.appVersion) < 895."""
    d = v4_dict()
    d[".appVersion"] = "4.0"
    glyphs4to3.normalize(d)
    assert int(d[".appVersion"])


def test_numeric_app_version_is_left_alone():
    d = v4_dict()
    glyphs4to3.normalize(d)
    assert d[".appVersion"] == "4004"


# -- group B: the editor-only keys -----------------------------------------

def test_editor_only_keys_are_dropped():
    d = v4_dict()
    d["fontMaster"][0]["active"] = 1
    d["instances"][0]["id"] = "i01"
    d["glyphs"][0]["group"] = "Letters"
    d["glyphs"][0]["groupIdx"] = 3
    only_layer(d)["active"] = 1
    only_layer(d)["anchors"] = [{"name": "top", "pos": [1, 2], "attr": {}}]
    only_shape(d)["attr"] = {"hidden": 1}
    d["settings"] = {"gridLength": 2, "dependencies": {"a": "b"}}

    glyphs4to3.normalize(d)

    assert "active" not in d["fontMaster"][0]
    assert "id" not in d["instances"][0]
    assert "group" not in d["glyphs"][0]
    assert "groupIdx" not in d["glyphs"][0]
    assert "active" not in only_layer(d)
    assert "attr" not in only_layer(d)["anchors"][0]
    assert "hidden" not in only_shape(d)["attr"]
    assert "dependencies" not in d["settings"]
    # the grid keys are NOT a version 4 change - glyphsLib reads them from
    # settings in version 3 too, so they must survive untouched
    assert d["settings"]["gridLength"] == 2


def test_dropped_keys_are_counted_not_listed():
    """layer.active is on every layer of every glyph - one log line, not N."""
    d = v4_dict()
    d["glyphs"][0]["layers"] = [
        {"layerId": f"m{i:02d}", "active": 1} for i in range(3)]
    result = glyphs4to3.normalize(d)
    assert result.dropped["layer.active"] == 3
    assert result.dropped_lines() == ["layer.active: 3"]


def test_bucket_b_does_not_touch_userdata():
    """
    userData holds designer-authored content. A generic recursion looking for
    key names would eat it; the walk is explicit for exactly this reason.
    """
    d = v4_dict()
    d["glyphs"][0]["userData"] = {"active": 1, "group": "x", "hidden": 1}
    only_layer(d)["userData"] = {"active": 1}
    glyphs4to3.normalize(d)
    assert d["glyphs"][0]["userData"] == {"active": 1, "group": "x", "hidden": 1}
    assert only_layer(d)["userData"] == {"active": 1}


def test_background_layers_are_walked_too():
    d = v4_dict()
    only_layer(d)["background"] = {"active": 1, "shapes": []}
    result = glyphs4to3.normalize(d)
    assert "active" not in only_layer(d)["background"]
    assert result.dropped["layer.active"] == 1


# -- group C: what must be refused -----------------------------------------

def test_higher_order_interpolation_nodes_are_rejected():
    d = v4_dict()
    d["glyphs"][0]["glyphname"] = "aacute"
    only_layer(d)["name"] = "Bold"
    only_shape(d)["nodes"][1] = [300, 400, "l", {"hoi": {"wght": {"ip": [1, 2]}}}]

    findings = glyphs4to3.find_unsupported(d)
    message = glyphs4to3.unsupported_message(findings)
    assert "nodeAttr.hoi" in message
    assert "'aacute'" in message
    assert "'Bold'" in message


def test_a_fourth_node_element_that_is_userdata_is_fine():
    """GSNode.read_v3 already accepts a fourth element as userData."""
    d = v4_dict()
    only_shape(d)["nodes"][1] = [300, 400, "l", {"name": "top"}]
    assert glyphs4to3.find_unsupported(d) == []


def test_shape_groups_are_rejected():
    """
    _parse_shapes_dict branches on "ref" and otherwise builds a GSPath, so a
    group would become an empty path and its outlines would vanish silently.
    """
    d = v4_dict()
    only_layer(d)["shapes"].append({"groupId": "g1"})
    message = glyphs4to3.unsupported_message(glyphs4to3.find_unsupported(d))
    assert "shapeGroup" in message
    assert "'A'" in message


def test_an_unknown_shape_kind_is_rejected():
    """Neither a component nor a path - caught without knowing its name."""
    d = v4_dict()
    only_layer(d)["shapes"].append({"somethingNew": 1})
    assert any(f.feature == "shapeGroup" for f in glyphs4to3.find_unsupported(d))


def test_an_empty_path_is_not_mistaken_for_a_group():
    """A version 3 GSPath with no nodes serializes without the "nodes" key."""
    d = v4_dict()
    only_layer(d)["shapes"].append({"closed": 1})
    assert glyphs4to3.find_unsupported(d) == []


def test_deferred_layer_coordinates_are_rejected():
    """
    A version 4 brace layer may say "use the axis default" instead of giving a
    number, and this service does use brace layers.
    """
    d = v4_dict()
    only_layer(d)["attr"] = {"coordinates": [100, "default"]}
    assert any(f.feature == "layerAttr.coordinates"
               for f in glyphs4to3.find_unsupported(d))


@pytest.mark.parametrize("coordinates", [
    [100, 50.5],
    ["600", 0],         # Glyphs quotes numbers here and glyphsLib does float()
])
def test_numeric_layer_coordinates_are_fine(coordinates):
    d = v4_dict()
    only_layer(d)["attr"] = {"coordinates": coordinates}
    assert glyphs4to3.find_unsupported(d) == []


def test_contextual_kerning_is_rejected():
    d = v4_dict(kerningContext={"ctx": {"m01": 10}})
    message = glyphs4to3.unsupported_message(glyphs4to3.find_unsupported(d))
    assert "kerningContext" in message
    assert "font level" in message


@pytest.mark.parametrize("d", [
    {"kerningContext": {}},
    {"kerningContext": None},
])
def test_an_empty_kerning_context_is_not_rejected(d):
    """Nothing to lose, and Glyphs may well write the key unconditionally."""
    assert glyphs4to3.find_unsupported(v4_dict(**d)) == []


def test_empty_smart_glyph_axes_are_not_rejected():
    d = v4_dict()
    d["glyphs"][0]["axes"] = []
    assert glyphs4to3.find_unsupported(d) == []


def test_version_4_smart_glyph_axes_are_rejected():
    """
    Not a rename of partsSettings: that key still exists in version 4 and
    holds a different shape.
    """
    d = v4_dict()
    d["glyphs"][0]["axes"] = [{"name": "Height", "tag": "HGHT"}]
    assert any(f.feature == "glyph.axes" for f in glyphs4to3.find_unsupported(d))


@pytest.mark.parametrize("attr", [
    {"group": "g1"},
    {"opacity": 0.5},
    {"compositing": 1},
    {"strokeGradient": {"start": [0, 0]}},
    {"mask": 2},
    {"lineJoin": 3},
    {"strokeWidth": "$width"},
    {"gradient": {"type": "circle", "startRadius": 0}},
])
def test_version_4_shape_attributes_are_accepted(attr):
    """
    In glyphsLib the only readers of a shape's attributes are
    builder/color_layers.py and the color-layer block of builder/glyph.py, and
    this service compiles monochrome outlines only - so these cannot change
    its output. Refusing them would be stricter than the version 3 path, which
    carries the same keys through today.
    """
    d = v4_dict()
    only_shape(d)["attr"] = attr
    assert glyphs4to3.find_unsupported(d) == []


def test_all_findings_are_reported_at_once():
    """
    Otherwise a customer fixes one problem and meets the next on the next
    round trip.
    """
    d = v4_dict(kerningContext={"ctx": {}})
    only_shape(d)["nodes"][0] = [100, 200, "l", {"hoi": {}}]
    message = glyphs4to3.unsupported_message(glyphs4to3.find_unsupported(d))
    assert "kerningContext" in message
    assert "nodeAttr.hoi" in message


def test_reported_locations_are_capped():
    """The message goes into transaction.json, so it must not grow with the source."""
    d = v4_dict()
    template = d["glyphs"][0]
    d["glyphs"] = []
    for i in range(40):
        glyph = copy.deepcopy(template)
        glyph["glyphname"] = f"glyph{i:02d}"
        glyph["layers"][0]["shapes"][0]["nodes"][0] = [1, 2, "l", {"hoi": {}}]
        d["glyphs"].append(glyph)

    message = glyphs4to3.unsupported_message(glyphs4to3.find_unsupported(d))
    assert f"and {40 - glyphs4to3.MAX_REPORTED_LOCATIONS} more" in message
    assert len(message) < 2000


def test_unsupported_error_is_a_value_error():
    """A caller that does not import this package can still catch it."""
    assert issubclass(glyphs4to3.UnsupportedSourceError, ValueError)
    assert issubclass(glyphs4to3.UnsupportedSourceError, glyphs4to3.Glyphs4Error)


def test_a_newer_format_version_is_refused():
    with pytest.raises(glyphs4to3.UnknownFormatVersionError) as excinfo:
        glyphs4to3.find_unsupported(v4_dict(**{".formatVersion": 5}))
    assert "format version 5" in str(excinfo.value)
    # both are Glyphs4Error, so a caller can catch one thing
    assert issubclass(glyphs4to3.UnknownFormatVersionError, glyphs4to3.Glyphs4Error)


def test_find_unsupported_does_not_mutate():
    d = v4_dict(kerningContext={"ctx": {}})
    before = copy.deepcopy(d)
    glyphs4to3.find_unsupported(d)
    assert d == before


# -- version 2 and 3 sources must be untouched -----------------------------

def test_v3_dict_is_returned_untouched():
    d = v3_dict()
    before = copy.deepcopy(d)
    result = glyphs4to3.normalize(d)
    assert result.converted is False
    assert result.source_version == 3
    assert d == before
    assert list(d) == list(before)      # including the key order


def test_v2_dict_is_returned_untouched():
    d = v3_dict()
    del d[".formatVersion"]
    before = copy.deepcopy(d)
    result = glyphs4to3.normalize(d)
    assert result.converted is False
    assert result.source_version == 2
    assert d == before


def test_find_unsupported_is_quiet_on_v3():
    d = v3_dict(kerningContext={"ctx": {}})
    assert glyphs4to3.find_unsupported(d) == []


# -- through glyphsLib -----------------------------------------------------

def test_loads_reads_a_v4_source():
    (font, result) = glyphs4to3.loads_with_report(to_text(v4_dict()))
    assert result.converted is True
    assert font.familyName == "Roobert"          # would be "Unnamed font"
    assert font.format_version == 3
    assert font.instances[0].name == "Condensed"
    assert font.axes[0].name == "Weight"
    node = font.glyphs[0].layers[0].paths[0].nodes[0]
    assert (node.position.x, node.position.y) == (100, 200)


def test_loads_matches_glyphslib_on_a_v3_source():
    text = to_text(v3_dict())
    (ours, result) = glyphs4to3.loads_with_report(text)
    theirs = glyphsLib.loads(text)
    assert result.converted is False
    assert ours.familyName == theirs.familyName
    assert ours.format_version == theirs.format_version == 3
    assert ([(n.position.x, n.position.y)
             for n in ours.glyphs[0].layers[0].paths[0].nodes]
            == [(n.position.x, n.position.y)
                for n in theirs.glyphs[0].layers[0].paths[0].nodes])


def test_format_version_last_still_reads_v3_nodes():
    """
    ".formatVersion" is what sets parser.format_version, and
    _parse_dict_into_object walks the keys in insertion order - so a source
    that puts it last has its version 3 node lists read by the version 2
    reader. glyphs4to3.loads() hands the version to the Parser up front instead.
    """
    d = v3_dict()
    version = d.pop(".formatVersion")
    d[".formatVersion"] = version        # move it to the end
    text = to_text(d)

    # Upstream currently mis-reads this input, which is what makes the
    # assertions below more than a tautology. Deliberately not asserted: when
    # a future glyphsLib fixes its key-order handling, this test should keep
    # passing rather than start failing on somebody else's bug fix.
    try:
        glyphsLib.loads(text)
    except TypeError:
        pass

    (font, _report) = glyphs4to3.loads_with_report(text)
    node = font.glyphs[0].layers[0].paths[0].nodes[0]
    assert (node.position.x, node.position.y) == (100, 200)
    assert font.format_version == 3


def test_loads_rejects_a_bucket_c_source():
    d = v4_dict()
    only_shape(d)["nodes"][0] = [100, 200, "l", {"hoi": {}}]
    with pytest.raises(glyphs4to3.UnsupportedSourceError) as excinfo:
        glyphs4to3.loads(to_text(d))
    assert "nodeAttr.hoi" in str(excinfo.value)
