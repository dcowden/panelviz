"""Printable wire-label PDF generation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

from panelviz.parser import LabelConfig
from panelviz.routing import WireRouter
from panelviz.label_assignment import ComponentLabelRow

PT_PER_IN = 72.0
LETTER_WIDTH_IN = 8.5
LETTER_HEIGHT_IN = 11.0
PREMIUM_2_625X1_LEFT_IN = 0.1875
PREMIUM_2_625X1_TOP_IN = 0.5
PREMIUM_2_625X1_LABEL_WIDTH_IN = 2.625
PREMIUM_2_625X1_LABEL_HEIGHT_IN = 1.0
PREMIUM_2_625X1_COLUMN_PITCH_IN = 2.75
PREMIUM_2_625X1_ROW_PITCH_IN = 1.0
PREMIUM_2_625X1_COLUMNS = 3
PREMIUM_2_625X1_ROWS = 10
PREMIUM_2_625X1_TEXT_LEADING_IN = 0.1875


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


@dataclass(frozen=True)
class ComponentMapPin:
    """One terminal placed in a compact printable component map."""

    pin: str
    side: str
    x_in: float
    y_in: float
    width_in: float
    height_in: float
    nets: tuple[str, ...]


@dataclass(frozen=True)
class ComponentMapLayout:
    """Compact printable geometry for a component map."""

    width_in: float
    height_in: float
    body_x_in: float
    body_y_in: float
    body_width_in: float
    body_height_in: float
    pins: tuple[ComponentMapPin, ...]


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
        height = (text_count + sum(self.config.whitespace)) * font_height_in + 2 * clearance_in + self.config.tail_length
        return WireLabelLayout(
            text=text,
            width_in=width,
            height_in=height,
            text_count=text_count,
            font_height_in=font_height_in,
        )

    def paginate(self, labels: list[str]) -> list[list[WireLabelCell]]:
        """Pack labels row-first into fixed-width columns for cutter-friendly pages."""

        if self.config.stock == "premium_2_625x1_split":
            return _paginate_premium_2_625x1_split(labels)
        if not labels:
            return []
        row_height = self.layout_for_text(labels[0]).height_in
        printable_width = LETTER_WIDTH_IN - 2 * self.config.page_margin
        printable_height = LETTER_HEIGHT_IN - 2 * self.config.page_margin
        rows_per_page = max(1, math.floor(printable_height / row_height + 1e-9))
        pages: list[list[WireLabelCell]] = []
        index = 0

        while index < len(labels):
            columns: list[float] = []
            rows: list[list[str | None]] = [[] for _ in range(rows_per_page)]

            while index < len(labels):
                label = labels[index]
                required_width = self.layout_for_text(label).width_in
                if columns and sum(columns) + required_width > printable_width + 1e-9:
                    break
                columns.append(min(required_width, printable_width))
                for existing_row in rows:
                    existing_row.append(None)
                rows[0][len(columns) - 1] = label
                index += 1

            if not columns:
                label = labels[index]
                columns.append(printable_width)
                for existing_row in rows:
                    existing_row.append(None)
                rows[0][0] = label
                index += 1

            page_full = index >= len(labels)
            for row in range(1, rows_per_page):
                if page_full:
                    break
                for column in range(len(columns)):
                    if index >= len(labels):
                        page_full = True
                        break
                    label = labels[index]
                    required_width = self.layout_for_text(label).width_in
                    if required_width > columns[column]:
                        growth = required_width - columns[column]
                        if sum(columns) + growth > printable_width + 1e-9:
                            page_full = True
                            break
                        columns[column] = required_width
                    rows[row][column] = label
                    index += 1

            x_positions = [self.config.page_margin]
            for width in columns[:-1]:
                x_positions.append(x_positions[-1] + width)

            page_cells: list[WireLabelCell] = []
            for row_index, row in enumerate(rows):
                for column_index, label in enumerate(row):
                    if label is None:
                        continue
                    page_cells.append(
                        WireLabelCell(
                            label,
                            x_positions[column_index],
                            self.config.page_margin + row_index * row_height,
                            columns[column_index],
                            row_height,
                        )
                    )
            pages.append(page_cells)
        return pages


def wire_label_groups(router: WireRouter) -> dict[str, list[str]]:
    """Return tag-oriented wire labels, sorted by net and duplicated for both ends.

    Each tag sheet is intended to stand alone at the workbench. If a wire spans
    tags, both physical-end labels are printed in each involved tag group so the
    installer does not have to fetch the matching label from another sheet.
    """

    groups: dict[str, list[tuple[str, str, int]]] = {}
    for wire in router.routed_wires:
        label = wire.wire_label or f"wire-{wire.index}"
        net_name = wire.net_name or ""
        endpoint_tags = set(router.components[wire.from_pin.component].tags) | set(router.components[wire.to_pin.component].tags)
        for tag in endpoint_tags:
            groups.setdefault(tag, []).extend([(net_name, label, wire.index), (net_name, label, wire.index)])
    return {
        tag: [label for _, label, _ in sorted(labels, key=lambda item: (item[0], item[1], item[2]))]
        for tag, labels in groups.items()
    }


def all_wire_labels(router: WireRouter) -> list[str]:
    """Return every physical wire label twice, sorted alphabetically in pairs."""

    labels = sorted((wire.wire_label or f"wire-{wire.index}" for wire in router.routed_wires), key=lambda label: label.lower())
    return [label for label in labels for _ in range(2)]


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
    height = (text_count + sum(config.whitespace)) * font_height_in + 2 * clearance_in + config.tail_length
    return WireLabelLayout(text, width, height, text_count, font_height_in)


def paginate_wire_labels(labels: list[str], config: LabelConfig) -> list[list[WireLabelCell]]:
    """Pack labels densely onto one or more US-letter portrait pages."""

    return WireLabelCalculator(config).paginate(labels)


def write_wire_label_pdfs(router: WireRouter, output_dir: str | Path, config: LabelConfig) -> list[Path]:
    """Write tag wire-label PDFs plus one consolidated all-labels PDF."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    all_labels = all_wire_labels(router)
    if all_labels:
        path = destination / "all_labels.pdf"
        path.write_bytes(render_wire_label_pages_pdf(paginate_wire_labels(all_labels, config), config))
        written.append(path)
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

    return render_wire_label_pages_pdf([cells], config)


def render_wire_label_pages_pdf(pages: list[list[WireLabelCell]], config: LabelConfig) -> bytes:
    """Render one or more US-letter wire-label pages into a single PDF."""

    pdf = FPDF(unit="in", format="letter")
    pdf.set_auto_page_break(False)
    pdf.set_compression(True)
    for cells in pages or [[]]:
        pdf.add_page()
        pdf.set_margins(0, 0, 0)
        _set_font(pdf, config)
        _set_text_color(pdf, config)
        pdf.set_draw_color(150, 150, 150)
        pdf.set_line_width(0.003)
        if config.stock == "premium_2_625x1_split":
            _draw_premium_2_625x1_cut_lines(pdf)
            for cell in cells:
                _draw_premium_split_label_text(pdf, cell, config)
            continue
        _draw_label_grid(pdf, cells, config)
        for cell in cells:
            _draw_label_text(pdf, cell, config)
    return bytes(pdf.output())


def render_component_label_sheet_pdf(
    component_name: str,
    rows: list[ComponentLabelRow],
    config: LabelConfig,
    component: dict | None = None,
) -> bytes:
    """Render a component check sheet followed by printable wire-label pages."""

    pdf = FPDF(orientation="P", unit="in", format="letter")
    pdf.set_compression(True)
    pdf.set_auto_page_break(False)
    label_pages = _component_label_pages([row.label for row in rows], config)
    if not label_pages:
        label_pages = [[]]

    total_pages = len(label_pages) + 1
    pdf.add_page()
    pdf.set_margins(0, 0, 0)
    _draw_component_summary_page(pdf, component_name, rows, 1, total_pages, component)

    for page_offset, cells in enumerate(label_pages, start=2):
        pdf.add_page()
        pdf.set_margins(0, 0, 0)
        if config.stock != "premium_2_625x1_split":
            _draw_component_sheet_page_header(pdf, component_name, page_offset, total_pages)
        _set_font(pdf, config)
        _set_text_color(pdf, config)
        pdf.set_draw_color(150, 150, 150)
        pdf.set_line_width(0.003)
        if config.stock == "premium_2_625x1_split":
            _draw_premium_2_625x1_cut_lines(pdf)
            for cell in cells:
                _draw_premium_split_label_text(pdf, cell, config)
            continue
        for cell in cells:
            pdf.rect(cell.x_in, cell.y_in, cell.width_in, cell.height_in)
            _draw_label_text(pdf, cell, config)
    return bytes(pdf.output())


def _component_label_pages(labels: list[str], config: LabelConfig) -> list[list[WireLabelCell]]:
    if not labels:
        return []
    if config.stock == "premium_2_625x1_split":
        return _paginate_premium_2_625x1_split(labels)
    calculator = WireLabelCalculator(config)
    top = 0.78
    printable_width = LETTER_WIDTH_IN - 2 * config.page_margin
    printable_height = LETTER_HEIGHT_IN - config.page_margin - top
    row_height = calculator.layout_for_text(labels[0]).height_in
    rows_per_page = max(1, math.floor(printable_height / row_height + 1e-9))
    pages: list[list[WireLabelCell]] = []
    index = 0
    while index < len(labels):
        columns: list[float] = []
        grid: list[list[str | None]] = [[] for _ in range(rows_per_page)]
        while index < len(labels):
            width = min(calculator.layout_for_text(labels[index]).width_in, printable_width)
            if columns and sum(columns) + width > printable_width + 1e-9:
                break
            columns.append(width)
            for row in grid:
                row.append(None)
            grid[0][len(columns) - 1] = labels[index]
            index += 1
        if not columns:
            columns.append(printable_width)
            for row in grid:
                row.append(None)
            grid[0][0] = labels[index]
            index += 1
        for row_index in range(1, rows_per_page):
            for column_index in range(len(columns)):
                if index >= len(labels):
                    break
                width = calculator.layout_for_text(labels[index]).width_in
                if width > columns[column_index]:
                    growth = width - columns[column_index]
                    if sum(columns) + growth > printable_width + 1e-9:
                        break
                    columns[column_index] = width
                grid[row_index][column_index] = labels[index]
                index += 1
            else:
                continue
            break

        x_positions = [config.page_margin]
        for width in columns[:-1]:
            x_positions.append(x_positions[-1] + width)
        cells = []
        for row_index, row in enumerate(grid):
            for column_index, label in enumerate(row):
                if label is None:
                    continue
                cells.append(
                    WireLabelCell(
                        label,
                        x_positions[column_index],
                        top + row_index * row_height,
                        columns[column_index],
                        row_height,
                    )
                )
        pages.append(cells)
    return pages


def _draw_component_sheet_page_header(pdf: FPDF, component_name: str, page_index: int, total_pages: int) -> None:
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(15, 23, 42)
    pdf.text(0.45, 0.45, f"{component_name} wire labels")
    pdf.set_font("Helvetica", "", 8)
    pdf.text(7.35, 0.45, f"Page {page_index} of {total_pages}")
    pdf.set_draw_color(203, 213, 225)
    pdf.set_line_width(0.006)
    pdf.line(0.45, 0.62, 8.05, 0.62)


def _draw_component_summary_page(
    pdf: FPDF,
    component_name: str,
    rows: list[ComponentLabelRow],
    page_index: int,
    total_pages: int,
    component: dict | None,
) -> None:
    _draw_component_sheet_page_header(pdf, component_name, page_index, total_pages)

    if component:
        _draw_component_map(pdf, component, rows, 0.55, 0.78, 7.4, 2.85)
    else:
        pdf.set_draw_color(71, 85, 105)
        pdf.set_line_width(0.018)
        pdf.rect(2.7, 1.15, 3.0, 1.85)
        pdf.set_font("Helvetica", "B", 12)
        pdf.text(3.2, 2.1, component_name[:24])
    pdf.set_font("Helvetica", "", 7)
    pdf.text(0.72, 3.78, "Component map")
    pdf.line(0.55, 3.65, 7.95, 3.65)

    pdf.set_font("Helvetica", "B", 7)
    table_x = 0.55
    table_y = 4.0
    pdf.text(table_x, table_y, "Label")
    pdf.text(table_x + 1.25, table_y, "Pin")
    pdf.text(table_x + 2.0, table_y, "Net")
    pdf.text(table_x + 3.55, table_y, "Other end")
    pdf.set_font("Helvetica", "", 7)
    y = table_y + 0.18
    max_rows = 42
    for row in rows[:max_rows]:
        pdf.text(table_x, y, row.label[:22])
        pdf.text(table_x + 1.25, y, row.pin[:14])
        pdf.text(table_x + 2.0, y, row.net[:24])
        pdf.text(table_x + 3.55, y, row.other_endpoint[:45])
        y += 0.145
    if len(rows) > max_rows:
        pdf.text(table_x, y, f"... {len(rows) - max_rows} more wire ends")


def _draw_component_map(
    pdf: FPDF,
    component: dict,
    rows: list[ComponentLabelRow],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    pin_nets = _row_nets_by_pin(rows)
    layout = compact_component_map_layout(pdf, component, pin_nets)
    ox = x + max(0, (width - layout.width_in) / 2)
    oy = y + max(0, (height - layout.height_in) / 2)

    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(31, 41, 55)
    pdf.set_line_width(0.012)
    pdf.rect(
        ox + layout.body_x_in,
        oy + layout.body_y_in,
        layout.body_width_in,
        layout.body_height_in,
        round_corners=True,
        corner_radius=0.045,
        style="DF",
    )

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(15, 23, 42)
    body_center_x = ox + layout.body_x_in + layout.body_width_in / 2
    body_center_y = oy + layout.body_y_in + layout.body_height_in / 2
    _centered_text(pdf, str(component.get("name") or ""), body_center_x, body_center_y - 0.03)
    subtitle = ", ".join(str(tag) for tag in component.get("tags", [])) or str(component.get("type") or "")
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(100, 116, 139)
    _centered_text(pdf, subtitle[:32], body_center_x, body_center_y + 0.10)

    for placed_pin in layout.pins:
        _draw_component_pin(pdf, placed_pin, ox, oy)

    pdf.set_text_color(15, 23, 42)


def compact_component_map_layout(pdf: FPDF, component: dict, pin_nets: dict[str, str] | None = None) -> ComponentMapLayout:
    """Return a native-scale terminal map with a compact, content-sized body.

    This layout is intentionally different from the main panel drawing: printed
    component-label sheets need terminals and text to remain legible, while the
    component body can shrink or grow to whatever size the terminals require.
    """

    pin_nets = pin_nets or {}
    pins_by_side: dict[str, list[ComponentMapPin]] = {"top": [], "right": [], "bottom": [], "left": []}
    component_rotation = int(round(float(component.get("rotation", 0) or 0) / 90)) * 90
    odd_turn = (component_rotation // 90) % 2 != 0
    for pin in component.get("pins", []):
        side = str(pin.get("side") or "")
        if side in pins_by_side:
            pin_name = str(pin.get("pin") or "")
            net_names = [str(net) for net in pin.get("nets", [])]
            if pin_name in pin_nets and pin_nets[pin_name] not in net_names:
                net_names.append(pin_nets[pin_name])
            pin_width = max(float(pin.get("width", 0)) / PT_PER_IN, 0.07)
            pin_height = max(float(pin.get("height", 0)) / PT_PER_IN, 0.07)
            if odd_turn:
                pin_width, pin_height = pin_height, pin_width
            screen_side = _rotated_side(side, component_rotation)
            pins_by_side[screen_side].append(
                ComponentMapPin(
                    pin=pin_name,
                    side=screen_side,
                    x_in=0,
                    y_in=0,
                    width_in=pin_width,
                    height_in=pin_height,
                    nets=tuple(net_names),
                )
            )

    horizontal_gap = 0.0
    vertical_gap = 0.0
    side_gap = 0.0
    name_text = str(component.get("name") or "")
    subtitle = ", ".join(str(tag) for tag in component.get("tags", [])) or str(component.get("type") or "")
    pdf.set_font("Helvetica", "B", 8)
    name_width = pdf.get_string_width(name_text)
    pdf.set_font("Helvetica", "", 6)
    subtitle_width = pdf.get_string_width(subtitle[:32])
    text_width = max(name_width, subtitle_width) + 0.28

    top_width = _pin_band_width(pins_by_side["top"], horizontal_gap)
    bottom_width = _pin_band_width(pins_by_side["bottom"], horizontal_gap)
    left_height = _pin_band_height(pins_by_side["left"], vertical_gap)
    right_height = _pin_band_height(pins_by_side["right"], vertical_gap)
    left_width = _pin_band_depth(pins_by_side["left"])
    right_width = _pin_band_depth(pins_by_side["right"])
    top_height = _pin_band_depth(pins_by_side["top"])
    bottom_height = _pin_band_depth(pins_by_side["bottom"])

    body_width = max(0.9, text_width, top_width, bottom_width)
    body_height = max(0.65, left_height, right_height, 0.48)
    body_x = left_width + side_gap
    body_y = top_height + side_gap
    total_width = body_x + body_width + side_gap + right_width
    total_height = body_y + body_height + side_gap + bottom_height
    placed: list[ComponentMapPin] = []

    _place_horizontal_pins(placed, pins_by_side["top"], "top", body_x, body_y - top_height, body_width, top_height, horizontal_gap)
    _place_horizontal_pins(
        placed,
        pins_by_side["bottom"],
        "bottom",
        body_x,
        body_y + body_height,
        body_width,
        bottom_height,
        horizontal_gap,
    )
    _place_vertical_pins(placed, pins_by_side["left"], "left", body_x - left_width, body_y, left_width, body_height, vertical_gap)
    _place_vertical_pins(
        placed,
        pins_by_side["right"],
        "right",
        body_x + body_width,
        body_y,
        right_width,
        body_height,
        vertical_gap,
    )

    return ComponentMapLayout(
        width_in=total_width,
        height_in=total_height,
        body_x_in=body_x,
        body_y_in=body_y,
        body_width_in=body_width,
        body_height_in=body_height,
        pins=tuple(placed),
    )


def _place_horizontal_pins(
    placed: list[ComponentMapPin],
    pins: list[ComponentMapPin],
    side: str,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
) -> None:
    if not pins:
        return
    band_width = _pin_band_width(pins, gap)
    current_x = x + (width - band_width) / 2
    for pin in pins:
        pin_width = pin.width_in
        pin_height = pin.height_in
        placed.append(
            ComponentMapPin(
                pin=pin.pin,
                side=side,
                x_in=current_x,
                y_in=y + height - pin_height,
                width_in=pin_width,
                height_in=pin_height,
                nets=pin.nets,
            )
        )
        current_x += pin_width + gap


def _place_vertical_pins(
    placed: list[ComponentMapPin],
    pins: list[ComponentMapPin],
    side: str,
    x: float,
    y: float,
    width: float,
    height: float,
    gap: float,
) -> None:
    if not pins:
        return
    band_height = _pin_band_height(pins, gap)
    current_y = y + (height - band_height) / 2
    for pin in pins:
        pin_width = pin.width_in
        pin_height = pin.height_in
        placed.append(
            ComponentMapPin(
                pin=pin.pin,
                side=side,
                x_in=x + width - pin_width,
                y_in=current_y,
                width_in=pin_width,
                height_in=pin_height,
                nets=pin.nets,
            )
        )
        current_y += pin_height + gap


def _pin_band_width(pins: list[ComponentMapPin], gap: float) -> float:
    if not pins:
        return 0.0
    return sum(pin.width_in for pin in pins) + gap * (len(pins) - 1)


def _pin_band_height(pins: list[ComponentMapPin], gap: float) -> float:
    if not pins:
        return 0.0
    return sum(pin.height_in for pin in pins) + gap * (len(pins) - 1)


def _pin_band_depth(pins: list[ComponentMapPin]) -> float:
    if not pins:
        return 0.0
    return max(pin.height_in if pin.side in {"top", "bottom"} else pin.width_in for pin in pins)


def _rotated_side(side: str, rotation: int) -> str:
    sides = ("top", "right", "bottom", "left")
    if side not in sides:
        return side
    turns = ((rotation // 90) % 4 + 4) % 4
    return sides[(sides.index(side) + turns) % len(sides)]


def _draw_component_pin(pdf: FPDF, pin: ComponentMapPin, ox: float, oy: float) -> None:
    px = ox + pin.x_in
    py = oy + pin.y_in
    pw = max(pin.width_in, 0.015)
    ph = max(pin.height_in, 0.015)
    side = pin.side
    pin_name = pin.pin
    net_names = list(pin.nets)

    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(148, 163, 184)
    pdf.set_line_width(0.004)
    pdf.rect(px, py, pw, ph, style="DF")

    terminal_size = max(3.5, min(5.5, min(pw, ph) * 72 * 0.62))
    pdf.set_font("Helvetica", "", terminal_size)
    pdf.set_text_color(15, 23, 42)
    _oriented_text(pdf, pin_name[:10], px + pw / 2, py + ph / 2, -90 if side in {"top", "bottom"} else 0)

    if not net_names:
        return
    net_text = ", ".join(net_names)[:24]
    pdf.set_font("Helvetica", "B", max(3.2, min(4.8, terminal_size * 0.78)))
    pdf.set_text_color(37, 99, 235)
    gap = 0.025
    if side == "left":
        _left_text(pdf, net_text, px + pw + gap, py + ph / 2)
    elif side == "right":
        _right_text(pdf, net_text, px - gap, py + ph / 2)
    elif side == "top":
        _oriented_text(pdf, net_text, px + pw / 2, py + ph + gap + 0.04, -90)
    else:
        _oriented_text(pdf, net_text, px + pw / 2, py - gap, -90)


def _row_nets_by_pin(rows: list[ComponentLabelRow]) -> dict[str, str]:
    pin_nets: dict[str, str] = {}
    for row in rows:
        if row.net and row.pin not in pin_nets:
            pin_nets[row.pin] = row.net
    return pin_nets


def _centered_text(pdf: FPDF, text: str, x: float, y: float) -> None:
    pdf.text(x - pdf.get_string_width(text) / 2, y, text)


def _left_text(pdf: FPDF, text: str, x: float, y: float) -> None:
    pdf.text(x, y + _font_size_in(pdf) * 0.32, text)


def _right_text(pdf: FPDF, text: str, x: float, y: float) -> None:
    pdf.text(x - pdf.get_string_width(text), y + _font_size_in(pdf) * 0.32, text)


def _oriented_text(pdf: FPDF, text: str, x: float, y: float, angle: float) -> None:
    if not text:
        return
    if angle == 0:
        _centered_text(pdf, text, x, y + _font_size_in(pdf) * 0.32)
        return
    with pdf.rotation(angle, x=x, y=y):
        pdf.text(x - pdf.get_string_width(text) / 2, y + _font_size_in(pdf) * 0.32, text)


def _font_size_in(pdf: FPDF) -> float:
    return float(pdf.font_size or 0) / PT_PER_IN


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


def _paginate_premium_2_625x1_split(labels: list[str]) -> list[list[WireLabelCell]]:
    """Place two wire labels on each 2.625 x 1.0 inch pre-cut address label."""

    if not labels:
        return []
    half_width = PREMIUM_2_625X1_LABEL_WIDTH_IN / 2
    cells_per_page = PREMIUM_2_625X1_COLUMNS * PREMIUM_2_625X1_ROWS * 2
    pages: list[list[WireLabelCell]] = []
    for page_start in range(0, len(labels), cells_per_page):
        page_labels = labels[page_start : page_start + cells_per_page]
        page_cells: list[WireLabelCell] = []
        for index, label in enumerate(page_labels):
            sticker_index = index // 2
            split_index = index % 2
            row = sticker_index // PREMIUM_2_625X1_COLUMNS
            column = sticker_index % PREMIUM_2_625X1_COLUMNS
            page_cells.append(
                WireLabelCell(
                    text=label,
                    x_in=PREMIUM_2_625X1_LEFT_IN + column * PREMIUM_2_625X1_COLUMN_PITCH_IN + split_index * half_width,
                    y_in=PREMIUM_2_625X1_TOP_IN + row * PREMIUM_2_625X1_ROW_PITCH_IN,
                    width_in=half_width,
                    height_in=PREMIUM_2_625X1_LABEL_HEIGHT_IN,
                )
            )
        pages.append(page_cells)
    return pages


def _draw_premium_2_625x1_cut_lines(pdf: FPDF) -> None:
    """Draw only the center cut lines on the pre-cut sticker stock."""

    pdf.set_draw_color(130, 130, 130)
    pdf.set_line_width(0.003)
    half_width = PREMIUM_2_625X1_LABEL_WIDTH_IN / 2
    for row in range(PREMIUM_2_625X1_ROWS):
        y = PREMIUM_2_625X1_TOP_IN + row * PREMIUM_2_625X1_ROW_PITCH_IN
        for column in range(PREMIUM_2_625X1_COLUMNS):
            x = PREMIUM_2_625X1_LEFT_IN + column * PREMIUM_2_625X1_COLUMN_PITCH_IN + half_width
            pdf.line(x, y, x, y + PREMIUM_2_625X1_LABEL_HEIGHT_IN)


def _draw_premium_split_label_text(pdf: FPDF, cell: WireLabelCell, config: LabelConfig) -> None:
    """Draw a split-stock label rotated so the text fits inside the 1 inch side."""

    center_x = cell.x_in + cell.width_in / 2
    center_y = cell.y_in + cell.height_in / 2
    virtual_width = cell.height_in
    virtual_height = cell.width_in
    clearance = _text_clearance_in(config)
    tail = min(config.tail_length, max(0.0, virtual_height - 0.15))
    stripe_weight = len(config.whitespace) + 1 + sum(config.whitespace)
    available_width = max(0.05, virtual_width - config.left_margin - config.right_margin)
    available_height = max(0.05, virtual_height - tail - 2 * clearance - PREMIUM_2_625X1_TEXT_LEADING_IN)
    font_height = _fit_font_height(pdf, cell.text, config, available_width, available_height, stripe_weight)
    x0 = center_x - virtual_width / 2
    y0 = center_y - virtual_height / 2
    text_center_x = x0 + virtual_width / 2
    y = y0 + clearance + PREMIUM_2_625X1_TEXT_LEADING_IN

    with pdf.rotation(90, x=center_x, y=center_y):
        for index in range(len(config.whitespace) + 1):
            baseline_y = y + font_height * 0.82
            pdf.text(text_center_x - pdf.get_string_width(cell.text) / 2, baseline_y, cell.text)
            y += font_height
            if index < len(config.whitespace):
                y += config.whitespace[index] * font_height


def _fit_font_height(
    pdf: FPDF,
    text: str,
    config: LabelConfig,
    available_width: float,
    available_height: float,
    stripe_weight: float,
) -> float:
    """Return a font height that fits both the text line and all stripes."""

    base_height = _font_height_in(config)
    _set_font_size_in(pdf, config, base_height)
    measured_width = max(pdf.get_string_width(text), 0.001)
    width_fit = base_height * min(1.0, available_width / measured_width)
    height_fit = available_height / max(stripe_weight, 1.0)
    fitted = max(3.5 / PT_PER_IN, min(base_height, width_fit, height_fit))
    _set_font_size_in(pdf, config, fitted)
    return fitted


def _set_font_size_in(pdf: FPDF, config: LabelConfig, font_height_in: float) -> None:
    family = _style_value(config, "font-family") or config.font_face
    weight = (_style_value(config, "font-weight") or "").lower()
    style = "B" if weight in {"bold", "700", "800", "900"} else ""
    pdf.set_font(family, style, font_height_in * PT_PER_IN)


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
