"""NiceGUI-based YAML wire editor for PanelViz."""

from __future__ import annotations

import base64
import csv
import webbrowser
import zipfile
from dataclasses import dataclass
from hashlib import sha1
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse, JSONResponse, Response
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from panelviz.parser import parse_panel_yaml
from panelviz.pdf_export import DrawingMeta, diagram_reference_grid, export_schematic_pdf, export_wire_list_pdf
from panelviz.reports import WIRE_LIST_COLUMNS, wire_list_rows
from panelviz.routing import WireRouter
from panelviz.viewer import _viewer_css, _viewer_js, update_scene_bounds, viewer_data
from panelviz.visualization import component_visual_config_from_visualization


class EditorError(ValueError):
    """Raised when an editor operation cannot be applied to the YAML file."""


def append_route_to_yaml(path: str | Path, route: list[str], net: str | None = None, awg: int | None = None) -> None:
    """Append a wire or route row to a PanelViz YAML file."""

    if len(route) < 2:
        raise EditorError("A route must contain at least two endpoints")

    yaml, data = _load_roundtrip_yaml(path)
    wires = _wires_node(data)
    metadata = _metadata(net=net, awg=awg)
    wires.append(_make_wire_row(route, metadata, force_route=bool(metadata)))
    _validate_roundtrip_yaml(yaml, data)
    _write_roundtrip_yaml(path, yaml, data)


def delete_wire_from_yaml(path: str | Path, wire_index: int) -> None:
    """Delete a physical wire from the YAML file, splitting route rows when needed."""

    router = _router(path)
    routed_wire = _routed_wire_from_router(router, wire_index)
    if routed_wire.source_row_index is None or routed_wire.source_segment_index is None:
        raise EditorError(f"Wire {wire_index} does not have source YAML metadata")

    yaml, data = _load_roundtrip_yaml(path)
    wires = _wires_node(data)
    row_index = routed_wire.source_row_index
    metadata = _metadata_from_row(wires[row_index])
    replacements = [
        [str(wire.from_pin), str(wire.to_pin)]
        for wire in router.routed_wires
        if wire.source_row_index == row_index and wire.source_segment_index != routed_wire.source_segment_index
    ]

    if not replacements:
        del wires[row_index]
    else:
        wires[row_index] = _make_wire_row(replacements[0], metadata)
        for offset, replacement in enumerate(replacements[1:], start=1):
            wires.insert(row_index + offset, _make_wire_row(replacement, metadata))
    _validate_roundtrip_yaml(yaml, data)
    _write_roundtrip_yaml(path, yaml, data)


def relocate_wire_endpoint_in_yaml(
    path: str | Path,
    wire_index: int,
    endpoint_node: str,
    new_endpoint: str,
) -> None:
    """Move one endpoint of a physical wire to a new YAML endpoint."""

    routed_wire = _routed_wire(path, wire_index)
    if routed_wire.source_row_index is None or routed_wire.source_segment_index is None:
        raise EditorError(f"Wire {wire_index} does not have source YAML metadata")

    if endpoint_node == str(routed_wire.from_pin):
        route_position = routed_wire.source_segment_index
    elif endpoint_node == str(routed_wire.to_pin):
        route_position = routed_wire.source_segment_index + 1
    else:
        raise EditorError(f"Endpoint {endpoint_node!r} is not part of wire {wire_index}")

    yaml, data = _load_roundtrip_yaml(path)
    wires = _wires_node(data)
    row = wires[routed_wire.source_row_index]
    route = _route_from_row(row)
    route[route_position] = new_endpoint
    wires[routed_wire.source_row_index] = _make_wire_row(route, _metadata_from_row(row), force_route=_row_uses_route(row))
    _validate_roundtrip_yaml(yaml, data)
    _write_roundtrip_yaml(path, yaml, data)


def layout_path_for_panel(path: str | Path) -> Path:
    """Return the sidecar layout path for a panel YAML file."""

    panel_path = Path(path)
    return panel_path.with_name(f"{panel_path.stem}.layout.yml")


def load_layout(path: str | Path) -> dict[str, dict[str, float]]:
    """Load saved component positions from the sidecar layout file."""

    layout_path = layout_path_for_panel(path)
    if not layout_path.exists():
        return {}
    yaml = YAML(typ="safe")
    data = yaml.load(layout_path.read_text(encoding="utf-8")) or {}
    components = data.get("components", {}) if isinstance(data, dict) else {}
    layout: dict[str, dict[str, float]] = {}
    for name, values in components.items():
        if not isinstance(values, dict):
            continue
        entry = {}
        for key in ("x", "y", "rotation"):
            if key in values and values[key] is not None:
                entry[key] = float(values[key])
        if entry:
            layout[str(name)] = entry
    return layout


def save_component_layout(path: str | Path, component: str, x: float, y: float, rotation: float) -> Path:
    """Save one component layout entry in the sidecar file."""

    layout_path = layout_path_for_panel(path)
    yaml, data = _load_layout_roundtrip(layout_path)
    components = _layout_components_node(data)
    entry = CommentedMap()
    entry["x"] = round(float(x), 3)
    entry["y"] = round(float(y), 3)
    entry["rotation"] = int(float(rotation)) % 360
    components[str(component)] = entry
    _write_roundtrip_yaml(layout_path, yaml, data)
    return layout_path


def run_editor(
    input_file: str | Path,
    port: int = 8767,
    open_browser: bool = True,
) -> None:  # pragma: no cover - blocking UI helper
    """Run the local NiceGUI editor."""

    try:
        from nicegui import app, ui
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("NiceGUI is required for --edit. Run: pip install -e \".[dev]\"") from error

    session = EditorSession(Path(input_file).resolve())

    @app.get("/panel-data.json", response_model=None)
    def panel_data_endpoint() -> dict[str, Any] | JSONResponse:
        try:
            return JSONResponse(session.panel_data(), headers=_no_store_headers())
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=422, headers=_no_store_headers())

    @app.get("/viewer.css")
    def viewer_css_endpoint() -> Response:
        return Response(_viewer_css() + _editor_css(), media_type="text/css", headers=_no_store_headers())

    @app.get("/viewer.js")
    def viewer_js_endpoint() -> Response:
        return Response(_viewer_js(), media_type="text/javascript", headers=_no_store_headers())

    @app.get("/editor.js")
    def editor_js_endpoint() -> Response:
        return Response(_editor_js(), media_type="text/javascript", headers=_no_store_headers())

    @app.get("/wire-list.csv")
    def wire_list_csv_endpoint() -> Response:
        try:
            csv_text = session.wire_list_csv()
        except Exception as error:
            return Response(str(error), status_code=422, media_type="text/plain", headers=_no_store_headers())
        filename = f"{session.path.stem}_wire_list.csv"
        return Response(
            csv_text,
            media_type="text/csv",
            headers={
                **_no_store_headers(),
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.get("/drawing-pdfs.zip")
    def drawing_pdfs_endpoint() -> Response:
        try:
            bundle = session.drawing_pdf_bundle()
        except Exception as error:
            return Response(str(error), status_code=422, media_type="text/plain", headers=_no_store_headers())
        filename = f"{session.path.stem}_drawing_pdfs.zip"
        return Response(
            bundle,
            media_type="application/zip",
            headers={
                **_no_store_headers(),
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.post("/api/drawing-pdfs", response_model=None)
    async def drawing_pdfs_api_endpoint(payload: dict[str, Any]) -> Response:
        try:
            bundle = session.drawing_pdf_bundle(payload)
        except Exception as error:
            return Response(str(error), status_code=422, media_type="text/plain", headers=_no_store_headers())
        filename = f"{session.path.stem}_drawing_pdfs.zip"
        return Response(
            bundle,
            media_type="application/zip",
            headers={
                **_no_store_headers(),
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.post("/api/append-route", response_model=None)
    async def append_route_endpoint(payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        try:
            session.append_route(payload)
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        return {"ok": True}

    @app.post("/api/delete-wire", response_model=None)
    async def delete_wire_endpoint(payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        try:
            session.delete_wire(int(payload["wire_index"]))
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        return {"ok": True}

    @app.post("/api/relocate-wire", response_model=None)
    async def relocate_wire_endpoint(payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        try:
            session.relocate_wire(
                int(payload["wire_index"]),
                str(payload["endpoint_node"]),
                str(payload["new_endpoint"]),
            )
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        return {"ok": True}

    @app.post("/api/save-layout", response_model=None)
    async def save_layout_endpoint(payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        try:
            session.save_layout(payload)
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        return {"ok": True}

    @app.get("/")
    def editor_page() -> HTMLResponse:
        return HTMLResponse(_editor_document(session.path), headers=_no_store_headers())

    url = f"http://127.0.0.1:{port}/"
    print(f"Serving PanelViz editor at {url}")
    if open_browser:
        webbrowser.open(url)
    ui.run(host="127.0.0.1", port=port, reload=False, show=False, title="PanelViz Editor")


@dataclass
class EditorSession:
    """Mutable editor session bound to one YAML file."""

    path: Path

    def panel_data(self) -> dict[str, Any]:
        parsed = parse_panel_yaml(self.path.read_text(encoding="utf-8"))
        router = WireRouter.route_parse_result(parsed)
        visual_config = component_visual_config_from_visualization(parsed.config.visualization)
        data = viewer_data(router, units=parsed.config.units, columns=3, config=visual_config)
        self._apply_layout(data)
        update_scene_bounds(data)
        data["reference_grid"] = diagram_reference_grid(data)
        return data

    def wire_list_csv(self) -> str:
        router = _router(self.path)
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=WIRE_LIST_COLUMNS)
        writer.writeheader()
        writer.writerows(row.model_dump() for row in wire_list_rows(router))
        return output.getvalue()

    def drawing_pdf_bundle(self, snapshot: dict[str, Any] | None = None) -> bytes:
        parsed = parse_panel_yaml(self.path.read_text(encoding="utf-8"))
        router = WireRouter.route_parse_result(parsed)
        visual_config = component_visual_config_from_visualization(parsed.config.visualization)
        data = viewer_data(router, units=parsed.config.units, columns=3, config=visual_config)
        self._apply_layout(data)
        update_scene_bounds(data)
        data["reference_grid"] = diagram_reference_grid(data)
        meta = DrawingMeta.from_config(parsed.config.drawing, self.path.name)
        image_bytes, image_width, image_height, source_bounds = _snapshot_export_args(snapshot)
        schematic = export_schematic_pdf(
            router,
            data,
            meta,
            image_bytes=image_bytes,
            image_width=image_width,
            image_height=image_height,
            source_bounds=source_bounds,
        )
        wire_list_pdf = export_wire_list_pdf(router, schematic.diagram_refs, meta)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{self.path.stem}_schematic.pdf", schematic.content)
            archive.writestr(f"{self.path.stem}_wire_list.pdf", wire_list_pdf)
        return output.getvalue()

    def append_route(self, payload: dict[str, Any]) -> None:
        route = [str(endpoint) for endpoint in payload.get("route", []) if str(endpoint).strip()]
        net = str(payload.get("net") or "").strip() or None
        awg_raw = str(payload.get("awg") or "").strip()
        awg = int(awg_raw) if awg_raw else None
        append_route_to_yaml(self.path, route, net=net, awg=awg)

    def delete_wire(self, wire_index: int) -> None:
        delete_wire_from_yaml(self.path, wire_index)

    def relocate_wire(self, wire_index: int, endpoint_node: str, new_endpoint: str) -> None:
        relocate_wire_endpoint_in_yaml(self.path, wire_index, endpoint_node, new_endpoint)

    def save_layout(self, payload: dict[str, Any]) -> None:
        save_component_layout(
            self.path,
            str(payload["component"]),
            float(payload["x"]),
            float(payload["y"]),
            float(payload.get("rotation", 0)),
        )

    def _apply_layout(self, data: dict[str, Any]) -> None:
        layout = load_layout(self.path)
        for component in data.get("components", []):
            component_name = component.get("name")
            saved = layout.get(component_name)
            if not saved:
                continue
            original_x = float(component.get("x", 0))
            original_y = float(component.get("y", 0))
            if "x" in saved:
                component["x"] = saved["x"]
            if "y" in saved:
                component["y"] = saved["y"]
            if "rotation" in saved:
                component["rotation"] = saved["rotation"]
            dx = float(component.get("x", original_x)) - original_x
            dy = float(component.get("y", original_y)) - original_y
            if dx or dy:
                _shift_component_endpoint_geometry(data, str(component_name), dx, dy)


def _load_roundtrip_yaml(path: str | Path) -> tuple[YAML, Any]:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    data = yaml.load(Path(path).read_text(encoding="utf-8"))
    return yaml, data


def _load_layout_roundtrip(path: str | Path) -> tuple[YAML, Any]:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    layout_path = Path(path)
    if not layout_path.exists():
        data = CommentedMap()
        data["components"] = CommentedMap()
        return yaml, data
    data = yaml.load(layout_path.read_text(encoding="utf-8")) or CommentedMap()
    return yaml, data


def _write_roundtrip_yaml(path: str | Path, yaml: YAML, data: Any) -> None:
    stream = StringIO()
    yaml.dump(data, stream)
    Path(path).write_text(stream.getvalue(), encoding="utf-8")


def _shift_component_endpoint_geometry(data: dict[str, Any], component_name: str, dx: float, dy: float) -> None:
    for component in data.get("components", []):
        if component.get("name") != component_name:
            continue
        for pin in component.get("pins", []):
            _shift_point(pin.get("anchor"), dx, dy)
        break

    for wire in data.get("wires", []):
        for endpoint in wire.get("endpoints", []):
            if endpoint.get("component") != component_name:
                continue
            _shift_point(endpoint.get("anchor"), dx, dy)
            _shift_point(endpoint.get("stub"), dx, dy)
            _shift_point(endpoint.get("label"), dx, dy)


def _shift_point(point: Any, dx: float, dy: float) -> None:
    if not isinstance(point, dict):
        return
    if "x" in point:
        point["x"] = float(point["x"]) + dx
    if "y" in point:
        point["y"] = float(point["y"]) + dy


def _no_store_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store"}


def _snapshot_export_args(
    snapshot: dict[str, Any] | None,
) -> tuple[bytes | None, float | None, float | None, dict[str, float] | None]:
    if not snapshot:
        return None, None, None, None
    image = str(snapshot.get("image") or "")
    if not image.startswith("data:image/png;base64,"):
        raise EditorError("Schematic PDF export requires a PNG data URL")
    image_bytes = base64.b64decode(image.split(",", 1)[1])
    width = float(snapshot.get("width") or 0)
    height = float(snapshot.get("height") or 0)
    bounds_raw = snapshot.get("source_bounds") or {}
    source_bounds = {
        "x": float(bounds_raw.get("x", 0)),
        "y": float(bounds_raw.get("y", 0)),
        "width": float(bounds_raw.get("width", width or 1)),
        "height": float(bounds_raw.get("height", height or 1)),
    }
    return image_bytes, width or None, height or None, source_bounds


def _validate_roundtrip_yaml(yaml: YAML, data: Any) -> None:
    stream = StringIO()
    yaml.dump(data, stream)
    WireRouter.route_parse_result(parse_panel_yaml(stream.getvalue()))


def _wires_node(data: Any) -> CommentedSeq:
    if "connections" not in data or data["connections"] is None:
        data["connections"] = CommentedMap()
    if "wires" not in data["connections"] or data["connections"]["wires"] is None:
        data["connections"]["wires"] = CommentedSeq()
    return data["connections"]["wires"]


def _layout_components_node(data: Any) -> CommentedMap:
    if "components" not in data or data["components"] is None:
        data["components"] = CommentedMap()
    return data["components"]


def _make_wire_row(route: list[str], metadata: dict[str, Any], force_route: bool = False) -> CommentedSeq | CommentedMap:
    if not metadata and not force_route:
        return _flow_seq(route)

    row = CommentedMap()
    row["route"] = _flow_seq(route)
    if metadata.get("net") is not None:
        row["net"] = metadata["net"]
    if metadata.get("awg") is not None:
        row["awg"] = metadata["awg"]
    return row


def _flow_seq(values: list[str]) -> CommentedSeq:
    sequence = CommentedSeq(values)
    sequence.fa.set_flow_style()
    return sequence


def _route_from_row(row: Any) -> list[str]:
    if isinstance(row, list):
        return [str(endpoint) for endpoint in row]
    if isinstance(row, dict) and "route" in row:
        return [str(endpoint) for endpoint in row["route"]]
    if isinstance(row, dict) and "from" in row and "to" in row:
        return [str(row["from"]), str(row["to"])]
    raise EditorError(f"Cannot determine route for YAML wire row: {row!r}")


def _row_uses_route(row: Any) -> bool:
    return isinstance(row, dict) and "route" in row


def _metadata_from_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    return _metadata(net=row.get("net"), awg=row.get("awg"))


def _metadata(net: Any = None, awg: Any = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if net not in (None, ""):
        metadata["net"] = str(net)
    if awg not in (None, ""):
        metadata["awg"] = int(awg)
    return metadata


def _delete_segment(route: list[str], segment_index: int) -> list[list[str]]:
    if len(route) <= 2:
        return []

    left = route[: segment_index + 1]
    right = route[segment_index + 1 :]
    return [segment for segment in (left, right) if len(segment) >= 2]


def _routed_wire(path: str | Path, wire_index: int):
    return _routed_wire_from_router(_router(path), wire_index)


def _router(path: str | Path) -> WireRouter:
    parsed = parse_panel_yaml(Path(path).read_text(encoding="utf-8"))
    return WireRouter.route_parse_result(parsed)


def _routed_wire_from_router(router: WireRouter, wire_index: int):
    try:
        return next(wire for wire in router.routed_wires if wire.index == wire_index)
    except StopIteration as error:
        raise EditorError(f"Unknown routed wire index: {wire_index}") from error


def _editor_document(path: Path) -> str:
    asset_version = sha1((_viewer_css() + _viewer_js() + _editor_css() + _editor_js()).encode("utf-8")).hexdigest()[:12]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PanelViz Editor</title>
  <link rel="stylesheet" href="/viewer.css?v={asset_version}">
  <script src="https://cdn.jsdelivr.net/npm/@svgdotjs/svg.js@3.2.4/dist/svg.min.js"></script>
</head>
<body>
{_editor_html(path, asset_version)}
</body>
</html>
"""


def _editor_html(path: Path, asset_version: str = "") -> str:
    version_suffix = f"?v={asset_version}" if asset_version else ""
    return f"""
<main class="app-shell editor-shell">
  <header class="toolbar">
    <div>
      <h1>PanelViz Editor</h1>
      <p id="status">Loading panel...</p>
      <p class="editor-path">{path}</p>
    </div>
    <div class="editor-route-panel">
      <div id="editor-route">Click a terminal to start a route.</div>
      <label>Net <input id="editor-net" type="text" placeholder="optional"></label>
      <label>AWG <input id="editor-awg" type="number" min="1" placeholder="default"></label>
      <button id="editor-save-route" type="button">Save Route</button>
      <button id="editor-cancel-route" type="button">Cancel</button>
    </div>
    <div class="help-strip">
      <span>Click terminal: start/finish</span>
      <span>Shift-click: add hop</span>
      <span>Click label + Delete: remove wire</span>
      <span>Drag dot to terminal: relocate</span>
      <span>Drag canvas: pan</span>
      <span>Shift-drag canvas: select components</span>
      <span>Wheel: zoom</span>
    </div>
    <div class="diagnostic-actions" role="group" aria-label="Diagnostic highlighting">
      <button id="show-unconnected" type="button">Unconnected</button>
      <button id="show-multiconnected" type="button">Multi-connected</button>
      <button id="show-isolated" type="button">No Connections</button>
    </div>
    <div class="controls" role="group" aria-label="Highlight mode">
      <label><input type="radio" name="highlight-mode" value="wire" checked> Wire</label>
      <label><input type="radio" name="highlight-mode" value="net"> Net</label>
      <a class="toolbar-link" href="/wire-list.csv" download>Download CSV</a>
      <button id="editor-download-pdfs" class="toolbar-link" type="button">Download PDFs</button>
      <button id="toggle-reference-grid" type="button" aria-pressed="false">Ref Grid</button>
      <button id="toggle-wire-table" type="button">Hide Wires</button>
      <button id="clear-selection" type="button">Clear</button>
    </div>
  </header>
  <section class="workspace">
    <section id="canvas-host" aria-label="Interactive PanelViz wiring editor"></section>
    <div id="wire-table-resizer" aria-hidden="true"></div>
    <aside class="wire-table-panel" aria-label="Wire list">
      <div class="wire-table-header">
        <h2>Wire List</h2>
        <div class="wire-table-actions">
          <button id="toggle-wire-columns" type="button">Split Columns</button>
        </div>
      </div>
      <div class="wire-table-scroll">
        <table class="wire-table">
          <thead id="wire-table-head"></thead>
          <tbody id="wire-table-body"></tbody>
        </table>
      </div>
    </aside>
  </section>
</main>
<script src="/viewer.js{version_suffix}"></script>
<script src="/editor.js{version_suffix}"></script>
"""


def _editor_css() -> str:
    return """
.editor-route-panel {
  min-width: 360px;
  display: grid;
  grid-template-columns: 1fr auto auto auto auto;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.editor-route-panel input {
  width: 86px;
  border: 1px solid #94a3b8;
  border-radius: 4px;
  padding: 4px 6px;
}
.toolbar-link {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  border: 1px solid #94a3b8;
  border-radius: 4px;
  padding: 0 9px;
  background: #ffffff;
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
}
.toolbar-link:hover {
  background: #f8fafc;
  border-color: #64748b;
}
#editor-route {
  min-width: 240px;
  max-width: 520px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #334155;
}
.editor-path {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pin-box.editor-route-selected {
  stroke: #0f172a;
  stroke-width: 2.2;
  fill: #dbeafe;
}
.wire-dot {
  cursor: grab;
}
.wire-dot.relocating {
  cursor: grabbing;
}
body.editor-relocating-wire .wire-endpoint-group {
  pointer-events: none;
}
.editor-error-toast {
  position: fixed;
  left: 50%;
  top: 72px;
  z-index: 20;
  max-width: min(720px, calc(100vw - 32px));
  transform: translateX(-50%);
  border: 1px solid #fecaca;
  border-radius: 6px;
  background: #fef2f2;
  color: #991b1b;
  box-shadow: 0 12px 30px rgb(15 23 42 / 0.18);
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 700;
}
"""


def _editor_js() -> str:
    return r"""
const editorState = {
  route: [],
  relocating: null,
};

const editorRouteEl = document.getElementById('editor-route');
const editorNetEl = document.getElementById('editor-net');
const editorAwgEl = document.getElementById('editor-awg');
const editorSaveEl = document.getElementById('editor-save-route');
const editorCancelEl = document.getElementById('editor-cancel-route');
const editorPdfEl = document.getElementById('editor-download-pdfs');

editorSaveEl.addEventListener('click', () => saveEditorRoute());
editorSaveEl.addEventListener('pointerdown', (event) => {
  event.stopPropagation();
});
editorCancelEl.addEventListener('click', () => clearEditorRoute());
editorCancelEl.addEventListener('pointerdown', (event) => {
  event.preventDefault();
  event.stopPropagation();
  clearEditorRoute();
});
editorPdfEl.addEventListener('click', () => downloadDrawingPdfs());
editorPdfEl.addEventListener('pointerdown', (event) => {
  event.stopPropagation();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    if (editorState.route.length) clearEditorRoute();
    return;
  }
  if (event.key === 'Delete' && state.selectedWire) {
    event.preventDefault();
    deleteSelectedWire();
  }
});

document.addEventListener('panelviz:component-layout', (event) => {
  saveComponentLayout(event.detail);
});

document.addEventListener('pointerup', (event) => {
  if (!editorState.relocating) return;
  const target = endpointFromPoint(event.clientX, event.clientY);
  const relocating = editorState.relocating;
  editorState.relocating = null;
  document.body.classList.remove('editor-relocating-wire');
  document.querySelectorAll('.wire-dot.relocating').forEach((dot) => dot.classList.remove('relocating'));
  if (!target || target === relocating.node) return;
  apiPost('/api/relocate-wire', {
    wire_index: Number(relocating.wire),
    endpoint_node: relocating.node,
    new_endpoint: target,
  });
});

const editorObserver = new MutationObserver(() => bindEditorTargets());
editorObserver.observe(document.getElementById('canvas-host'), { childList: true, subtree: true });
setInterval(bindEditorTargets, 500);

function bindEditorTargets() {
  document.querySelectorAll('.pin-box:not([data-editor-bound])').forEach((pin) => {
    pin.dataset.editorBound = 'true';
    pin.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      event.stopPropagation();
      handleEndpointClick(pin.dataset.node, event.shiftKey);
    }, true);
  });
  document.querySelectorAll('.wire-dot:not([data-editor-bound])').forEach((dot) => {
    dot.dataset.editorBound = 'true';
    dot.addEventListener('pointerdown', (event) => {
      const group = dot.closest('.wire-endpoint-group');
      if (!group) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      editorState.relocating = {
        wire: group.dataset.wire,
        node: group.dataset.node,
      };
      document.body.classList.add('editor-relocating-wire');
      dot.classList.add('relocating');
    });
  });
}

function endpointFromElement(element) {
  const target = element && element.closest('.pin-box');
  if (!target) return null;
  return target.dataset.node || null;
}

function endpointFromPoint(x, y) {
  const elements = document.elementsFromPoint(x, y);
  for (const element of elements) {
    const endpoint = endpointFromElement(element);
    if (endpoint) return endpoint;
  }
  return null;
}

function handleEndpointClick(endpoint, shiftKey) {
  if (!endpoint) return;
  if (!editorState.route.length) {
    editorState.route = [endpoint];
    renderEditorRoute();
    return;
  }
  editorState.route.push(endpoint);
  renderEditorRoute();
  if (!shiftKey) saveEditorRoute();
}

function renderEditorRoute() {
  editorRouteEl.textContent = editorState.route.length
    ? editorState.route.join(' -> ')
    : 'Click a terminal to start a route.';
  document.querySelectorAll('.editor-route-selected').forEach((el) => el.classList.remove('editor-route-selected'));
  editorState.route.forEach((endpoint) => {
    document.querySelectorAll(`[data-node="${cssEscape(endpoint)}"],[data-endpoint="${cssEscape(endpoint)}"]`).forEach((el) => {
      el.classList.add('editor-route-selected');
    });
  });
}

function clearEditorRoute() {
  editorState.route = [];
  renderEditorRoute();
}

function saveEditorRoute() {
  if (editorState.route.length < 2) return;
  apiPost('/api/append-route', {
    route: editorState.route,
    net: editorNetEl.value,
    awg: editorAwgEl.value,
  });
}

function deleteSelectedWire() {
  apiPost('/api/delete-wire', {
    wire_index: Number(state.selectedWire),
  });
}

function saveComponentLayout(detail) {
  if (!detail || !detail.component) return;
  apiPost('/api/save-layout', detail, { refresh: false, quiet: true });
}

function apiPost(url, payload, options = {}) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(async (response) => {
      if (!response.ok) {
        const text = await response.text();
        let message = text || response.statusText;
        try {
          message = JSON.parse(text).error || message;
        } catch {
          // Keep the raw response text when the server did not return JSON.
        }
        throw new Error(message);
      }
      if (options.refresh === false) return;
      clearEditorRoute();
      reloadPanelData();
    })
    .catch((error) => {
      if (options.quiet) return;
      showEditorError(error.message);
    });
}

function reloadPanelData() {
  fetch('panel-data.json')
    .then((response) => response.json().then((data) => {
      if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
      return data;
    }))
    .then((data) => {
      if (window.PanelVizRefreshData) {
        window.PanelVizRefreshData(data, { preserveViewBox: true });
      } else if (window.PanelVizRender) {
        window.PanelVizRender(data, { preserveViewBox: true });
      } else {
        window.location.reload();
      }
    })
    .catch((error) => {
      showEditorError(error.message);
    });
}

async function downloadDrawingPdfs() {
  try {
    editorPdfEl.disabled = true;
    const originalLabel = editorPdfEl.textContent;
    editorPdfEl.textContent = 'Preparing PDFs...';
    editorRouteEl.textContent = 'Preparing drawing snapshot...';
    const snapshot = await schematicSnapshot();
    const response = await fetch('/api/drawing-pdfs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshot),
    });
    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || response.statusText);
    }
    const blob = await response.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = pdfBundleFilename(response) || 'panelviz_drawing_pdfs.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
    editorRouteEl.textContent = 'PDF bundle generated.';
    editorPdfEl.textContent = originalLabel;
  } catch (error) {
    showEditorError(error.message);
  } finally {
    editorPdfEl.disabled = false;
    if (editorPdfEl.textContent === 'Preparing PDFs...') {
      editorPdfEl.textContent = 'Download PDFs';
    }
  }
}

async function schematicSnapshot() {
  const svg = document.querySelector('#canvas-host svg');
  if (!svg) throw new Error('No schematic SVG is available to export');
  const bounds = svgSceneBounds(svg);
  const css = await fetch('/viewer.css').then((response) => response.text());
  const clone = svg.cloneNode(true);
  clone.setAttribute('xmlns', NS);
  clone.setAttribute('viewBox', `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`);
  clone.setAttribute('width', bounds.width);
  clone.setAttribute('height', bounds.height);
  clone.style.width = `${bounds.width}px`;
  clone.style.height = `${bounds.height}px`;
  clone.querySelectorAll('.selection-marquee').forEach((node) => node.remove());
  const style = document.createElementNS(NS, 'style');
  style.textContent = `${css}\nsvg{background:#eef2f7}`;
  clone.insertBefore(style, clone.firstChild);
  const svgText = new XMLSerializer().serializeToString(clone);
  const raster = await rasterizeSvg(svgText, bounds.width, bounds.height);
  return {
    image: raster.image,
    width: raster.width,
    height: raster.height,
    source_bounds: bounds,
  };
}

function svgSceneBounds(svg) {
  const items = [...svg.querySelectorAll('.component,.wire-endpoint-group,.no-connect-marker,.no-connect-stub,.no-connect-dot')];
  if (!items.length) {
    const viewBox = svg.viewBox.baseVal;
    return { x: viewBox.x, y: viewBox.y, width: viewBox.width, height: viewBox.height };
  }
  const inverse = svg.getScreenCTM().inverse();
  const points = [];
  items.forEach((item) => {
    const rect = item.getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    [
      [rect.left, rect.top],
      [rect.right, rect.top],
      [rect.right, rect.bottom],
      [rect.left, rect.bottom],
    ].forEach(([x, y]) => {
      const point = svg.createSVGPoint();
      point.x = x;
      point.y = y;
      const local = point.matrixTransform(inverse);
      points.push(local);
    });
  });
  if (!points.length) {
    const viewBox = svg.viewBox.baseVal;
    return { x: viewBox.x, y: viewBox.y, width: viewBox.width, height: viewBox.height };
  }
  const minX = Math.min(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxX = Math.max(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y));
  const padding = 48;
  return {
    x: minX - padding,
    y: minY - padding,
    width: Math.max(1, maxX - minX + padding * 2),
    height: Math.max(1, maxY - minY + padding * 2),
  };
}

function rasterizeSvg(svgText, width, height) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const svgBlob = new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);
    image.onload = () => {
      try {
        const maxPixels = 30000000;
        const maxDimension = 9000;
        const scale = Math.min(
          2,
          maxDimension / Math.max(width, height),
          Math.sqrt(maxPixels / Math.max(width * height, 1)),
        );
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.ceil(width * scale));
        canvas.height = Math.max(1, Math.ceil(height * scale));
        const context = canvas.getContext('2d');
        context.fillStyle = '#eef2f7';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        resolve({
          image: canvas.toDataURL('image/png'),
          width: canvas.width,
          height: canvas.height,
        });
      } catch (error) {
        URL.revokeObjectURL(url);
        reject(error);
      }
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Could not render schematic SVG for PDF export'));
    };
    image.src = url;
  });
}

function pdfBundleFilename(response) {
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/i);
  return match ? match[1] : null;
}

function showEditorError(message) {
  const previous = document.querySelector('.editor-error-toast');
  if (previous) previous.remove();
  const toast = document.createElement('div');
  toast.className = 'editor-error-toast';
  toast.textContent = `Edit failed: ${message}`;
  document.body.appendChild(toast);
  editorRouteEl.textContent = `Edit failed: ${message}`;
  window.setTimeout(() => toast.remove(), 7000);
}
"""
