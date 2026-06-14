"""NiceGUI-based YAML wire editor for PanelViz."""

from __future__ import annotations

import base64
import csv
import html
import re
import secrets
import socket
import zipfile
from dataclasses import dataclass
from hashlib import sha1
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse, JSONResponse, Response
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from panelviz.label_assignment import (
    apply_label_assignment,
    assign_labels,
    component_label_rows,
    labels_path_for_panel,
    load_label_assignment,
    save_label_assignment,
)
from panelviz.parser import parse_panel_yaml
from panelviz.pdf_export import DrawingMeta, diagram_reference_grid, export_schematic_pdf, export_wire_list_pdf
from panelviz.references import attach_wire_references
from panelviz.reports import WIRE_LIST_COLUMNS, wire_list_rows
from panelviz.routing import WireRouter
from panelviz.viewer import _viewer_css, _viewer_js, update_scene_bounds, update_transformed_endpoint_geometry, viewer_data
from panelviz.visualization import component_visual_config_from_visualization
from panelviz.wire_labels import (
    all_wire_labels,
    paginate_wire_labels,
    render_component_label_sheet_pdf,
    render_wire_label_pages_pdf,
    render_wire_label_pdf,
    wire_label_groups,
)


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
        raise RuntimeError("NiceGUI is required for the PanelViz web app. Run: pip install -e \".[dev]\"") from error

    selected_port = _select_editor_port(port)
    session = EditorSession(Path(input_file).resolve())
    cache_bust = secrets.token_urlsafe(12)

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

    @app.get("/docs/getting-started")
    def getting_started_endpoint() -> HTMLResponse:
        return HTMLResponse(
            _markdown_doc_html("Getting Started", _doc_path("getting_started.md").read_text(encoding="utf-8")),
            headers=_no_store_headers(),
        )

    @app.get("/docs/reference")
    def reference_endpoint() -> HTMLResponse:
        return HTMLResponse(
            _markdown_doc_html("YAML Reference", _doc_path("reference.md").read_text(encoding="utf-8")),
            headers=_no_store_headers(),
        )

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

    @app.post("/api/assign-labels", response_model=None)
    async def assign_labels_endpoint(payload: dict[str, Any]) -> Response:
        try:
            order = [str(component) for component in payload.get("component_order", [])]
            bundle = session.assign_labels(order)
        except Exception as error:
            return Response(str(error), status_code=422, media_type="text/plain", headers=_no_store_headers())
        filename = f"{session.path.stem}_component_label_sheets.zip"
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
        return HTMLResponse(_editor_document(session.path, cache_bust), headers=_no_store_headers())

    url = f"http://127.0.0.1:{selected_port}/"
    if selected_port != port:
        print(f"Port {port} is already in use; using {selected_port} instead.")
    print(f"Serving PanelViz editor at {url}")
    ui.run(host="127.0.0.1", port=selected_port, reload=False, show=open_browser, title="PanelViz Editor")


def _select_editor_port(preferred_port: int, attempts: int = 50) -> int:
    """Return the preferred editor port or the next free localhost port."""

    for port in range(preferred_port, preferred_port + attempts):
        if _localhost_port_is_free(port):
            return port
    raise EditorError(f"No free localhost port found from {preferred_port} through {preferred_port + attempts - 1}")


def _localhost_port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@dataclass
class EditorSession:
    """Mutable editor session bound to one YAML file."""

    path: Path

    def panel_data(self) -> dict[str, Any]:
        parsed = parse_panel_yaml(self.path.read_text(encoding="utf-8"))
        router = WireRouter.route_parse_result(parsed)
        self._apply_labels(router)
        visual_config = component_visual_config_from_visualization(parsed.config.visualization)
        data = viewer_data(router, units=parsed.config.units, columns=3, config=visual_config)
        data["labels"] = {"assigned": labels_path_for_panel(self.path).exists(), "path": str(labels_path_for_panel(self.path))}
        self._apply_layout(data)
        update_transformed_endpoint_geometry(data)
        update_scene_bounds(data)
        data["reference_grid"] = diagram_reference_grid(data)
        attach_wire_references(data)
        return data

    def wire_list_csv(self) -> str:
        router = _router(self.path)
        self._apply_labels(router)
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=WIRE_LIST_COLUMNS)
        writer.writeheader()
        writer.writerows(row.model_dump() for row in wire_list_rows(router))
        return output.getvalue()

    def drawing_pdf_bundle(self, snapshot: dict[str, Any] | None = None) -> bytes:
        parsed = parse_panel_yaml(self.path.read_text(encoding="utf-8"))
        router = WireRouter.route_parse_result(parsed)
        self._apply_labels(router)
        visual_config = component_visual_config_from_visualization(parsed.config.visualization)
        data = viewer_data(router, units=parsed.config.units, columns=3, config=visual_config)
        self._apply_layout(data)
        update_transformed_endpoint_geometry(data)
        update_scene_bounds(data)
        data["reference_grid"] = diagram_reference_grid(data)
        attach_wire_references(data)
        meta = DrawingMeta.from_config(parsed.config.drawing, self.path.name)
        image_bytes, image_width, image_height, source_bounds, snapshot_refs = _snapshot_export_args(snapshot)
        schematic = export_schematic_pdf(
            router,
            data,
            meta,
            image_bytes=image_bytes,
            image_width=image_width,
            image_height=image_height,
            source_bounds=source_bounds,
        )
        wire_list_pdf = export_wire_list_pdf(router, snapshot_refs or schematic.diagram_refs, meta)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{self.path.stem}_schematic.pdf", schematic.content)
            archive.writestr(f"{self.path.stem}_wire_list.pdf", wire_list_pdf)
            labels = all_wire_labels(router)
            if labels:
                archive.writestr("all_labels.pdf", render_wire_label_pages_pdf(paginate_wire_labels(labels, parsed.config.labels), parsed.config.labels))
            for tag, labels in sorted(wire_label_groups(router).items()):
                safe_tag = _safe_archive_tag(tag)
                for page_index, cells in enumerate(paginate_wire_labels(labels, parsed.config.labels), start=1):
                    suffix = "" if page_index == 1 else str(page_index)
                    archive.writestr(f"wirelabel_{safe_tag}{suffix}.pdf", render_wire_label_pdf(cells, parsed.config.labels))
            assignment = load_label_assignment(labels_path_for_panel(self.path))
            if assignment is not None:
                component_views = {str(component["name"]): component for component in data.get("components", [])}
                for component_name, rows in component_label_rows(router, assignment).items():
                    if rows:
                        archive.writestr(
                            f"component_labels_{_safe_archive_tag(component_name)}.pdf",
                            render_component_label_sheet_pdf(
                                component_name,
                                rows,
                                parsed.config.labels,
                                component_views.get(component_name),
                            ),
                        )
        return output.getvalue()

    def assign_labels(self, component_order: list[str]) -> bytes:
        parsed = parse_panel_yaml(self.path.read_text(encoding="utf-8"))
        router = WireRouter.route_parse_result(parsed)
        assignment = assign_labels(router, component_order, parsed.config.wire_label_format)
        save_label_assignment(self.path, assignment)
        apply_label_assignment(router, assignment)
        visual_config = component_visual_config_from_visualization(parsed.config.visualization)
        data = viewer_data(router, units=parsed.config.units, columns=3, config=visual_config)
        self._apply_layout(data)
        update_transformed_endpoint_geometry(data)
        update_scene_bounds(data)
        component_views = {str(component["name"]): component for component in data.get("components", [])}
        rows_by_component = component_label_rows(router, assignment)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for component_name in assignment.component_order:
                rows = rows_by_component.get(component_name, [])
                if not rows:
                    continue
                archive.writestr(
                    f"component_labels_{_safe_archive_tag(component_name)}.pdf",
                    render_component_label_sheet_pdf(
                        component_name,
                        rows,
                        parsed.config.labels,
                        component_views.get(component_name),
                    ),
                )
            labels = all_wire_labels(router)
            if labels:
                archive.writestr("all_labels.pdf", render_wire_label_pages_pdf(paginate_wire_labels(labels, parsed.config.labels), parsed.config.labels))
            for tag, labels in sorted(wire_label_groups(router).items()):
                safe_tag = _safe_archive_tag(tag)
                for page_index, cells in enumerate(paginate_wire_labels(labels, parsed.config.labels), start=1):
                    suffix = "" if page_index == 1 else str(page_index)
                    archive.writestr(f"wirelabel_{safe_tag}{suffix}.pdf", render_wire_label_pdf(cells, parsed.config.labels))
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

    def _apply_labels(self, router: WireRouter) -> None:
        apply_label_assignment(router, load_label_assignment(labels_path_for_panel(self.path)))


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
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _doc_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / name


def _markdown_doc_html(title: str, markdown: str) -> str:
    """Render a small, dependency-free Markdown subset for local docs."""

    body: list[str] = []
    code_lines: list[str] = []
    in_code = False
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            if in_code:
                body.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            close_list()
            continue
        if line.startswith("#"):
            close_list()
            level = min(len(line) - len(line.lstrip("#")), 3)
            text = html.escape(line.lstrip("#").strip())
            body.append(f"<h{level}>{text}</h{level}>")
            continue
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{html.escape(line[2:].strip())}</li>")
            continue
        close_list()
        body.append(f"<p>{html.escape(line)}</p>")
    close_list()
    if in_code:
        body.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")

    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <title>{safe_title}</title>
  <style>
    body {{ margin: 0; background: #f8fafc; color: #0f172a; font-family: "Segoe UI", Arial, Helvetica, sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 28px 56px; }}
    h1 {{ margin-top: 0; font-size: 32px; }}
    h2 {{ margin-top: 32px; border-bottom: 1px solid #cbd5e1; padding-bottom: 6px; }}
    h3 {{ margin-top: 24px; }}
    p, li {{ line-height: 1.55; }}
    code {{ font-family: Consolas, "Courier New", monospace; }}
    pre {{ overflow: auto; padding: 14px; border: 1px solid #cbd5e1; border-radius: 8px; background: #ffffff; }}
    ul {{ padding-left: 22px; }}
  </style>
</head>
<body>
  <main>
    {''.join(body)}
  </main>
</body>
</html>
"""


def _snapshot_export_args(
    snapshot: dict[str, Any] | None,
) -> tuple[bytes | None, float | None, float | None, dict[str, float] | None, dict[int | str, dict[str, str]] | None]:
    if not snapshot:
        return None, None, None, None, None
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
    return image_bytes, width or None, height or None, source_bounds, _snapshot_wire_refs(snapshot.get("wire_refs"))


def _snapshot_wire_refs(raw_refs: Any) -> dict[int | str, dict[str, str]] | None:
    if not isinstance(raw_refs, dict):
        return None
    refs: dict[int | str, dict[str, str]] = {}
    for key, value in raw_refs.items():
        if not isinstance(value, dict):
            continue
        wire_refs = {
            "from": str(value.get("from") or ""),
            "to": str(value.get("to") or ""),
        }
        refs[str(key)] = wire_refs
        try:
            refs[int(key)] = wire_refs
        except (TypeError, ValueError):
            pass
    return refs or None


def _safe_archive_tag(tag: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag.strip())
    return safe or "untagged"


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


def _editor_document(path: Path, cache_bust: str | None = None) -> str:
    asset_version = cache_bust or sha1((_viewer_css() + _viewer_js() + _editor_css() + _editor_js()).encode("utf-8")).hexdigest()[:12]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
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
    <div class="toolbar-status">
      <h1>PanelViz Editor</h1>
      <p id="status">Loading panel...</p>
      <p class="editor-path">{path}</p>
    </div>
    <div class="toolbar-group edit-toolbar-group" aria-label="Edit controls">
      <button id="editor-edit-toggle" class="toolbar-button primary-action" type="button" aria-pressed="false">Enable Edit</button>
      <div class="editor-route-panel" aria-hidden="true">
        <div id="editor-route">Editing locked. Enable Edit to change wiring or layout.</div>
        <label>Net <input id="editor-net" type="text" placeholder="optional"></label>
        <label>AWG <input id="editor-awg" type="number" min="1" placeholder="default"></label>
        <button id="editor-save-route" class="toolbar-button" type="button">Save Route</button>
        <button id="editor-cancel-route" class="toolbar-button" type="button">Cancel</button>
      </div>
    </div>
    <div class="toolbar-group mode-toolbar-group" role="radiogroup" aria-label="Highlight mode">
      <span class="toolbar-label">Select</span>
      <label class="segmented-option"><input type="radio" name="highlight-mode" value="wire" checked><span>Wire</span></label>
      <label class="segmented-option"><input type="radio" name="highlight-mode" value="net"><span>Net</span></label>
    </div>
    <div class="toolbar-group diagnostic-actions" role="group" aria-label="Diagnostic highlighting">
      <span class="toolbar-label">Diagnostics</span>
      <button id="show-unconnected" class="toolbar-button" type="button" aria-pressed="false">Unconnected</button>
      <button id="show-multiconnected" class="toolbar-button" type="button" aria-pressed="false">Multi-connected</button>
      <button id="show-isolated" class="toolbar-button" type="button" aria-pressed="false">No Connections</button>
      <button id="clear-selection" class="toolbar-button clear-button" type="button">Clear</button>
    </div>
    <div class="toolbar-group docs-toolbar-group" role="group" aria-label="Documentation and exports">
      <a class="toolbar-link toolbar-button" href="/wire-list.csv" download>CSV</a>
      <button id="editor-download-pdfs" class="toolbar-button" type="button">PDFs</button>
      <button id="assign-labels-button" class="toolbar-button primary-action" type="button">Assign Labels</button>
      <a class="toolbar-link toolbar-button" href="/docs/getting-started" target="_blank" rel="noopener">Getting Started</a>
      <a class="toolbar-link toolbar-button" href="/docs/reference" target="_blank" rel="noopener">Reference</a>
      <button id="editor-help-button" class="toolbar-button icon-button" type="button" aria-haspopup="dialog" aria-expanded="false" title="Help">?</button>
      <button id="toggle-reference-grid" class="toolbar-button" type="button" aria-pressed="false">Ref Grid</button>
      <button id="toggle-wire-table" class="toolbar-button wire-panel-toggle" type="button" aria-expanded="true" title="Collapse wire list">Wire List &lt;</button>
    </div>
  </header>
  <dialog id="editor-help-dialog" class="help-dialog">
    <form method="dialog">
      <div class="help-dialog-header">
        <h2>PanelViz Controls</h2>
        <button type="submit" aria-label="Close help">Close</button>
      </div>
      <dl>
        <dt>View</dt><dd>Drag empty canvas to pan. Use the wheel to zoom around the pointer.</dd>
        <dt>Select</dt><dd>Click wire labels, terminals, or component bodies to highlight related wiring. Right-click empty canvas clears selection.</dd>
        <dt>Diagnostics</dt><dd>Use Unconnected, Multi-connected, and No Connections to highlight wiring warnings.</dd>
        <dt>Edit toggle</dt><dd>Editing starts locked. Enable Edit before moving components, rotating components, creating routes, deleting wires, or relocating wire endpoints.</dd>
        <dt>Routing</dt><dd>With Edit enabled, click terminals to start and finish a route. Shift-click adds intermediate hops. Enter optional Net/AWG before saving.</dd>
        <dt>Wire edits</dt><dd>With Edit enabled, click a wire label and press Delete to remove it, or drag an endpoint dot onto another terminal to relocate it.</dd>
        <dt>Layout edits</dt><dd>With Edit enabled, drag component bodies to move them. Right-click a component to rotate it 90 degrees. Shift-drag empty canvas to select a group.</dd>
      </dl>
    </form>
  </dialog>
  <dialog id="assign-labels-dialog" class="assign-labels-dialog">
    <form method="dialog">
      <div class="help-dialog-header">
        <h2>Assign Labels</h2>
        <button type="submit" aria-label="Close assign labels">Close</button>
      </div>
      <p class="assign-labels-note">Order components in the sequence you want final wire numbers assigned. Label sheets for every connected component will download as a ZIP.</p>
      <select id="assign-labels-list" size="16" aria-label="Component label assignment order"></select>
      <div class="assign-labels-actions">
        <button id="assign-labels-up" class="toolbar-button" type="button">Up</button>
        <button id="assign-labels-down" class="toolbar-button" type="button">Down</button>
        <button id="assign-labels-layout" class="toolbar-button" type="button">Sort By Layout</button>
        <button id="assign-labels-submit" class="toolbar-button primary-action" type="button">Generate Sheets</button>
      </div>
    </form>
  </dialog>
  <section class="workspace">
    <section id="canvas-host" aria-label="Interactive PanelViz wiring editor"></section>
    <div id="wire-table-resizer" aria-hidden="true"></div>
    <aside class="wire-table-panel" aria-label="Wire list">
      <div class="wire-table-header">
        <h2>Wire List <span id="wire-table-count" class="wire-table-count">0 wires</span></h2>
        <div class="wire-table-actions">
          <label class="wire-tag-filter">Tag <input id="wire-tag-filter" type="search" list="wire-tag-options" placeholder="all"></label>
          <datalist id="wire-tag-options"></datalist>
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
.editor-shell .toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1.2fr) minmax(320px, 1.8fr) auto auto minmax(420px, 1.6fr);
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
}
.toolbar-status {
  min-width: 0;
}
.toolbar-group {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px;
  border: 1px solid #dbe3ee;
  border-radius: 8px;
  background: #f8fafc;
  white-space: nowrap;
}
.toolbar-label {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}
.toolbar-button,
.toolbar-link {
  box-sizing: border-box;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #94a3b8;
  border-radius: 6px;
  padding: 0 10px;
  background: #ffffff;
  color: #0f172a;
  font: 700 12px/1.1 "Segoe UI", Arial, Helvetica, sans-serif;
  text-decoration: none;
  cursor: pointer;
}
.toolbar-button:hover,
.toolbar-link:hover {
  background: #eff6ff;
  border-color: #64748b;
}
.primary-action {
  min-width: 92px;
}
.icon-button {
  width: 30px;
  padding: 0;
  border-radius: 999px;
  font-weight: 900;
}
.clear-button {
  margin-left: 4px;
}
.diagnostic-actions .toolbar-button[aria-pressed="true"],
.mode-toolbar-group input:checked + span {
  background: #dbeafe;
  border-color: #2563eb;
  color: #1d4ed8;
}
.mode-toolbar-group {
  gap: 0;
}
.mode-toolbar-group .toolbar-label {
  margin-right: 6px;
}
.segmented-option {
  display: inline-flex;
  align-items: center;
  margin: 0;
}
.segmented-option input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.segmented-option span {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  border: 1px solid #94a3b8;
  border-left-width: 0;
  padding: 0 10px;
  background: #ffffff;
  color: #0f172a;
  font-size: 12px;
  font-weight: 800;
}
.segmented-option:first-of-type span {
  border-left-width: 1px;
  border-radius: 6px 0 0 6px;
}
.segmented-option:last-of-type span {
  border-radius: 0 6px 6px 0;
}
.editor-route-panel {
  min-width: 360px;
  display: grid;
  grid-template-columns: 1fr auto auto auto auto;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.editor-route-panel[aria-hidden="true"] {
  display: none;
}
.editor-route-panel input {
  width: 86px;
  border: 1px solid #94a3b8;
  border-radius: 4px;
  padding: 4px 6px;
}
.editor-route-panel[aria-disabled="true"] {
  opacity: 0.58;
}
.editor-route-panel[aria-disabled="true"] input,
.editor-route-panel[aria-disabled="true"] button {
  pointer-events: none;
}
#editor-edit-toggle[aria-pressed="true"] {
  background: #dbeafe;
  border-color: #2563eb;
  color: #1d4ed8;
}
.help-dialog {
  width: min(720px, calc(100vw - 48px));
  border: 1px solid #94a3b8;
  border-radius: 8px;
  color: #0f172a;
  box-shadow: 0 24px 70px rgb(15 23 42 / 0.28);
}
.assign-labels-dialog {
  width: min(620px, calc(100vw - 48px));
  border: 1px solid #94a3b8;
  border-radius: 8px;
  color: #0f172a;
  box-shadow: 0 24px 70px rgb(15 23 42 / 0.28);
}
.assign-labels-dialog::backdrop {
  background: rgb(15 23 42 / 0.36);
}
.assign-labels-dialog form {
  margin: 0;
}
.assign-labels-note {
  margin: 0 0 12px;
  color: #475569;
  line-height: 1.35;
}
#assign-labels-list {
  width: 100%;
  min-height: 320px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 6px;
  font: 13px/1.35 Consolas, "Courier New", monospace;
}
.assign-labels-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.help-dialog::backdrop {
  background: rgb(15 23 42 / 0.36);
}
.help-dialog form {
  margin: 0;
}
.help-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 10px;
  margin-bottom: 12px;
}
.help-dialog h2 {
  margin: 0;
  font-size: 18px;
}
.help-dialog dl {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 10px 16px;
  margin: 0;
}
.help-dialog dt {
  font-weight: 800;
}
.help-dialog dd {
  margin: 0;
  color: #334155;
  line-height: 1.35;
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
@media (max-width: 1500px) {
  .editor-shell .toolbar {
    grid-template-columns: minmax(220px, 1fr) minmax(300px, 1.4fr) auto;
  }
  .docs-toolbar-group {
    grid-column: 1 / -1;
  }
}
@media (max-width: 980px) {
  .editor-shell .toolbar {
    grid-template-columns: 1fr;
    align-items: stretch;
  }
  .toolbar-group,
  .editor-route-panel {
    flex-wrap: wrap;
    white-space: normal;
  }
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
  editEnabled: false,
  route: [],
  relocating: null,
};

const editorRouteEl = document.getElementById('editor-route');
const editorNetEl = document.getElementById('editor-net');
const editorAwgEl = document.getElementById('editor-awg');
const editorSaveEl = document.getElementById('editor-save-route');
const editorCancelEl = document.getElementById('editor-cancel-route');
const editorPdfEl = document.getElementById('editor-download-pdfs');
const editorEditToggleEl = document.getElementById('editor-edit-toggle');
const editorHelpButtonEl = document.getElementById('editor-help-button');
const editorHelpDialogEl = document.getElementById('editor-help-dialog');
const editorRoutePanelEl = document.querySelector('.editor-route-panel');
const assignLabelsButtonEl = document.getElementById('assign-labels-button');
const assignLabelsDialogEl = document.getElementById('assign-labels-dialog');
const assignLabelsListEl = document.getElementById('assign-labels-list');
const assignLabelsUpEl = document.getElementById('assign-labels-up');
const assignLabelsDownEl = document.getElementById('assign-labels-down');
const assignLabelsLayoutEl = document.getElementById('assign-labels-layout');
const assignLabelsSubmitEl = document.getElementById('assign-labels-submit');

window.PanelVizCanEdit = () => editorState.editEnabled;

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
editorEditToggleEl.addEventListener('click', () => {
  setEditEnabled(!editorState.editEnabled);
});
editorEditToggleEl.addEventListener('pointerdown', (event) => {
  event.stopPropagation();
});
editorHelpButtonEl.addEventListener('click', () => {
  if (editorHelpDialogEl?.showModal) {
    editorHelpDialogEl.showModal();
  }
  editorHelpButtonEl.setAttribute('aria-expanded', 'true');
});
editorHelpButtonEl.addEventListener('pointerdown', (event) => {
  event.stopPropagation();
});
editorHelpDialogEl?.addEventListener('close', () => {
  editorHelpButtonEl.setAttribute('aria-expanded', 'false');
});
assignLabelsButtonEl.addEventListener('click', () => openAssignLabelsDialog());
assignLabelsButtonEl.addEventListener('pointerdown', (event) => {
  event.stopPropagation();
});
assignLabelsUpEl.addEventListener('click', () => moveSelectedAssignLabelComponent(-1));
assignLabelsDownEl.addEventListener('click', () => moveSelectedAssignLabelComponent(1));
assignLabelsLayoutEl.addEventListener('click', () => populateAssignLabelsList(layoutSortedComponents()));
assignLabelsSubmitEl.addEventListener('click', () => submitAssignLabels());
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    if (editorState.route.length) clearEditorRoute();
    return;
  }
  if (event.key === 'Delete' && state.selectedWire && editorState.editEnabled) {
    event.preventDefault();
    deleteSelectedWire();
  }
});

document.addEventListener('panelviz:component-layout', (event) => {
  if (!editorState.editEnabled) return;
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
  if (!editorState.editEnabled) return;
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
      if (!editorState.editEnabled) return;
      event.preventDefault();
      event.stopPropagation();
      handleEndpointClick(pin.dataset.node, event.shiftKey);
    }, true);
  });
  document.querySelectorAll('.wire-dot:not([data-editor-bound])').forEach((dot) => {
    dot.dataset.editorBound = 'true';
    dot.addEventListener('pointerdown', (event) => {
      if (!editorState.editEnabled) return;
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
  if (!editorState.editEnabled) return;
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
    : editorState.editEnabled
      ? 'Click a terminal to start a route.'
      : 'Editing locked. Enable Edit to change wiring or layout.';
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
  if (!editorState.editEnabled) return;
  if (editorState.route.length < 2) return;
  apiPost('/api/append-route', {
    route: editorState.route,
    net: editorNetEl.value,
    awg: editorAwgEl.value,
  });
}

function deleteSelectedWire() {
  if (!editorState.editEnabled) return;
  apiPost('/api/delete-wire', {
    wire_index: Number(state.selectedWire),
  });
}

function openAssignLabelsDialog() {
  populateAssignLabelsList(layoutSortedComponents());
  if (assignLabelsDialogEl?.showModal) {
    assignLabelsDialogEl.showModal();
  }
}

function layoutSortedComponents() {
  const components = state?.data?.components || [];
  return [...components]
    .sort((left, right) => (left.y - right.y) || (left.x - right.x) || left.name.localeCompare(right.name))
    .map((component) => component.name);
}

function populateAssignLabelsList(componentNames) {
  assignLabelsListEl.replaceChildren();
  componentNames.forEach((componentName) => {
    const option = document.createElement('option');
    option.value = componentName;
    option.textContent = componentName;
    assignLabelsListEl.appendChild(option);
  });
}

function moveSelectedAssignLabelComponent(direction) {
  const index = assignLabelsListEl.selectedIndex;
  if (index < 0) return;
  const targetIndex = index + direction;
  if (targetIndex < 0 || targetIndex >= assignLabelsListEl.options.length) return;
  const option = assignLabelsListEl.options[index];
  const reference = direction < 0 ? assignLabelsListEl.options[targetIndex] : assignLabelsListEl.options[targetIndex].nextSibling;
  assignLabelsListEl.insertBefore(option, reference);
  assignLabelsListEl.selectedIndex = targetIndex;
}

async function submitAssignLabels() {
  const componentOrder = [...assignLabelsListEl.options].map((option) => option.value);
  try {
    assignLabelsSubmitEl.disabled = true;
    assignLabelsSubmitEl.textContent = 'Generating...';
    const response = await fetch('/api/assign-labels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ component_order: componentOrder }),
    });
    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || response.statusText);
    }
    await downloadResponseBlob(response, 'component_label_sheets.zip');
    assignLabelsDialogEl.close();
    reloadPanelData();
  } catch (error) {
    showEditorError(error.message);
  } finally {
    assignLabelsSubmitEl.disabled = false;
    assignLabelsSubmitEl.textContent = 'Generate Sheets';
  }
}

function saveComponentLayout(detail) {
  if (!editorState.editEnabled) return;
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

function setEditEnabled(enabled) {
  editorState.editEnabled = Boolean(enabled);
  editorEditToggleEl.setAttribute('aria-pressed', String(editorState.editEnabled));
  editorEditToggleEl.textContent = editorState.editEnabled ? 'Edit On' : 'Enable Edit';
  editorRoutePanelEl?.setAttribute('aria-disabled', String(!editorState.editEnabled));
  editorRoutePanelEl?.setAttribute('aria-hidden', String(!editorState.editEnabled));
  [editorNetEl, editorAwgEl, editorSaveEl, editorCancelEl].forEach((control) => {
    control.disabled = !editorState.editEnabled;
  });
  if (!editorState.editEnabled) {
    editorState.relocating = null;
    document.body.classList.remove('editor-relocating-wire');
    document.querySelectorAll('.wire-dot.relocating').forEach((dot) => dot.classList.remove('relocating'));
    clearEditorRoute();
  } else {
    renderEditorRoute();
  }
}

function reloadPanelData() {
  fetch('panel-data.json', { cache: 'no-store' })
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
    await downloadResponseBlob(response, 'panelviz_drawing_pdfs.zip');
    editorRouteEl.textContent = 'PDF bundle generated.';
    editorPdfEl.textContent = originalLabel;
  } catch (error) {
    showEditorError(error.message);
  } finally {
    editorPdfEl.disabled = false;
    if (editorPdfEl.textContent === 'Preparing PDFs...') {
      editorPdfEl.textContent = 'PDFs';
    }
  }
}

async function schematicSnapshot() {
  const svg = document.querySelector('#canvas-host svg');
  if (!svg) throw new Error('No schematic SVG is available to export');
  const bounds = svgSceneBounds(svg);
  const pdfGrid = referenceGridFromBounds(bounds, {});
  const wireRefs = collectWireReferences(pdfGrid);
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
    wire_refs: wireRefs,
  };
}

function collectWireReferences(grid) {
  const refs = {};
  if (!window.PanelVizRender || !state?.data?.wires) return refs;
  state.data.wires.forEach((wire) => {
    const fromAnchor = renderedEndpointAnchor(wire, wire.endpoints?.[0]);
    const toAnchor = renderedEndpointAnchor(wire, wire.endpoints?.[1]);
    const wireRefs = {
      from: fromAnchor ? referenceForPoint(grid, fromAnchor.x, fromAnchor.y) : '',
      to: toAnchor ? referenceForPoint(grid, toAnchor.x, toAnchor.y) : '',
    };
    refs[String(wire.index)] = wireRefs;
    refs[String(wire.label)] = wireRefs;
  });
  return refs;
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
        const maxPixels = 160000000;
        const maxDimension = 20000;
        const scale = Math.min(
          4,
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

async function downloadResponseBlob(response, fallbackName) {
  const blob = await response.blob();
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  link.download = pdfBundleFilename(response) || fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(downloadUrl);
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

setEditEnabled(false);
"""
