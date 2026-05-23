from pathlib import Path

from panelviz.parser import parse_panel_yaml
from panelviz.routing import WireRouter
from panelviz.viewer import (
    readable_center_text_rotation,
    readable_local_text_rotation_for_side,
    readable_screen_text_rotation_for_side,
    rotated_pin_side,
    screen_center_text_orientation,
    viewer_data,
    write_static_viewer,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"
VALID_PANEL = Path(__file__).resolve().parent / "fixtures" / "mycnc_valid.yml"


def test_viewer_data_contains_components_wires_styles_and_pin_anchors():
    parsed = parse_panel_yaml(VALID_PANEL.read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)

    data = viewer_data(router, units=parsed.config.units, columns=3)

    assert data["canvas"]["width"] > 0
    assert data["canvas"]["x"] < data["scene"]["x"]
    assert data["canvas"]["y"] < data["scene"]["y"]
    assert data["canvas"]["width"] > data["scene"]["width"]
    assert data["canvas"]["height"] > data["scene"]["height"]
    assert data["reference_grid"]["columns"] > 0
    assert data["reference_grid"]["rows"] > 0
    assert len(data["reference_grid"]["verticals"]) == data["reference_grid"]["columns"] + 1
    assert len(data["reference_grid"]["horizontals"]) == data["reference_grid"]["rows"] + 1
    assert data["reference_grid"]["labels"][0]["ref"] == "A1"
    assert {component["name"] for component in data["components"]} >= {"contactor_110", "live_power_t"}
    assert len(data["wires"]) == 137
    assert data["styles"]["nets"]["earth"]["color"] == "#16a34a"
    earth_wire = next(wire for wire in data["wires"] if wire["net"] == "earth")
    assert earth_wire["style"]["color"] == "#16a34a"
    assert data["wires"][0]["awg"] == 12
    assert data["wires"][0]["from_ref"]
    assert data["wires"][0]["to_ref"]
    assert data["wires"][0]["style"]["line_weight"] > data["styles"]["nets"]["earth"]["line_weight"]
    assert earth_wire["endpoints"][0]["anchor"]["x"] > 0
    assert earth_wire["endpoints"][0]["stub"]["x"] > 0
    contactor_a1_endpoints = [
        endpoint
        for wire in data["wires"]
        for endpoint in wire["endpoints"]
        if endpoint["node"] == "contactor_110.A1"
    ]
    assert len(contactor_a1_endpoints) == 2
    assert {endpoint["label"]["slot"] for endpoint in contactor_a1_endpoints} == {0, 1}
    if contactor_a1_endpoints[0]["side"] in {"top", "bottom"}:
        assert len({endpoint["label"]["y"] for endpoint in contactor_a1_endpoints}) == 2
        assert len({endpoint["label"]["x"] for endpoint in contactor_a1_endpoints}) == 1
    else:
        assert len({endpoint["label"]["x"] for endpoint in contactor_a1_endpoints}) == 2
        assert len({endpoint["label"]["y"] for endpoint in contactor_a1_endpoints}) == 1
    assert data["wires"][0]["endpoints"][0]["dot_radius"] < 2
    assert data["wires"][0]["from_component"] == "wall_plug"
    assert data["wires"][0]["from_pin"] == "GND"
    axbbe_o2 = next(
        pin
        for component in data["components"]
        if component["name"] == "axbb-e"
        for pin in component["pins"]
        if pin["node"] == "axbb-e.O2"
    )
    assert axbbe_o2["nets"] == ["VFD REV"]
    assert axbbe_o2["no_connect"] is False
    axbbe_o1 = next(
        pin
        for component in data["components"]
        if component["name"] == "axbb-e"
        for pin in component["pins"]
        if pin["node"] == "axbb-e.O1"
    )
    assert axbbe_o1["no_connect"] is True
    assert "unconnected_pins" in data["diagnostics"]
    assert any(item["node"] == "estop_relay.COM" for item in data["diagnostics"]["unconnected_pins"])


def test_write_static_viewer_writes_no_build_browser_bundle():
    parsed = parse_panel_yaml(VALID_PANEL.read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    output_dir = TEST_OUTPUTS / "viewer_bundle"

    written = write_static_viewer(router, output_dir, units=parsed.config.units, columns=3)

    assert [path.name for path in written] == ["viewer.html", "viewer.css", "viewer.js", "panel-data.json"]
    viewer_html = (output_dir / "viewer.html").read_text(encoding="utf-8")
    assert '<script src="viewer.js?v=' in viewer_html
    assert '<link rel="stylesheet" href="viewer.css?v=' in viewer_html
    assert "@svgdotjs/svg.js" in (output_dir / "viewer.html").read_text(encoding="utf-8")
    assert 'id="wire-table-body"' in (output_dir / "viewer.html").read_text(encoding="utf-8")
    viewer_js = (output_dir / "viewer.js").read_text(encoding="utf-8")
    assert "SVG().addTo" in viewer_js
    assert "enableZoom" in viewer_js
    assert "fitBoundsToViewport" in viewer_js
    assert "renderedSceneBounds" in viewer_js
    assert "enableMarqueeSelect" in viewer_js
    assert "enableContextMenu" in viewer_js
    assert "enablePan" in viewer_js
    assert "enableTableResize" in viewer_js
    assert "rotateComponent" in viewer_js
    assert "renderWireTable" in viewer_js
    assert "PanelVizRefreshData" in viewer_js
    assert "endpointOriginX" in viewer_js
    assert "const originX = component.endpointOriginX ?? component.x" in viewer_js
    assert "sortWireTable" in viewer_js
    assert "AWG" in viewer_js
    assert "From Ref" in viewer_js
    assert "To Ref" in viewer_js
    assert "from_ref" in viewer_js
    assert "to_ref" in viewer_js
    assert "selectDiagnosticNodes" in viewer_js
    assert "toggle-reference-grid" in viewer_html
    assert "renderReferenceGrid" in viewer_js
    assert "reference-grid-layer" in viewer_js
    assert "createSceneLayers" in viewer_js
    assert "physical-layer" in viewer_js
    assert "wire-label-layer" in viewer_js
    assert "interaction-layer" in viewer_js
    assert "debug-layer" in viewer_js
    assert "referenceGridFromBounds" in viewer_js
    assert "applyWireReferences" in viewer_js
    assert "referenceForPoint" in viewer_js
    assert "updateReferenceGrid" in viewer_js
    assert "readableScreenRotation" in viewer_js
    assert "stubDistance" in viewer_js
    assert "selectComponent" in viewer_js
    assert "selectPin" in viewer_js
    assert "wire-label-group" in viewer_js
    assert "terminalTextFontSize" in viewer_js
    assert "no-connect-stub" in viewer_js
    assert "no-connect-x" in viewer_js
    assert "component-endpoint-layer" in viewer_js
    assert "readableLabelLocalRotation" in viewer_js
    assert "bindComponentSelectTarget" in viewer_js
    assert "endDrag(true)" in viewer_js
    assert "dragSelectionNames" in viewer_js
    viewer_css = (output_dir / "viewer.css").read_text(encoding="utf-8")
    assert "component-body" in viewer_css
    assert "selection-marquee" in viewer_css
    assert "scene-layer" in viewer_css
    assert "debug-layer" in viewer_css
    assert "interaction-layer" in viewer_css
    assert "group-selected" in viewer_css
    assert "no-connect-stub" in viewer_css
    assert "no-connect-x" in viewer_css
    assert "wire-table-row" in viewer_css
    assert "reference-grid-label" in viewer_css
    assert '"Segoe UI", Arial, Helvetica, sans-serif' in viewer_css
    assert "font-weight: 900" in viewer_css
    assert '"wires"' in (output_dir / "panel-data.json").read_text(encoding="utf-8")
    assert '"reference_grid"' in (output_dir / "panel-data.json").read_text(encoding="utf-8")


def test_viewer_layout_honors_component_terminal_width_override():
    parsed = parse_panel_yaml(
        """
config:
  units:
    length: in
components:
  default_terminal:
    type: connector
    size:
      width: 1
      height: 1
    pins:
      bottom: [A]
  wide_terminal:
    type: connector
    size:
      width: 1
      height: 1
      terminal_width: 0.25
    pins:
      bottom: [A]
connections:
  wires:
    - [default_terminal.A, wide_terminal.A]
"""
    )
    router = WireRouter.route_parse_result(parsed)

    data = viewer_data(router, units=parsed.config.units, columns=2)
    components = {component["name"]: component for component in data["components"]}
    default_pin = components["default_terminal"]["pins"][0]
    wide_pin = components["wide_terminal"]["pins"][0]

    assert wide_pin["width"] > default_pin["width"]
    assert wide_pin["height"] > default_pin["height"]
    endpoints = data["wires"][0]["endpoints"]
    default_label = next(endpoint["label"] for endpoint in endpoints if endpoint["component"] == "default_terminal")
    wide_label = next(endpoint["label"] for endpoint in endpoints if endpoint["component"] == "wide_terminal")

    assert default_label["height"] == default_pin["width"]
    assert wide_label["height"] == wide_pin["width"]
    assert wide_label["font_size"] > default_label["font_size"]
    assert wide_label["corner_radius"] < wide_label["height"] / 2


def test_viewer_text_orientation_contract_keeps_component_labels_readable():
    for rotation in (0, 90, 180, 270):
        horizontal_local = readable_center_text_rotation("horizontal", rotation)
        vertical_local = readable_center_text_rotation("vertical", rotation)

        assert (horizontal_local + rotation) % 360 == 0
        assert (vertical_local + rotation) % 360 == 270


def test_viewer_center_text_orientation_uses_rotated_screen_shape():
    assert screen_center_text_orientation(144, 34, "switched_110N", 14, 0) == "horizontal"
    assert screen_center_text_orientation(144, 34, "switched_110N", 14, 90) == "vertical"
    assert screen_center_text_orientation(144, 34, "switched_110N", 14, 270) == "vertical"
    assert screen_center_text_orientation(144, 34, "switched_110N", 14, 180) == "horizontal"


def test_viewer_text_orientation_contract_keeps_terminal_labels_consistent():
    sides = ("top", "right", "bottom", "left")

    for rotation in (0, 90, 180, 270):
        for side in sides:
            local_rotation = readable_local_text_rotation_for_side(side, rotation)
            screen_rotation = (local_rotation + rotation) % 360
            screen_side = rotated_pin_side(side, rotation)
            expected_screen_rotation = readable_screen_text_rotation_for_side(side, rotation) % 360

            assert screen_rotation == expected_screen_rotation
            assert screen_rotation in {0, 270}
            if screen_side in {"top", "bottom"}:
                assert screen_rotation == 270
            else:
                assert screen_rotation == 0
