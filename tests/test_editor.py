from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from panelviz.editor import (
    EditorSession,
    _editor_document,
    _editor_js,
    append_route_to_yaml,
    delete_wire_from_yaml,
    layout_path_for_panel,
    load_layout,
    relocate_wire_endpoint_in_yaml,
    save_component_layout,
)
from panelviz.parser import parse_panel_yaml
from panelviz.routing import WireRouter


TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


EDITOR_YAML = """
components:
  source:
    type: connector
    pins:
      right: [A, B]
  block:
    type: terminal_block
    positions: 2
    pins:
      left: [A]
      right: [B]
  load:
    type: connector
    pins:
      left: [A, B]
connections:
  wires:
    - [source.A, block.1, load.A]
"""


LAYOUT_YAML = """
components:
  source:
    type: connector
    size:
      width: 1
      height: 1
    pins:
      right: [A, B]
  block:
    type: terminal_block
    size:
      width: 1
      height: 0.2
    positions: 2
    pins:
      left: [A]
      right: [B]
  load:
    type: connector
    size:
      width: 1
      height: 1
    pins:
      left: [A, B]
connections:
  wires:
    - [source.A, block.1, load.A]
"""


def write_editor_yaml(name: str, text: str = EDITOR_YAML) -> Path:
    TEST_OUTPUTS.mkdir(exist_ok=True)
    path = TEST_OUTPUTS / name
    path.write_text(text, encoding="utf-8")
    return path


def routed(path: Path) -> WireRouter:
    return WireRouter.route_parse_result(parse_panel_yaml(path.read_text(encoding="utf-8")))


def test_append_route_to_yaml_writes_short_and_object_route_rows():
    path = write_editor_yaml("editor_append.yml")

    append_route_to_yaml(path, ["source.B", "block.2", "load.B"])
    append_route_to_yaml(path, ["load.A", "block.1A"], net="RETURN", awg=18)

    text = path.read_text(encoding="utf-8")
    assert "- [source.B, block.2, load.B]" in text
    assert "route: [load.A, block.1A]" in text
    assert "net: RETURN" in text
    assert "awg: 18" in text

    router = routed(path)
    assert len(router.routed_wires) == 5
    assert router.routed_wires[2].from_pin.component == "source"
    assert router.routed_wires[2].to_pin.pin == "2A"
    assert router.routed_wires[3].from_pin.pin == "2B"
    assert router.routed_wires[4].net_name == "RETURN"


def test_delete_wire_from_yaml_splits_route_rows():
    path = write_editor_yaml("editor_delete.yml")

    delete_wire_from_yaml(path, 1)

    text = path.read_text(encoding="utf-8")
    assert "[block.1B, load.A]" in text
    router = routed(path)
    assert len(router.routed_wires) == 1
    assert str(router.routed_wires[0].from_pin) == "block.1B"


def test_relocate_wire_endpoint_updates_source_yaml_route_endpoint():
    path = write_editor_yaml("editor_relocate.yml")

    relocate_wire_endpoint_in_yaml(path, 2, "load.A", "load.B")

    assert "[source.A, block.1, load.B]" in path.read_text(encoding="utf-8")
    router = routed(path)
    assert str(router.routed_wires[1].to_pin) == "load.B"


CONFLICT_YAML = """
components:
  source:
    type: connector
    pins:
      right: [A, B]
    nets:
      - name: ONE
        pins: [A]
  load:
    type: connector
    pins:
      left: [A, B]
    nets:
      - name: TWO
        pins: [B]
connections:
  wires:
    - [source.B, load.A]
"""


def test_append_route_rejects_net_conflict_without_writing():
    path = write_editor_yaml("editor_append_conflict.yml", CONFLICT_YAML)
    before = path.read_text(encoding="utf-8")

    try:
        append_route_to_yaml(path, ["source.A", "load.B"])
    except Exception as error:
        assert "Net conflict" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected net conflict")

    assert path.read_text(encoding="utf-8") == before


def test_relocate_endpoint_rejects_net_conflict_without_writing():
    path = write_editor_yaml("editor_relocate_conflict.yml", CONFLICT_YAML)
    path.write_text(path.read_text(encoding="utf-8").replace("[source.B, load.A]", "[source.A, load.A]"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    try:
        relocate_wire_endpoint_in_yaml(path, 1, "load.A", "load.B")
    except Exception as error:
        assert "Net conflict" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected net conflict")

    assert path.read_text(encoding="utf-8") == before


def test_save_component_layout_writes_sidecar_and_applies_to_panel_data():
    path = write_editor_yaml("editor_layout.yml", LAYOUT_YAML)

    layout_path = save_component_layout(path, "source", 123.4567, 78.9, 450)

    assert layout_path == layout_path_for_panel(path)
    assert layout_path.name == "editor_layout.layout.yml"
    assert load_layout(path) == {"source": {"x": 123.457, "y": 78.9, "rotation": 90.0}}
    assert "connections:" not in layout_path.read_text(encoding="utf-8")

    data = EditorSession(path).panel_data()
    source = next(component for component in data["components"] if component["name"] == "source")
    assert source["x"] == 123.457
    assert source["y"] == 78.9
    assert source["rotation"] == 90.0
    source_center_x = source["x"] + source["width"] / 2
    source_center_y = source["y"] + source["height"] / 2
    assert data["scene"]["x"] <= source_center_x <= data["scene"]["x"] + data["scene"]["width"]
    assert data["scene"]["y"] <= source_center_y <= data["scene"]["y"] + data["scene"]["height"]
    assert data["reference_grid"]["verticals"][0] == pytest.approx(data["scene"]["x"])
    assert data["reference_grid"]["verticals"][-1] == pytest.approx(data["scene"]["x"] + data["scene"]["width"])
    assert data["reference_grid"]["horizontals"][0] == pytest.approx(data["scene"]["y"])
    assert data["reference_grid"]["horizontals"][-1] == pytest.approx(data["scene"]["y"] + data["scene"]["height"])
    source_endpoint = next(
        endpoint
        for wire in data["wires"]
        for endpoint in wire["endpoints"]
        if endpoint["component"] == "source"
    )
    assert source["x"] <= source_endpoint["anchor"]["x"] <= source["x"] + source["width"]
    assert source["y"] <= source_endpoint["anchor"]["y"] <= source["y"] + source["height"]
    assert source_endpoint["label"]["x"] > source["x"] + source["width"]


def test_editor_session_exports_wire_list_csv():
    path = write_editor_yaml("editor_wire_list.yml", LAYOUT_YAML)

    csv_text = EditorSession(path).wire_list_csv()

    assert csv_text.startswith("wirenumber,from_component,from_pin,to_component,to_pin,netname,awg")
    assert "source,A,block,1A" in csv_text
    assert "block,1B,load,A" in csv_text


def test_editor_session_exports_schematic_and_wire_list_pdf_bundle():
    path = write_editor_yaml("editor_pdf_bundle.yml", LAYOUT_YAML)

    bundle_path = TEST_OUTPUTS / "editor_pdf_bundle.zip"
    bundle_path.write_bytes(EditorSession(path).drawing_pdf_bundle())

    with ZipFile(bundle_path) as archive:
        assert archive.namelist() == ["editor_pdf_bundle_schematic.pdf", "editor_pdf_bundle_wire_list.pdf"]
        schematic = archive.read("editor_pdf_bundle_schematic.pdf")
        wire_list = archive.read("editor_pdf_bundle_wire_list.pdf")

    assert schematic.startswith(b"%PDF-")
    assert wire_list.startswith(b"%PDF-")
    assert len(schematic) > 1000
    assert len(wire_list) > 1000


def test_editor_session_exports_pdf_bundle_from_schematic_snapshot():
    path = write_editor_yaml("editor_pdf_snapshot_bundle.yml", LAYOUT_YAML)
    png_1x1 = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )

    bundle = EditorSession(path).drawing_pdf_bundle(
        {
            "image": png_1x1,
            "width": 320,
            "height": 180,
            "source_bounds": {"x": 10, "y": 20, "width": 320, "height": 180},
        }
    )

    with ZipFile(BytesIO(bundle)) as archive:
        schematic = archive.read("editor_pdf_snapshot_bundle_schematic.pdf")
        wire_list = archive.read("editor_pdf_snapshot_bundle_wire_list.pdf")

    assert schematic.startswith(b"%PDF-")
    assert wire_list.startswith(b"%PDF-")
    assert len(schematic) > 1000


def test_editor_js_refreshes_panel_data_without_full_render_when_available():
    js = _editor_js()

    assert "window.PanelVizRefreshData" in js
    assert "window.PanelVizRefreshData(data, { preserveViewBox: true })" in js
    assert "window.location.reload()" in js


def test_editor_does_not_overlay_terminal_position_route_targets():
    js = _editor_js()

    assert "terminal-position-target" not in js
    assert "addTerminalPositionTargets" not in js


def test_editor_js_exports_rendered_svg_snapshot_for_pdf_bundle():
    js = _editor_js()

    assert "/api/drawing-pdfs" in js
    assert "new XMLSerializer().serializeToString(clone)" in js
    assert "canvas.toDataURL('image/png')" in js
    assert "const maxPixels = 160000000" in js
    assert "const maxDimension = 20000" in js
    assert "Math.min(\n          4," in js
    assert "source_bounds: bounds" in js


def test_editor_document_cache_busts_local_assets():
    html = _editor_document(Path("panel.yml"))

    assert '<link rel="stylesheet" href="/viewer.css?v=' in html
    assert '<script src="/viewer.js?v=' in html
    assert '<script src="/editor.js?v=' in html
    assert 'href="/wire-list.csv"' in html
    assert "Download CSV" in html
    assert 'id="editor-download-pdfs"' in html
    assert "Download PDFs" in html
    assert 'id="toggle-reference-grid"' in html
