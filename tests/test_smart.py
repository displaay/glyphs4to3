"""
Format 4 smart glyph axes -> format 3 partsSettings / partSelection.

The fixture is the shape Glyphs 4 writes: the smart glyph has "axes", its
master layer sits at the axis default and each pole is a layer associated
with that master whose attr.coordinates are the font axes followed by the
glyph's own axes.
"""
import copy
import logging

import glyphsLib
import openstep_plist
import pytest
from fontTools.pens.boundsPen import BoundsPen

import glyphs4to3


def rect(width):
    return {"closed": 1, "nodes": [[0, 0, "l"], [width, 0, "l"],
                                   [width, 100, "l"], [0, 100, "l"]]}


def smart_dict(*, default=None, pole=100, piece=None):
    """
    One font axis (wght) and one master at 400. "_bar" is a smart glyph with a
    Width axis: 100 units wide at the master, 300 at the pole. "B" uses it.
    """
    axis = {"name": "Width"}
    if default is not None:
        axis["default"] = default
    return {
        ".appVersion": "4205",
        ".formatVersion": 4,
        "axes": [{"name": "Weight", "tag": "wght"}],
        "fontMaster": [{"axesValues": [400], "id": "m01", "name": "Regular"}],
        "familyName": "Smart",
        "glyphs": [
            {
                "glyphname": "_bar",
                "export": 0,
                "axes": [axis],
                "layers": [
                    {"layerId": "m01", "width": 100, "shapes": [rect(100)]},
                    {"layerId": "p01", "associatedMasterId": "m01", "name": "wide",
                     "attr": {"coordinates": [400, pole]},
                     "width": 300, "shapes": [rect(300)]},
                ],
            },
            {
                "glyphname": "B",
                "unicode": 66,
                "layers": [{"layerId": "m01", "width": 600, "shapes": [
                    {"ref": "_bar", **({"piece": piece} if piece is not None else {})},
                ]}],
            },
        ],
        "unitsPerEm": 1000,
    }


def glyph(d, name):
    return next(g for g in d["glyphs"] if g["glyphname"] == name)


def layer(d, name, layer_id):
    return next(lay for lay in glyph(d, name)["layers"] if lay["layerId"] == layer_id)


def reasons(d):
    return [f.where for f in glyphs4to3.find_unsupported(d) if f.feature == "glyph.axes"]


def decomposed_width(d):
    """The right edge of "B" once glyphsLib has interpolated its smart component."""
    font = glyphsLib.loads(openstep_plist.dumps(d, sort_keys=False)) \
        if d[".formatVersion"] == 3 else glyphs4to3.loads(
            openstep_plist.dumps(d, sort_keys=False))
    ufo = glyphsLib.to_ufos(font, minimal=True)[0]
    # decomposed here, because whether glyphsLib leaves a smart component that
    # sits at its default as a plain component differs between versions
    pen = BoundsPen(ufo)
    ufo["B"].draw(pen)
    return pen.bounds[2]


# -- the conversion --------------------------------------------------------

def test_a_two_pole_smart_glyph_is_accepted():
    assert glyphs4to3.find_unsupported(smart_dict(piece={"Width": 50})) == []


def test_axes_become_parts_settings_and_poles_part_selection():
    d = smart_dict(piece={"Width": 50})
    report = glyphs4to3.normalize(d)
    bar = glyph(d, "_bar")
    assert "axes" not in bar
    assert bar["partsSettings"] == [{"name": "Width", "bottomValue": 0, "topValue": 100}]
    assert layer(d, "_bar", "m01")["partSelection"] == {"Width": 1}
    pole = layer(d, "_bar", "p01")
    assert pole["partSelection"] == {"Width": 2}
    # left in place glyphsLib would read the pole as an intermediate layer
    assert "attr" not in pole
    assert any("partsSettings (1)" in line for line in report.renamed)


def test_a_default_at_the_top_maps_the_master_to_the_top():
    d = smart_dict(default=100, pole=0)
    glyphs4to3.normalize(d)
    assert glyph(d, "_bar")["partsSettings"] == [
        {"name": "Width", "bottomValue": 0, "topValue": 100}]
    assert layer(d, "_bar", "m01")["partSelection"] == {"Width": 2}
    assert layer(d, "_bar", "p01")["partSelection"] == {"Width": 1}


def test_the_default_marker_in_a_smart_coordinate_is_the_axis_default():
    """
    "-" means "this axis' default"; on a smart axis that is a number we know,
    so it is not the deferred-coordinate refusal. Here it puts the pole on the
    master, which is a duplicate location.
    """
    d = smart_dict(pole="-")
    assert reasons(d) == ["glyph '_bar': two layers of master 'm01' share a smart location"]
    assert not any(f.feature == "layerAttr.coordinates"
                   for f in glyphs4to3.find_unsupported(d))


def test_a_deferred_font_axis_coordinate_on_a_pole_is_refused():
    d = smart_dict()
    layer(d, "_bar", "p01")["attr"]["coordinates"] = ["-", 100]
    assert reasons(d) == [
        "glyph '_bar': layer 'wide' (master 'Regular') is an intermediate layer between masters"]


def test_a_pole_listed_before_its_master_layer_still_interpolates():
    """glyphsLib lists master layers first whatever the file order."""
    d = smart_dict(piece={"Width": 50})
    glyph(d, "_bar")["layers"].reverse()
    assert decomposed_width(d) == 200


def test_layers_outside_the_model_are_left_alone():
    d = smart_dict()
    backup = {"layerId": "b01", "associatedMasterId": "m01", "name": "backup",
              "width": 100, "shapes": [rect(100)]}
    glyph(d, "_bar")["layers"].append(backup)
    glyphs4to3.normalize(d)
    assert "partSelection" not in backup


# -- glyphsLib reads the result ---------------------------------------------

@pytest.mark.parametrize(("piece", "expected"), [
    ({"Width": 0}, 100),
    ({"Width": 50}, 200),
    ({"Width": 100}, 300),
    (None, 100),            # no piece: the master, i.e. the axis default
])
def test_glyphslib_interpolates_the_converted_smart_component(piece, expected):
    assert decomposed_width(smart_dict(piece=piece)) == expected


def test_a_top_default_interpolates_from_the_top():
    d = smart_dict(default=100, pole=0, piece={"Width": 25})
    # master (default, 100 wide) at Width=100, pole (300 wide) at Width=0
    assert decomposed_width(d) == 250


def test_the_same_source_in_format_3_interpolates_identically():
    """What a Glyphs 3 file of the same design says, read by glyphsLib alone."""
    d = smart_dict(piece={"Width": 30})
    v3 = copy.deepcopy(d)
    v3[".formatVersion"] = 3
    bar = glyph(v3, "_bar")
    del bar["axes"]
    bar["partsSettings"] = [{"name": "Width", "bottomValue": 0, "topValue": 100}]
    bar["layers"][0]["partSelection"] = {"Width": 1}
    bar["layers"][1]["partSelection"] = {"Width": 2}
    del bar["layers"][1]["attr"]
    assert decomposed_width(d) == decomposed_width(v3) == 160


# -- piece values ----------------------------------------------------------

def test_piece_keys_naming_a_font_axis_are_dropped():
    """
    Glyphs 4 writes the editor location into "piece"; glyphsLib raises
    KeyError on any key that is not one of the glyph's smart axes.
    """
    d = smart_dict(piece={"Weight": 400, "Width": 50})
    report = glyphs4to3.normalize(d)
    assert layer(d, "B", "m01")["shapes"][0]["piece"] == {"Width": 50}
    assert any("non-smart axes dropped (1)" in line for line in report.renamed)


def test_a_piece_key_that_moves_the_part_to_another_location_is_refused():
    """Glyphs 4 draws the part as it is at Weight 0; format 3 cannot say that."""
    d = smart_dict(piece={"Weight": 0, "Width": 50})
    findings = glyphs4to3.find_unsupported(d)
    assert [(f.feature, f.where) for f in findings] == [
        ("component.piece", "glyph 'B' layer 'Regular': Weight=0")]
    assert "another font location" in glyphs4to3.unsupported_message(findings)


def test_normalize_without_the_check_drops_it_with_a_warning(caplog):
    d = smart_dict(piece={"Weight": 0, "Width": 50})
    with caplog.at_level(logging.WARNING, logger="glyphs4to3"):
        glyphs4to3.normalize(d)
    assert layer(d, "B", "m01")["shapes"][0]["piece"] == {"Width": 50}
    assert "glyph 'B' layer 'Regular': Weight=0" in caplog.text


def test_a_piece_key_in_a_background_is_not_refused():
    """A background is never drawn."""
    d = smart_dict()
    layer(d, "B", "m01")["background"] = {"shapes": [
        {"ref": "_bar", "piece": {"Weight": 0, "Width": 50}}]}
    assert glyphs4to3.find_unsupported(d) == []
    glyphs4to3.normalize(d)
    assert layer(d, "B", "m01")["background"]["shapes"][0]["piece"] == {"Width": 50}


def test_a_piece_key_that_names_no_axis_is_dropped_quietly(caplog):
    d = smart_dict(piece={"Serif": 3, "Width": 50})
    assert glyphs4to3.find_unsupported(d) == []
    with caplog.at_level(logging.WARNING, logger="glyphs4to3"):
        glyphs4to3.normalize(d)
    assert layer(d, "B", "m01")["shapes"][0]["piece"] == {"Width": 50}
    assert caplog.text == ""


def test_a_matching_piece_key_is_not_logged(caplog):
    d = smart_dict(piece={"Weight": 400, "Width": 50})
    with caplog.at_level(logging.WARNING, logger="glyphs4to3"):
        glyphs4to3.normalize(d)
    assert caplog.text == ""


def test_an_emptied_piece_is_removed():
    d = smart_dict(piece={"Weight": 400})
    glyphs4to3.normalize(d)
    assert "piece" not in layer(d, "B", "m01")["shapes"][0]


def test_an_axis_without_poles_is_dropped():
    """
    Nothing moves along it. Left in, glyphsLib would look for poles the glyph
    does not have; without any axis the glyph is an ordinary component.
    """
    d = smart_dict(piece={"Width": 50})
    bar = glyph(d, "_bar")
    del bar["layers"][1]
    assert glyphs4to3.find_unsupported(d) == []
    glyphs4to3.normalize(d)
    assert "axes" not in bar and "partsSettings" not in bar
    assert "partSelection" not in bar["layers"][0]
    assert "piece" not in layer(d, "B", "m01")["shapes"][0]
    font = glyphsLib.loads(openstep_plist.dumps(d, sort_keys=False))
    ufo = glyphsLib.to_ufos(font, minimal=True)[0]
    assert [c.baseGlyph for c in ufo["B"].components] == ["_bar"]


def test_a_piece_key_of_a_dropped_axis_is_not_logged(caplog):
    d = smart_dict(piece={"Width": 50})
    del glyph(d, "_bar")["layers"][1]
    with caplog.at_level(logging.WARNING, logger="glyphs4to3"):
        glyphs4to3.normalize(d)
    assert caplog.text == ""


# -- what format 3 cannot say ----------------------------------------------

def add_pole(d, layer_id, coordinates, width=200):
    glyph(d, "_bar")["layers"].append(
        {"layerId": layer_id, "associatedMasterId": "m01", "name": layer_id,
         "attr": {"coordinates": coordinates}, "width": width, "shapes": [rect(width)]})


def test_a_third_position_on_an_axis_is_refused():
    d = smart_dict()
    add_pole(d, "p02", [400, 50])
    assert reasons(d) == ["glyph '_bar': smart axis 'Width' has 3 positions (0, 50, 100); "
                          "format 3 has only a bottom and a top"]


def test_a_non_integer_pole_is_refused():
    assert reasons(smart_dict(pole=50.5)) == [
        "glyph '_bar': smart axis 'Width' spans 0..50.5; format 3 stores whole numbers only"]


def test_a_smart_layer_between_masters_is_refused():
    d = smart_dict()
    layer(d, "_bar", "p01")["attr"]["coordinates"] = [500, 100]
    assert reasons(d) == [
        "glyph '_bar': layer 'wide' (master 'Regular') is an intermediate layer between masters"]


def test_a_coordinate_count_mismatch_is_refused():
    d = smart_dict()
    layer(d, "_bar", "p01")["attr"]["coordinates"] = [100]
    assert reasons(d) == ["glyph '_bar': layer 'wide' (master 'Regular') has 1 coordinates "
                          "for 1 font axes and 1 smart axes"]


def test_axes_next_to_parts_settings_are_refused():
    d = smart_dict()
    glyph(d, "_bar")["partsSettings"] = [{"name": "Width", "bottomValue": 0, "topValue": 1}]
    assert reasons(d) == ["glyph '_bar': has both format 3 partsSettings and format 4 axes"]


def test_a_refused_glyph_is_left_alone_by_normalize():
    d = smart_dict(pole=50.5)
    before = copy.deepcopy(glyph(d, "_bar"))
    glyphs4to3.normalize(d)
    assert glyph(d, "_bar") == before


def test_loads_names_the_reason():
    d = smart_dict(pole=50.5)
    with pytest.raises(glyphs4to3.UnsupportedSourceError) as excinfo:
        glyphs4to3.loads(openstep_plist.dumps(d, sort_keys=False))
    assert "spans 0..50.5" in str(excinfo.value)


def test_find_unsupported_does_not_mutate_a_smart_glyph():
    d = smart_dict(piece={"Weight": 400, "Width": 50})
    before = copy.deepcopy(d)
    glyphs4to3.find_unsupported(d)
    assert d == before


# -- two axes --------------------------------------------------------------

def test_two_smart_axes_map_each_pole_on_its_own():
    d = smart_dict()
    glyph(d, "_bar")["axes"].append({"name": "Height"})
    layer(d, "_bar", "p01")["attr"]["coordinates"] = [400, 100, 0]
    add_pole(d, "p02", [400, 0, 50])
    assert glyphs4to3.find_unsupported(d) == []
    glyphs4to3.normalize(d)
    assert glyph(d, "_bar")["partsSettings"] == [
        {"name": "Width", "bottomValue": 0, "topValue": 100},
        {"name": "Height", "bottomValue": 0, "topValue": 50},
    ]
    assert layer(d, "_bar", "m01")["partSelection"] == {"Width": 1, "Height": 1}
    assert layer(d, "_bar", "p01")["partSelection"] == {"Width": 2, "Height": 1}
    assert layer(d, "_bar", "p02")["partSelection"] == {"Width": 1, "Height": 2}


# -- several masters -------------------------------------------------------

def add_master(d, master_id, weight):
    d["fontMaster"].append({"axesValues": [weight], "id": master_id, "name": master_id})
    glyph(d, "B")["layers"].append(
        {"layerId": master_id, "width": 600, "shapes": [{"ref": "_bar", "piece": {"Width": 50}}]})
    glyph(d, "_bar")["layers"].append(
        {"layerId": master_id, "width": 100, "shapes": [rect(100)]})


def test_poles_on_every_master_are_accepted():
    d = smart_dict(piece={"Width": 50})
    add_master(d, "m02", 700)
    add_pole(d, "p02", [700, 100])
    layer(d, "_bar", "p02")["associatedMasterId"] = "m02"
    assert glyphs4to3.find_unsupported(d) == []


def test_a_master_without_the_poles_of_the_others_is_refused():
    """
    glyphsLib would draw a plain component on that master, with the Width
    the source asks for ignored.
    """
    d = smart_dict(piece={"Width": 50})
    add_master(d, "m02", 700)
    assert reasons(d) == ["glyph '_bar': masters 'm01' and 'm02' have different smart poles"]


@pytest.mark.parametrize("kind", [
    {"axisRules": [{"min": 500}]},
    {"color": 1},
    {"colorPalette": 0},
])
def test_a_pole_that_is_also_another_layer_kind_is_refused(kind):
    d = smart_dict()
    layer(d, "_bar", "p01")["attr"].update(kind)
    assert reasons(d) == [
        "glyph '_bar': layer 'wide' (master 'Regular') is also a bracket or colour layer"]


def test_piece_keys_are_cleaned_for_a_format_3_style_smart_glyph_too():
    """partsSettings is still legal in format 4, and so is the editor location in piece."""
    d = smart_dict(piece={"Weight": 400, "Width": 50})
    bar = glyph(d, "_bar")
    del bar["axes"]
    bar["partsSettings"] = [{"name": "Width", "bottomValue": 0, "topValue": 100}]
    bar["layers"][0]["partSelection"] = {"Width": 1}
    bar["layers"][1]["partSelection"] = {"Width": 2}
    del bar["layers"][1]["attr"]
    glyphs4to3.normalize(d)
    assert layer(d, "B", "m01")["shapes"][0]["piece"] == {"Width": 50}
    assert decomposed_width(d) == 200
