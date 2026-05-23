
"""PDF exports for PanelViz drawings and wire lists."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Any

from fpdf import FPDF

from panelviz.parser import DrawingConfig
from panelviz.reports import wire_list_rows
from panelviz.routing import WireRouter

PT_PER_IN = 72.0
SCHEMATIC_PAGE = (17 * PT_PER_IN, 11 * PT_PER_IN)
LETTER_PORTRAIT = (8.5 * PT_PER_IN, 11 * PT_PER_IN)
FRAME_PAD = 24.0
ZONE_SIZE = 22.0
TITLE_W = 430.0
TITLE_H = 92.0
DRAWING_PAD = 24.0


@dataclass(frozen=True)
class PdfExportResult:
    """A generated PDF and its diagram reference lookup."""

    content: bytes
    diagram_refs: dict[int | str, dict[str, str]]


@dataclass(frozen=True)
class DrawingMeta:
    """Title block metadata."""

    company: str = ""
    author: str = ""
    title: str = "PanelViz Wiring Schematic"
    file_name: str = ""
    printed_date: str = ""
    scale: str = "1:1"

    @classmethod
    def from_config(cls, config: DrawingConfig, file_name: str, printed_date: str | None = None) -> "DrawingMeta":
        return cls(
            company=config.company,
            author=config.author,
            title=config.title,
            file_name=file_name,
            printed_date=printed_date or date.today().isoformat(),
        )


@dataclass(frozen=True)
class SheetGeometry:
    page_w: float
    page_h: float
    frame_x: float
    frame_y: float
    frame_w: float
    frame_h: float
    drawing_x: float
    drawing_y: float
    drawing_w: float
    drawing_h: float
    title_x: float
    title_y: float
    title_w: float
    title_h: float
    scale: float
    source_min_x: float
    source_min_y: float
    columns: int
    rows: int


def export_schematic_pdf(
    router: WireRouter,
    data: dict[str, Any],
    meta: DrawingMeta,
    image_bytes: bytes | None = None,
    image_width: float | None = None,
    image_height: float | None = None,
    source_bounds: dict[str, float] | None = None,
) -> PdfExportResult:
    """Export the routed schematic as a one-page drawing PDF."""

    geometry = _schematic_geometry(data, image_width=image_width, image_height=image_height, source_bounds=source_bounds)
    pdf = FPDF(unit="pt", format=(geometry.page_w, geometry.page_h))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    _draw_drawing_border(pdf, geometry, meta, sheet="1 OF 1")
    if image_bytes:
        _draw_schematic_image(pdf, image_bytes, geometry)
    else:
        _draw_schematic_contents(pdf, data, geometry)
    refs = _diagram_references(data, geometry)
    return PdfExportResult(bytes(pdf.output()), refs)


def export_wire_list_pdf(router: WireRouter, diagram_refs: dict[int | str, dict[str, str]], meta: DrawingMeta) -> bytes:
    """Export a paginated letter portrait wire-list PDF."""

    rows = wire_list_rows(router)
    pdf = FPDF(unit="pt", format=LETTER_PORTRAIT)
    pdf.set_auto_page_break(False)
    page_w, page_h = LETTER_PORTRAIT
    margin = 28.0
    title_h = 52.0
    header_h = 28.0
    row_h = 14.0
    table_top_first = margin + title_h + 48.0
    table_top = margin + title_h + 18.0
    usable_bottom = page_h - margin - 8.0
    rows_first = max(1, int((usable_bottom - table_top_first - header_h) // row_h))
    rows_later = max(1, int((usable_bottom - table_top - header_h) // row_h))
    pages: list[list[Any]] = []
    remaining = rows[:]
    pages.append(remaining[:rows_first])
    remaining = remaining[rows_first:]
    while remaining:
        pages.append(remaining[:rows_later])
        remaining = remaining[rows_later:]
    total_pages = len(pages)

    for index, page_rows in enumerate(pages, start=1):
        pdf.add_page()
        _draw_wire_list_border(pdf, meta, index, total_pages)
        if index == 1:
            _draw_wire_list_summary(pdf, margin, margin + title_h + 16, len(rows), len(router.components))
            top = table_top_first
        else:
            top = table_top
        _draw_wire_list_table(pdf, page_rows, diagram_refs, margin, top, page_w - 2 * margin, row_h)
    return bytes(pdf.output())


def _schematic_geometry(
    data: dict[str, Any],
    image_width: float | None = None,
    image_height: float | None = None,
    source_bounds: dict[str, float] | None = None,
) -> SheetGeometry:
    if source_bounds is None and isinstance(data.get("scene"), dict):
        source_bounds = data["scene"]

    if source_bounds:
        min_x = float(source_bounds.get("x", 0))
        min_y = float(source_bounds.get("y", 0))
        max_x = min_x + max(1.0, float(source_bounds.get("width", 1)))
        max_y = min_y + max(1.0, float(source_bounds.get("height", 1)))
    else:
        min_x, min_y, max_x, max_y = _content_bounds(data)
    source_w = max(1.0, max_x - min_x)
    source_h = max(1.0, max_y - min_y)
    page_w = max(
        SCHEMATIC_PAGE[0],
        source_w + 2 * FRAME_PAD + 2 * ZONE_SIZE + 2 * DRAWING_PAD,
        TITLE_W + 2 * FRAME_PAD + 2 * ZONE_SIZE + 2 * DRAWING_PAD,
    )
    page_h = max(SCHEMATIC_PAGE[1], source_h + TITLE_H + 2 * FRAME_PAD + 2 * ZONE_SIZE + 3 * DRAWING_PAD)
    frame_x = FRAME_PAD
    frame_y = FRAME_PAD
    frame_w = page_w - 2 * FRAME_PAD
    frame_h = page_h - 2 * FRAME_PAD
    title_x = page_w - FRAME_PAD - ZONE_SIZE - TITLE_W
    title_y = page_h - FRAME_PAD - ZONE_SIZE - TITLE_H
    drawing_x = frame_x + ZONE_SIZE + DRAWING_PAD
    drawing_y = frame_y + ZONE_SIZE + DRAWING_PAD
    available_w = frame_w - 2 * ZONE_SIZE - 2 * DRAWING_PAD
    available_h = title_y - drawing_y - DRAWING_PAD
    scale = 1.0
    used_w = min(source_w, available_w)
    used_h = min(source_h, available_h)
    drawing_x += max(0.0, (available_w - used_w) / 2)
    return SheetGeometry(
        page_w=page_w,
        page_h=page_h,
        frame_x=frame_x,
        frame_y=frame_y,
        frame_w=frame_w,
        frame_h=frame_h,
        drawing_x=drawing_x,
        drawing_y=drawing_y,
        drawing_w=used_w,
        drawing_h=used_h,
        title_x=title_x,
        title_y=title_y,
        title_w=TITLE_W,
        title_h=TITLE_H,
        scale=scale,
        source_min_x=min_x,
        source_min_y=min_y,
        columns=max(8, min(80, math.ceil(used_w / 90))),
        rows=max(4, min(26, math.ceil(used_h / 90))),
    )


def _draw_schematic_image(pdf: FPDF, image_bytes: bytes, geo: SheetGeometry) -> None:
    pdf.image(BytesIO(image_bytes), x=geo.drawing_x, y=geo.drawing_y, w=geo.drawing_w, h=geo.drawing_h)


def _content_bounds(data: dict[str, Any]) -> tuple[float, float, float, float]:
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
    for component in data.get("components", []):
        for x, y in _rotated_rect_corners(
            float(component["x"]),
            float(component["y"]),
            float(component["width"]),
            float(component["height"]),
            float(component.get("rotation", 0)),
        ):
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
    for wire in data.get("wires", []):
        for endpoint in wire.get("endpoints", []):
            for point_name in ("anchor", "stub", "label"):
                point = endpoint.get(point_name, {})
                if "x" not in point or "y" not in point:
                    continue
                x = float(point["x"])
                y = float(point["y"])
                pad = max(float(point.get("width", 0)) / 2, float(point.get("height", 0)) / 2, 4)
                min_x, min_y = min(min_x, x - pad), min(min_y, y - pad)
                max_x, max_y = max(max_x, x + pad), max(max_y, y + pad)
    if not math.isfinite(min_x):
        return 0, 0, 1, 1
    return min_x, min_y, max_x, max_y


def _draw_drawing_border(pdf: FPDF, geo: SheetGeometry, meta: DrawingMeta, sheet: str) -> None:
    pdf.set_draw_color(45, 45, 45)
    pdf.set_line_width(1.2)
    pdf.rect(FRAME_PAD / 2, FRAME_PAD / 2, geo.page_w - FRAME_PAD, geo.page_h - FRAME_PAD)
    pdf.set_line_width(0.8)
    pdf.rect(geo.frame_x, geo.frame_y, geo.frame_w, geo.frame_h)
    pdf.rect(geo.frame_x + ZONE_SIZE, geo.frame_y + ZONE_SIZE, geo.frame_w - 2 * ZONE_SIZE, geo.frame_h - 2 * ZONE_SIZE)
    _draw_zones(pdf, geo)
    _draw_title_block(pdf, geo, meta, sheet)


def _draw_zones(pdf: FPDF, geo: SheetGeometry) -> None:
    letters = [chr(ord("A") + i) for i in range(geo.rows)]
    col_w = (geo.frame_w - 2 * ZONE_SIZE) / geo.columns
    row_h = (geo.frame_h - 2 * ZONE_SIZE) / geo.rows
    pdf.set_font("Helvetica", "B", 8)
    for col in range(geo.columns):
        label = str(col + 1)
        x = geo.frame_x + ZONE_SIZE + col * col_w
        pdf.line(x, geo.frame_y, x, geo.frame_y + ZONE_SIZE)
        pdf.line(x, geo.frame_y + geo.frame_h - ZONE_SIZE, x, geo.frame_y + geo.frame_h)
        _center_text(pdf, x + col_w / 2, geo.frame_y + ZONE_SIZE / 2 + 3, label, 8)
        _center_text(pdf, x + col_w / 2, geo.frame_y + geo.frame_h - ZONE_SIZE / 2 + 3, label, 8)
    x = geo.frame_x + geo.frame_w - ZONE_SIZE
    pdf.line(x, geo.frame_y, x, geo.frame_y + ZONE_SIZE)
    pdf.line(x, geo.frame_y + geo.frame_h - ZONE_SIZE, x, geo.frame_y + geo.frame_h)
    for row, label in enumerate(letters):
        y = geo.frame_y + ZONE_SIZE + row * row_h
        pdf.line(geo.frame_x, y, geo.frame_x + ZONE_SIZE, y)
        pdf.line(geo.frame_x + geo.frame_w - ZONE_SIZE, y, geo.frame_x + geo.frame_w, y)
        _center_text(pdf, geo.frame_x + ZONE_SIZE / 2, y + row_h / 2 + 3, label, 8)
        _center_text(pdf, geo.frame_x + geo.frame_w - ZONE_SIZE / 2, y + row_h / 2 + 3, label, 8)
    y = geo.frame_y + geo.frame_h - ZONE_SIZE
    pdf.line(geo.frame_x, y, geo.frame_x + ZONE_SIZE, y)
    pdf.line(geo.frame_x + geo.frame_w - ZONE_SIZE, y, geo.frame_x + geo.frame_w, y)


def _draw_title_block(pdf: FPDF, geo: SheetGeometry, meta: DrawingMeta, sheet: str) -> None:
    x, y, w, h = geo.title_x, geo.title_y, geo.title_w, geo.title_h
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(1.0)
    pdf.rect(x, y, w, h)
    for row_y in (y + 30, y + 58):
        pdf.line(x, row_y, x + w, row_y)
    for col_x in (x + 80, x + 230, x + 320):
        pdf.line(col_x, y + 30, col_x, y + h)
    _label_value(pdf, x + 6, y + 9, "TITLE", meta.title, 6, 13)
    pdf.set_font("Helvetica", "B", 8)
    pdf.text(x + w - 62, y + 20, f"SHT {sheet}")
    _label_value(pdf, x + 6, y + 40, "COMPANY", meta.company or "-", 6, 9)
    _label_value(pdf, x + 86, y + 40, "AUTHOR", meta.author or "-", 6, 9)
    _label_value(pdf, x + 236, y + 40, "DATE", meta.printed_date, 6, 9)
    _label_value(pdf, x + 326, y + 40, "FILE", meta.file_name, 6, 9)
    _label_value(pdf, x + 6, y + 68, "DRAWING", "SCHEMATIC", 6, 9)
    _label_value(pdf, x + 86, y + 68, "SCALE", meta.scale, 6, 9)


def _draw_schematic_contents(pdf: FPDF, data: dict[str, Any], geo: SheetGeometry) -> None:
    _draw_schematic_grid(pdf, geo)
    for component in data.get("components", []):
        _draw_component(pdf, component, data.get("wires", []), geo)


def _draw_schematic_grid(pdf: FPDF, geo: SheetGeometry) -> None:
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.25)
    step = 24 * geo.scale
    if step < 8:
        step = 12
    x = geo.drawing_x
    while x <= geo.drawing_x + geo.drawing_w:
        pdf.line(x, geo.drawing_y, x, geo.drawing_y + geo.drawing_h)
        x += step
    y = geo.drawing_y
    while y <= geo.drawing_y + geo.drawing_h:
        pdf.line(geo.drawing_x, y, geo.drawing_x + geo.drawing_w, y)
        y += step


def _draw_component(pdf: FPDF, component: dict[str, Any], wires: list[dict[str, Any]], geo: SheetGeometry) -> None:
    x, y = _map_point(geo, float(component["x"]), float(component["y"]))
    w = float(component["width"]) * geo.scale
    h = float(component["height"]) * geo.scale
    rotation = float(component.get("rotation", 0))
    cx, cy = x + w / 2, y + h / 2
    with pdf.rotation(rotation, x=cx, y=cy):
        pdf.set_draw_color(31, 41, 55)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_line_width(1.0)
        pdf.rect(x, y, w, h)
        for pin in component.get("pins", []):
            _draw_pin(pdf, x, y, pin, geo.scale)
        pdf.set_font("Helvetica", "B", max(6, min(14, float(component["font"]["name"]) * geo.scale)))
        _center_text(pdf, x + w / 2, y + h / 2 - 3, component["name"], max(6, min(14, float(component["font"]["name"]) * geo.scale)))
        pdf.set_font("Helvetica", "", 5.5)
        _center_text(pdf, x + w / 2, y + h / 2 + 9, component.get("type", ""), 5.5)
        for wire in wires:
            for endpoint in wire.get("endpoints", []):
                if endpoint.get("component") == component.get("name"):
                    _draw_endpoint(pdf, x, y, component, endpoint, wire, geo.scale)


def _draw_pin(pdf: FPDF, component_x: float, component_y: float, pin: dict[str, Any], scale: float) -> None:
    x = component_x + float(pin["x"]) * scale
    y = component_y + float(pin["y"]) * scale
    w = float(pin["width"]) * scale
    h = float(pin["height"]) * scale
    pdf.set_draw_color(148, 163, 184)
    pdf.set_fill_color(248, 250, 252)
    pdf.set_line_width(0.35)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_text_color(15, 23, 42)
    _center_text(pdf, x + w / 2, y + h / 2 + 2, str(pin["pin"]), max(3, min(6, h * 0.45)))
    if pin.get("no_connect"):
        _draw_no_connect(pdf, x, y, pin, scale)


def _draw_no_connect(pdf: FPDF, component_x: float, component_y: float, pin: dict[str, Any], scale: float) -> None:
    anchor = _pin_boundary_local(pin)
    vx, vy = _side_vector(pin["side"])
    ax = component_x + anchor[0] * scale
    ay = component_y + anchor[1] * scale
    end_x = ax + vx * 18 * scale
    end_y = ay + vy * 18 * scale
    pdf.set_draw_color(220, 38, 38)
    pdf.set_line_width(0.9)
    pdf.line(ax, ay, end_x, end_y)
    s = 5
    pdf.line(end_x - s, end_y - s, end_x + s, end_y + s)
    pdf.line(end_x + s, end_y - s, end_x - s, end_y + s)


def _draw_endpoint(pdf: FPDF, component_x: float, component_y: float, component: dict[str, Any], endpoint: dict[str, Any], wire: dict[str, Any], scale: float) -> None:
    pin = next((item for item in component.get("pins", []) if item.get("node") == endpoint.get("node")), None)
    if not pin:
        return
    vx, vy = _side_vector(endpoint["side"])
    slot = int(endpoint.get("label", {}).get("slot", 0))
    slot_count = int(endpoint.get("label", {}).get("slot_count", 1))
    fan_x, fan_y = _fan_offset(endpoint["side"], slot, slot_count, 20.0)
    anchor = _pin_boundary_local(pin)
    ax = component_x + anchor[0] * scale
    ay = component_y + anchor[1] * scale
    sx = ax + (vx * float(endpoint.get("stub_length", 20)) + fan_x) * scale
    sy = ay + (vy * float(endpoint.get("stub_length", 20)) + fan_y) * scale
    label = endpoint.get("label", {})
    label_width = float(label.get("width", 44)) * scale
    label_height = float(label.get("height", 17)) * scale
    gap = float(endpoint.get("label_gap", 6)) * scale
    lx = sx + vx * (gap + label_width / 2)
    ly = sy + vy * (gap + label_width / 2)
    style = wire.get("style", {})
    _set_pdf_color(pdf, style.get("color", "#475569"), draw=True)
    pdf.set_line_width(max(0.45, float(style.get("line_weight", 1.4)) * 0.45 * scale))
    pdf.line(ax, ay, sx, sy)
    pdf.set_fill_color(71, 85, 105)
    pdf.ellipse(ax - 1.8, ay - 1.8, 3.6, 3.6, style="F")
    _set_pdf_color(pdf, style.get("color", "#475569"), draw=True)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(lx - label_width / 2, ly - label_height / 2, label_width, label_height, style="DF")
    pdf.set_text_color(15, 23, 42)
    font_size = max(4, min(8, 7 * scale))
    pdf.set_font("Helvetica", "B", font_size)
    text = str(wire.get("label", ""))
    rotation = 90 if endpoint["side"] in {"top", "bottom"} else 0
    if rotation:
        with pdf.rotation(rotation, x=lx, y=ly):
            _center_text(pdf, lx, ly + font_size * 0.35, text, font_size)
    else:
        _center_text(pdf, lx, ly + font_size * 0.35, text, font_size)


def _draw_wire_list_border(pdf: FPDF, meta: DrawingMeta, page: int, total: int) -> None:
    w, h = LETTER_PORTRAIT
    margin = 28.0
    pdf.set_draw_color(40, 40, 40)
    pdf.set_line_width(1)
    pdf.rect(margin / 2, margin / 2, w - margin, h - margin)
    pdf.rect(margin, margin, w - 2 * margin, h - 2 * margin)
    title_y = margin
    pdf.line(margin, title_y + 52, w - margin, title_y + 52)
    pdf.line(w - margin - 230, title_y, w - margin - 230, title_y + 52)
    pdf.line(w - margin - 120, title_y, w - margin - 120, title_y + 52)
    _label_value(pdf, margin + 8, title_y + 10, "WIRE LIST", meta.title, 6, 11)
    _label_value(pdf, w - margin - 222, title_y + 10, "FILE", meta.file_name, 6, 8)
    _label_value(pdf, w - margin - 112, title_y + 10, "PRINTED", meta.printed_date, 6, 8)
    pdf.set_font("Helvetica", "B", 8)
    pdf.text(w - margin - 112, title_y + 42, f"PAGE {page} OF {total}")


def _draw_wire_list_summary(pdf: FPDF, x: float, y: float, wire_count: int, component_count: int) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.text(x, y, f"Wire count: {wire_count}")
    pdf.text(x + 130, y, f"Component count: {component_count}")


def _draw_wire_list_table(
    pdf: FPDF,
    rows: list[Any],
    diagram_refs: dict[int | str, dict[str, str]],
    x: float,
    y: float,
    width: float,
    row_h: float,
) -> None:
    columns = [
        ("Wire", 72),
        ("From", 95),
        ("Pin", 46),
        ("To", 95),
        ("Pin", 46),
        ("Net", 78),
        ("AWG", 34),
        ("From Ref", 42),
        ("To Ref", 42),
    ]
    scale = width / sum(col_w for _, col_w in columns)
    widths = [col_w * scale for _, col_w in columns]
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(100, 116, 139)
    cursor = x
    for (label, _), col_w in zip(columns, widths):
        pdf.rect(cursor, y, col_w, row_h, style="DF")
        pdf.text(cursor + 2, y + 9.5, label)
        cursor += col_w
    pdf.set_font("Helvetica", "", 6.4)
    for row_index, row in enumerate(rows, start=1):
        cursor = x
        row_y = y + row_index * row_h
        refs = _wire_refs(diagram_refs, row.wirenumber)
        values = [
            row.wirenumber,
            row.from_component,
            row.from_pin,
            row.to_component,
            row.to_pin,
            row.netname,
            str(row.awg),
            refs.get("from", ""),
            refs.get("to", ""),
        ]
        for value, col_w in zip(values, widths):
            pdf.rect(cursor, row_y, col_w, row_h)
            pdf.text(cursor + 2, row_y + 9.2, _clip(str(value), col_w, 6.4))
            cursor += col_w


def _wire_refs(diagram_refs: dict[int | str, dict[str, str]], wire_label: str) -> dict[str, str]:
    return diagram_refs.get(wire_label, {"from": "", "to": ""})


def diagram_reference_grid(data: dict[str, Any]) -> dict[str, Any]:
    """Return the schematic reference grid in source drawing coordinates."""

    geo = _schematic_geometry(data)
    zone_left = geo.drawing_x
    zone_top = geo.drawing_y
    zone_w = geo.drawing_w
    zone_h = geo.drawing_h
    col_w = zone_w / geo.columns
    row_h = zone_h / geo.rows

    verticals = [_pdf_x_to_source(geo, zone_left + index * col_w) for index in range(geo.columns + 1)]
    horizontals = [_pdf_y_to_source(geo, zone_top + index * row_h) for index in range(geo.rows + 1)]
    labels = []
    for row_index in range(geo.rows):
        row_label = chr(ord("A") + row_index)
        for col_index in range(geo.columns):
            labels.append(
                {
                    "ref": f"{row_label}{col_index + 1}",
                    "x": (verticals[col_index] + verticals[col_index + 1]) / 2,
                    "y": (horizontals[row_index] + horizontals[row_index + 1]) / 2,
                }
            )
    return {
        "columns": geo.columns,
        "rows": geo.rows,
        "verticals": verticals,
        "horizontals": horizontals,
        "labels": labels,
    }


def _diagram_references(data: dict[str, Any], geo: SheetGeometry) -> dict[int | str, dict[str, str]]:
    refs: dict[int | str, dict[str, str]] = {}
    grid = data.get("reference_grid")
    for wire in data.get("wires", []):
        endpoints = wire.get("endpoints", [])
        wire_refs: dict[str, str] = {}
        for ref_key, endpoint in zip(("from", "to"), endpoints[:2]):
            point = endpoint.get("anchor", {})
            if "x" not in point or "y" not in point:
                continue
            wire_refs[ref_key] = _zone_ref(float(point["x"]), float(point["y"]), geo, grid)
        if not wire_refs:
            continue
        refs[int(wire.get("index", 0))] = wire_refs
        refs[str(wire.get("label", ""))] = wire_refs
    return refs


def _zone_ref(x: float, y: float, geo: SheetGeometry, grid: dict[str, Any] | None = None) -> str:
    zone = _zone_ref_from_grid(x, y, grid)
    if zone:
        return zone
    px, py = _map_point(geo, x, y)
    rel_x = min(max((px - geo.drawing_x) / max(1, geo.drawing_w), 0), 0.9999)
    rel_y = min(max((py - geo.drawing_y) / max(1, geo.drawing_h), 0), 0.9999)
    col = int(rel_x * geo.columns) + 1
    row = chr(ord("A") + int(rel_y * geo.rows))
    return f"{row}{col}"


def _zone_ref_from_grid(x: float, y: float, grid: dict[str, Any] | None) -> str | None:
    if not isinstance(grid, dict):
        return None
    verticals = grid.get("verticals")
    horizontals = grid.get("horizontals")
    rows = int(grid.get("rows", 0) or 0)
    columns = int(grid.get("columns", 0) or 0)
    if not isinstance(verticals, list) or not isinstance(horizontals, list):
        return None
    if len(verticals) < 2 or len(horizontals) < 2:
        return None
    if rows < 1 or columns < 1:
        return None

    col_index = bisect_right(verticals, x) - 1
    row_index = bisect_right(horizontals, y) - 1
    col_index = max(0, min(columns - 1, col_index))
    row_index = max(0, min(rows - 1, row_index))
    row_label = chr(ord("A") + row_index)
    return f"{row_label}{col_index + 1}"


def _rotated_rect_corners(x: float, y: float, w: float, h: float, rotation: float) -> list[tuple[float, float]]:
    center = (x + w / 2, y + h / 2)
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return [_rotate_point(point, center, rotation) for point in corners]


def _rotate_point(point: tuple[float, float], center: tuple[float, float], rotation: float) -> tuple[float, float]:
    radians = math.radians(rotation)
    px, py = point
    cx, cy = center
    dx, dy = px - cx, py - cy
    return (cx + dx * math.cos(radians) - dy * math.sin(radians), cy + dx * math.sin(radians) + dy * math.cos(radians))


def _map_point(geo: SheetGeometry, x: float, y: float) -> tuple[float, float]:
    return geo.drawing_x + (x - geo.source_min_x) * geo.scale, geo.drawing_y + (y - geo.source_min_y) * geo.scale


def _pdf_x_to_source(geo: SheetGeometry, x: float) -> float:
    return (x - geo.drawing_x) / geo.scale + geo.source_min_x


def _pdf_y_to_source(geo: SheetGeometry, y: float) -> float:
    return (y - geo.drawing_y) / geo.scale + geo.source_min_y


def _pin_boundary_local(pin: dict[str, Any]) -> tuple[float, float]:
    x, y = float(pin["x"]), float(pin["y"])
    w, h = float(pin["width"]), float(pin["height"])
    side = pin.get("side")
    if side == "left":
        return x, y + h / 2
    if side == "right":
        return x + w, y + h / 2
    if side == "top":
        return x + w / 2, y
    return x + w / 2, y + h


def _side_vector(side: str) -> tuple[float, float]:
    if side == "left":
        return -1, 0
    if side == "right":
        return 1, 0
    if side == "top":
        return 0, -1
    return 0, 1


def _fan_offset(side: str, slot: int, slot_count: int, spacing: float) -> tuple[float, float]:
    if slot_count <= 1:
        return 0, 0
    offset = (slot - (slot_count - 1) / 2) * spacing
    if side in {"left", "right"}:
        return 0, offset
    return offset, 0


def _set_pdf_color(pdf: FPDF, color: str, draw: bool = False) -> None:
    color = color.lstrip("#")
    try:
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    except Exception:
        r, g, b = 71, 85, 105
    if draw:
        pdf.set_draw_color(r, g, b)
    else:
        pdf.set_text_color(r, g, b)


def _center_text(pdf: FPDF, x: float, y: float, value: str, size: float) -> None:
    pdf.set_font_size(size)
    pdf.text(x - pdf.get_string_width(value) / 2, y, value)


def _label_value(pdf: FPDF, x: float, y: float, label: str, value: str, label_size: float, value_size: float) -> None:
    pdf.set_font("Helvetica", "B", label_size)
    pdf.text(x, y, label)
    pdf.set_font("Helvetica", "", value_size)
    pdf.text(x, y + value_size + 4, _clip(value, 120, value_size))


def _clip(value: str, width: float, font_size: float) -> str:
    max_chars = max(1, int(width / max(font_size * 0.55, 1)))
    return value if len(value) <= max_chars else value[: max(1, max_chars - 1)] + "?"
