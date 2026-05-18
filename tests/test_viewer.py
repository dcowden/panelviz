from pathlib import Path

from panelviz.parser import parse_panel_yaml
from panelviz.routing import WireRouter
from panelviz.viewer import viewer_data, write_static_viewer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


def test_viewer_data_contains_components_wires_styles_and_pin_anchors():
    parsed = parse_panel_yaml((PROJECT_ROOT / "mycnc.yml").read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)

    data = viewer_data(router, units=parsed.config.units, columns=3)

    assert data["canvas"]["width"] > 0
    assert {component["name"] for component in data["components"]} >= {"contactor_110", "live_power_t"}
    assert len(data["wires"]) == 133
    assert data["styles"]["nets"]["earth"]["color"] == "#16a34a"
    earth_wire = next(wire for wire in data["wires"] if wire["net"] == "earth")
    assert earth_wire["style"]["color"] == "#16a34a"
    assert data["wires"][0]["awg"] == 12
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
    assert len({endpoint["label"]["x"] for endpoint in contactor_a1_endpoints}) == 2
    assert data["wires"][0]["from_component"] == "wall_plug"
    assert data["wires"][0]["from_pin"] == "GND"
    assert "unconnected_pins" in data["diagnostics"]
    assert any(item["node"] == "estop_relay.COM" for item in data["diagnostics"]["unconnected_pins"])


def test_write_static_viewer_writes_no_build_browser_bundle():
    parsed = parse_panel_yaml((PROJECT_ROOT / "mycnc.yml").read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    output_dir = TEST_OUTPUTS / "viewer_bundle"

    written = write_static_viewer(router, output_dir, units=parsed.config.units, columns=3)

    assert [path.name for path in written] == ["viewer.html", "viewer.css", "viewer.js", "panel-data.json"]
    assert '<script src="viewer.js"></script>' in (output_dir / "viewer.html").read_text(encoding="utf-8")
    assert "@svgdotjs/svg.js" in (output_dir / "viewer.html").read_text(encoding="utf-8")
    assert 'id="wire-table-body"' in (output_dir / "viewer.html").read_text(encoding="utf-8")
    viewer_js = (output_dir / "viewer.js").read_text(encoding="utf-8")
    assert "SVG().addTo" in viewer_js
    assert "enableZoom" in viewer_js
    assert "enableContextMenu" in viewer_js
    assert "enablePan" in viewer_js
    assert "enableTableResize" in viewer_js
    assert "rotateComponent" in viewer_js
    assert "renderWireTable" in viewer_js
    assert "sortWireTable" in viewer_js
    assert "AWG" in viewer_js
    assert "selectDiagnosticNodes" in viewer_js
    assert "labelRotation" in viewer_js
    assert "selectComponent" in viewer_js
    assert "selectPin" in viewer_js
    assert "wire-label-group" in viewer_js
    assert "component-endpoint-layer" in viewer_js
    assert "labelLocalRotation" in viewer_js
    assert "bindComponentSelectTarget" in viewer_js
    assert "endDrag(true)" in viewer_js
    viewer_css = (output_dir / "viewer.css").read_text(encoding="utf-8")
    assert "component-body" in viewer_css
    assert "wire-table-row" in viewer_css
    assert '"wires"' in (output_dir / "panel-data.json").read_text(encoding="utf-8")
