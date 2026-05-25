"""Printable wire-label PDF generation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

from panelviz.parser import LabelConfig
from panelviz.reports import wire_list_rows
from panelviz.routing import WireRouter

PT_PER_IN = 72.0
LETTER_WIDTH_IN = 8.5
LETTER_HEIGHT_IN = 11.0


@dataclass(frozen=True)
class WireLabelLayout:
    """Physical dimensions for one wrap-around wire label."""

    text: str
    width_in: float
    height_in: float
    text_count: int
    font_height_in: float


@dataclass(frozen=True)
class WireLabelCell:
    """One placed label on a US-letter page."""

    text: str
    x_in: float
    y_in: float
    width_in: float
    height_in: float


class WireLabelCalculator:
    """Measure and place printable wire labels on cutter-friendly grids."""

    def __init__(self, config: LabelConfig):
        self.config = config
        self._measurement_pdf = _measurement_pdf(config)

    def layout_for_text(self, text: str) -> WireLabelLayout:
        """Return snapped physical label dimensions for one wire label."""

        font_height_in = _font_height_in(self.config)
        clearance_in = _text_clearance_in(self.config)
        text_width_in = self._measurement_pdf.get_string_width(text) / PT_PER_IN
        raw_width = text_width_in + self.config.left_margin + self.config.right_margin
        width = max(1.0, _snap_up(raw_width, self.config.width_increment))
        text_count = len(self.config.whitespace) + 1
        height = (text_count + sum(self.config.whitespace)) * font_height_in + 2 * clearance_in
        return WireLabelLayout(
            text=text,
            width_in=width,
            height_in=height,
            text_count=text_count,
            font_height_in=font_height_in,
        )

    def paginate(self, labels: list[str]) -> list[list[WireLabelCell]]:
        """Pack labels into fixed-width columns so every page has stable cut lines."""

        if not labels:
            return []
        labels_by_width: dict[float, list[str]] = {}
        row_height = self.layout_for_text(labels[0]).height_in
        for label in labels:
            layout = self.layout_for_text(label)
            labels_by_width.setdefault(layout.width_in, []).append(label)

        pages: list[list[WireLabelCell]] = []
        printable_width = LETTER_WIDTH_IN - 2 * self.config.page_margin
        printable_height = LETTER_HEIGHT_IN - 2 * self.config.page_margin
        rows_per_page = max(1, math.floor(printable_height / row_height + 1e-9))

        column_chunks: list[tuple[float, list[str]]] = []
        for width in sorted(labels_by_width, reverse=True):
            group = labels_by_width[width]
            for start in range(0, len(group), rows_per_page):
                column_chunks.append((width, group[start : start + rows_per_page]))
        column_chunks.sort(key=lambda item: (len(item[1]) < rows_per_page, -item[0]))

        packed_pages: list[list[tuple[float, list[str]]]] = []
        used_widths: list[float] = []
        for width, chunk in column_chunks:
            for page_index, used_width in enumerate(used_widths):
                if used_width + width <= printable_width + 1e-9:
                    packed_pages[page_index].append((width, chunk))
                    used_widths[page_index] += width
                    break
            else:
                packed_pages.append([(width, chunk)])
                used_widths.append(width)

        for page_columns in packed_pages:
            page_cells: list[WireLabelCell] = []
            x = self.config.page_margin
            for width, chunk in page_columns:
                for row, label in enumerate(chunk):
                    page_cells.append(
                        WireLabelCell(
                            label,
                            x,
                            self.config.page_margin + row * row_height,
                            width,
                            row_height,
                        )
                    )
                x += width
            pages.append(page_cells)
        return pages


def wire_label_groups(router: WireRouter) -> dict[str, list[str]]:
    """Return wire labels grouped by endpoint component tags."""

    groups: dict[str, list[str]] = {}
    for row in wire_list_rows(router, grouped=False):
        tags = [tag.strip() for tag in row.tags.split(",") if tag.strip()]
        for tag in tags:
            groups.setdefault(tag, [])
            if row.wirenumber not in groups[tag]:
                groups[tag].append(row.wirenumber)
    return groups


def wire_label_layout(text: str, config: LabelConfig, pdf: FPDF | None = None) -> WireLabelLayout:
    """Return snapped physical label dimensions for one wire label."""

    if pdf is None:
        return WireLabelCalculator(config).layout_for_text(text)
    font_height_in = _font_height_in(config)
    clearance_in = _text_clearance_in(config)
    text_width_in = pdf.get_string_width(text) / PT_PER_IN
    raw_width = text_width_in + config.left_margin + config.right_margin
    width = max(1.0, _snap_up(raw_width, config.width_increment))
    text_count = len(config.whitespace) + 1
    height = (text_count + sum(config.whitespace)) * font_height_in + 2 * clearance_in
    return WireLabelLayout(text, width, height, text_count, font_height_in)


def paginate_wire_labels(labels: list[str], config: LabelConfig) -> list[list[WireLabelCell]]:
    """Pack labels densely onto one or more US-letter portrait pages."""

    return WireLabelCalculator(config).paginate(labels)


def write_wire_label_pdfs(router: WireRouter, output_dir: str | Path, config: LabelConfig) -> list[Path]:
    """Write one or more wire-label PDFs for each distinct component tag."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for tag, labels in sorted(wire_label_groups(router).items()):
        pages = paginate_wire_labels(labels, config)
        safe_tag = _safe_filename_tag(tag)
        for page_index, cells in enumerate(pages, start=1):
            suffix = "" if page_index == 1 else str(page_index)
            path = destination / f"wirelabel_{safe_tag}{suffix}.pdf"
            path.write_bytes(render_wire_label_pdf(cells, config))
            written.append(path)
    return written


def render_wire_label_pdf(cells: list[WireLabelCell], config: LabelConfig) -> bytes:
    """Render a single-page US-letter PDF containing wire-label cells."""

    pdf = FPDF(unit="in", format="letter")
    pdf.set_auto_page_break(False)
    pdf.set_compression(True)
    pdf.add_page()
    pdf.set_margins(0, 0, 0)
    _set_font(pdf, config)
    _set_text_color(pdf, config)
    pdf.set_draw_color(150, 150, 150)
    pdf.set_line_width(0.003)
    _draw_label_grid(pdf, cells, config)
    for cell in cells:
        _draw_label_text(pdf, cell, config)
    return bytes(pdf.output())


def _draw_label_grid(pdf: FPDF, cells: list[WireLabelCell], config: LabelConfig) -> None:
    if not cells:
        return
    row_height = cells[0].height_in
    printable_width = LETTER_WIDTH_IN - 2 * config.page_margin
    printable_height = LETTER_HEIGHT_IN - 2 * config.page_margin
    rows = max(1, math.floor(printable_height / row_height + 1e-9))
    boundaries = sorted({round(cell.x_in, 6) for cell in cells} | {round(cell.x_in + cell.width_in, 6) for cell in cells})
    x0 = boundaries[0]
    x1 = boundaries[-1]
    y0 = config.page_margin
    y1 = y0 + rows * row_height
    for x in boundaries:
        pdf.line(x, y0, x, y1)
    for row in range(rows + 1):
        y = y0 + row * row_height
        pdf.line(x0, y, x1, y)


def _draw_label_text(pdf: FPDF, cell: WireLabelCell, config: LabelConfig) -> None:
    font_height = _font_height_in(config)
    clearance = _text_clearance_in(config)
    center_x = cell.x_in + cell.width_in / 2
    y = cell.y_in + clearance
    for index in range(len(config.whitespace) + 1):
        baseline_y = y + font_height * 0.82
        pdf.text(center_x - pdf.get_string_width(cell.text) / 2, baseline_y, cell.text)
        y += font_height
        if index < len(config.whitespace):
            y += config.whitespace[index] * font_height


def _measurement_pdf(config: LabelConfig) -> FPDF:
    pdf = FPDF(unit="pt", format="letter")
    pdf.add_page()
    _set_font(pdf, config)
    return pdf


def _set_font(pdf: FPDF, config: LabelConfig) -> None:
    family = _style_value(config, "font-family") or config.font_face
    weight = (_style_value(config, "font-weight") or "").lower()
    style = "B" if weight in {"bold", "700", "800", "900"} else ""
    pdf.set_font(family, style, _font_height_in(config) * PT_PER_IN)


def _set_text_color(pdf: FPDF, config: LabelConfig) -> None:
    color = (_style_value(config, "color") or "#000000").lstrip("#")
    if len(color) != 6:
        pdf.set_text_color(0, 0, 0)
        return
    try:
        pdf.set_text_color(int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    except ValueError:
        pdf.set_text_color(0, 0, 0)


def _font_height_in(config: LabelConfig) -> float:
    style_size = _style_value(config, "font-size")
    if style_size:
        parsed = _parse_css_length_in(style_size)
        if parsed is not None:
            return parsed
    return config.font_height / PT_PER_IN if config.font_height_unit == "pt" else config.font_height


def _text_clearance_in(config: LabelConfig) -> float:
    return config.text_clearance / PT_PER_IN if config.text_clearance_unit == "pt" else config.text_clearance


def _parse_css_length_in(value: str) -> float | None:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(pt|in)\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    return number / PT_PER_IN if match.group(2) == "pt" else number


def _style_value(config: LabelConfig, key: str) -> str | None:
    for style_key, value in config.style.items():
        if style_key.lower() == key:
            return value
    return None


def _snap_up(value: float, increment: float) -> float:
    return math.ceil(value / increment - 1e-9) * increment


def _safe_filename_tag(tag: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag.strip())
    return safe or "untagged"
