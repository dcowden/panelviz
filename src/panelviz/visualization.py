"""Component visualization primitives."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from panelviz.components import Component, PinSide, TerminalBlock
from panelviz.parser import NetStyle, UnitsConfig, VisualizationConfig, WiringMode
from panelviz.routing import RoutedWire, WireRouter


POINTS_PER_INCH = 72.0
MM_PER_INCH = 25.4


class TextMeasurer(Protocol):
    """Measures text in points for a given font size."""

    def width(self, text: str, font_size_pt: float, font_family: str) -> float:
        """Return text width in points."""

    def height(self, text: str, font_size_pt: float, font_family: str) -> float:
        """Return text height in points."""


class ApproximateTextMeasurer:
    """Portable fallback text measurer.

    The renderer accepts any real font measurer, but tests and bare environments
    need a deterministic fallback.
    """

    def width(self, text: str, font_size_pt: float, font_family: str) -> float:
        del font_family
        return len(text) * font_size_pt * 0.58

    def height(self, text: str, font_size_pt: float, font_family: str) -> float:
        del text, font_family
        return font_size_pt * 1.2


class TkTextMeasurer:
    """Measure text through Tk's font machinery when available."""

    def __init__(self) -> None:
        import tkinter as tk
        import tkinter.font as tkfont

        self._root = tk.Tk()
        self._root.withdraw()
        self._tkfont = tkfont

    def width(self, text: str, font_size_pt: float, font_family: str) -> float:
        font = self._tkfont.Font(root=self._root, family=font_family, size=max(1, round(font_size_pt)))
        return float(font.measure(text))

    def height(self, text: str, font_size_pt: float, font_family: str) -> float:
        font = self._tkfont.Font(root=self._root, family=font_family, size=max(1, round(font_size_pt)))
        return float(font.metrics("linespace"))


class FontConfig(BaseModel):
    """Global typography guardrails for visual output."""

    family: str = "Arial"
    min_pin_size: float = 6.0
    max_pin_size: float = 10.0
    min_component_name_size: float = 7.0
    max_component_name_size: float = 14.0


class ComponentVisualConfig(BaseModel):
    """Sizing constants for component SVG layout."""

    font: FontConfig = Field(default_factory=FontConfig)
    margin_pt: float = 12.0
    pin_padding_x_pt: float = 3.0
    pin_padding_y_pt: float = 2.0
    pin_band_fraction: float = 0.22
    min_pin_band_pt: float = 22.0
    max_pin_band_pt: float = 32.0
    min_component_center_width_pt: float = 72.0
    min_component_center_height_pt: float = 32.0
    min_terminal_pin_band_pt: float = 28.0
    min_terminal_center_width_pt: float = 96.0
    min_terminal_row_height_pt: float = 16.0
    component_gap_pt: float = 28.0
    wire_label_font_size_pt: float = 7.0
    wire_stroke_width_pt: float = 1.0
    wire_stub_pt: float = 20.0
    wire_lane_spacing_pt: float = 3.0
    wire_endpoint_radius_pt: float = 2.2
    wire_label_gap_pt: float = 6.0
    wiring_label_margin_pt: float = 96.0


class TypographyPlan(BaseModel):
    """Font sizes shared by rendered components."""

    pin_font_size_pt: float
    component_name_font_size_pt: float
    pin_font_fits: bool = True
    component_name_font_fits: bool = True


class PinBox(BaseModel):
    """A rectangular area for one pin label."""

    pin: str
    side: PinSide
    x: float
    y: float
    width: float
    height: float


class ComponentLayout(BaseModel):
    """Computed SVG layout for a component."""

    component_name: str
    component_type: str
    width_pt: float
    height_pt: float
    margin_pt: float
    pin_boxes: list[PinBox]
    center_x: float
    center_y: float
    center_width: float
    center_height: float
    typography: TypographyPlan


class ComponentSheetLayout(BaseModel):
    """Computed SVG layout for a sheet of components."""

    layouts: list[ComponentLayout]
    positions: dict[str, tuple[float, float]]
    width_pt: float
    height_pt: float
    typography: TypographyPlan


def default_text_measurer() -> TextMeasurer:
    """Return the best available text measurer."""

    try:
        return TkTextMeasurer()
    except Exception:
        return ApproximateTextMeasurer()


def length_to_points(value: float, units: UnitsConfig) -> float:
    """Convert a length to points."""

    if units.length == "in":
        return value * POINTS_PER_INCH
    if units.length == "mm":
        return value / MM_PER_INCH * POINTS_PER_INCH
    raise ValueError(f"Unsupported length unit: {units.length}")


def plan_typography(
    components: list[Component],
    units: UnitsConfig,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
) -> TypographyPlan:
    """Choose shared font sizes that fit all provided components."""

    visual_config = config or ComponentVisualConfig()
    text_measurer = measurer or default_text_measurer()
    pin_limits: list[float] = []
    name_limits: list[float] = []

    for component in components:
        metrics = _component_metrics(component, units, visual_config)
        visual_pins = _visual_pins_by_side(component)
        for side in PinSide:
            pins = visual_pins.get(side, [])
            if not pins:
                continue
            box_width, box_height = _pin_box_size_for_side(side, len(pins), metrics)
            pin_limits.extend(
                _max_font_size_for_text(
                    pin,
                    box_width,
                    box_height,
                    visual_config,
                    text_measurer,
                )
                for pin in pins
            )
        name_limits.append(
            _max_text_font_size(
                component.name,
                metrics.center_width,
                metrics.center_height,
                visual_config.font.family,
                visual_config.pin_padding_x_pt,
                visual_config.pin_padding_y_pt,
                visual_config.font.max_component_name_size,
                text_measurer,
            )
        )

    raw_pin_size = min(pin_limits, default=visual_config.font.max_pin_size)
    raw_name_size = min(name_limits, default=visual_config.font.max_component_name_size)
    pin_size = min(raw_pin_size, visual_config.font.max_pin_size)
    name_size = min(raw_name_size, visual_config.font.max_component_name_size)
    return TypographyPlan(
        pin_font_size_pt=max(pin_size, visual_config.font.min_pin_size),
        component_name_font_size_pt=max(name_size, visual_config.font.min_component_name_size),
        pin_font_fits=raw_pin_size >= visual_config.font.min_pin_size,
        component_name_font_fits=raw_name_size >= visual_config.font.min_component_name_size,
    )


def plan_component_layout(
    component: Component,
    units: UnitsConfig,
    typography: TypographyPlan,
    config: ComponentVisualConfig | None = None,
) -> ComponentLayout:
    """Compute SVG rectangles for a single component."""

    visual_config = config or ComponentVisualConfig()
    metrics = _component_metrics(component, units, visual_config)
    visual_pins = _visual_pins_by_side(component)
    pin_boxes: list[PinBox] = []

    for side in PinSide:
        pins = visual_pins.get(side, [])
        if not pins:
            continue
        box_width, box_height = _pin_box_size_for_side(side, len(pins), metrics)
        for index, pin in enumerate(pins):
            pin_boxes.append(_pin_box(side, pin, index, box_width, box_height, metrics))

    return ComponentLayout(
        component_name=component.name,
        component_type=component.type.value,
        width_pt=metrics.width,
        height_pt=metrics.height,
        margin_pt=visual_config.margin_pt,
        pin_boxes=pin_boxes,
        center_x=metrics.left_band,
        center_y=metrics.top_band,
        center_width=metrics.center_width,
        center_height=metrics.center_height,
        typography=typography,
    )


def render_component_svg(
    component: Component,
    all_components: list[Component] | None = None,
    units: UnitsConfig | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
) -> str:
    """Render one component as a standalone SVG."""

    render_units = units or UnitsConfig()
    visual_config = config or ComponentVisualConfig()
    typography = plan_typography(all_components or [component], render_units, visual_config, measurer)
    layout = plan_component_layout(component, render_units, typography, visual_config)
    return svg_from_layout(layout, visual_config)


def write_component_svg(
    component: Component,
    path: str | Path,
    all_components: list[Component] | None = None,
    units: UnitsConfig | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
) -> Path:
    """Write one component SVG to disk."""

    output_path = Path(path)
    output_path.write_text(
        render_component_svg(component, all_components, units, config, measurer),
        encoding="utf-8",
    )
    return output_path


def plan_component_sheet_layout(
    components: list[Component],
    units: UnitsConfig,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
) -> ComponentSheetLayout:
    """Compute a simple grid layout for multiple components."""

    if not components:
        raise ValueError("At least one component is required")

    visual_config = config or ComponentVisualConfig()
    typography = plan_typography(components, units, visual_config, measurer)
    layouts = [plan_component_layout(component, units, typography, visual_config) for component in components]
    column_count = _auto_column_count(len(layouts)) if columns is None else columns
    if column_count < 1:
        raise ValueError("columns must be positive")

    row_widths: list[float] = []
    row_heights: list[float] = []
    for row_start in range(0, len(layouts), column_count):
        row = layouts[row_start : row_start + column_count]
        row_widths.append(sum(_outer_width(layout) for layout in row) + visual_config.component_gap_pt * (len(row) - 1))
        row_heights.append(max(_outer_height(layout) for layout in row))

    sheet_width = max(row_widths)
    sheet_height = sum(row_heights) + visual_config.component_gap_pt * (len(row_heights) - 1)
    positions: dict[str, tuple[float, float]] = {}
    y = 0.0
    for row_index, row_start in enumerate(range(0, len(layouts), column_count)):
        row = layouts[row_start : row_start + column_count]
        x = 0.0
        for layout in row:
            positions[layout.component_name] = (x, y)
            x += _outer_width(layout) + visual_config.component_gap_pt
        y += row_heights[row_index] + visual_config.component_gap_pt

    return ComponentSheetLayout(
        layouts=layouts,
        positions=positions,
        width_pt=sheet_width,
        height_pt=sheet_height,
        typography=typography,
    )


def render_components_svg(
    components: list[Component],
    units: UnitsConfig | None = None,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
) -> str:
    """Render multiple components as one standalone SVG sheet."""

    render_units = units or UnitsConfig()
    visual_config = config or ComponentVisualConfig()
    sheet = plan_component_sheet_layout(components, render_units, columns, visual_config, measurer)
    return svg_from_sheet_layout(sheet, visual_config)


def write_components_svg(
    components: list[Component],
    path: str | Path,
    units: UnitsConfig | None = None,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
) -> Path:
    """Write a multi-component SVG sheet to disk."""

    output_path = Path(path)
    output_path.write_text(
        render_components_svg(components, units, columns, config, measurer),
        encoding="utf-8",
    )
    return output_path


def render_wiring_diagram_svg(
    router: WireRouter,
    units: UnitsConfig | None = None,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
    wiring_mode: WiringMode | None = None,
) -> str:
    """Render components plus routed, labeled physical wires."""

    render_units = units or UnitsConfig()
    visual_config = config or ComponentVisualConfig()
    mode = wiring_mode or router.wiring_mode
    visual_config = _config_for_wiring_mode(router, visual_config, mode)
    components = list(router.components.values())
    sheet = plan_component_sheet_layout(components, render_units, columns, visual_config, measurer)
    return svg_from_wiring_layout(sheet, router, visual_config, wiring_mode=mode)


def write_wiring_diagram_svg(
    router: WireRouter,
    path: str | Path,
    units: UnitsConfig | None = None,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
    measurer: TextMeasurer | None = None,
    wiring_mode: WiringMode | None = None,
) -> Path:
    """Write a full routed wiring SVG diagram to disk."""

    output_path = Path(path)
    output_path.write_text(
        render_wiring_diagram_svg(router, units, columns, config, measurer, wiring_mode),
        encoding="utf-8",
    )
    return output_path


def svg_from_layout(layout: ComponentLayout, config: ComponentVisualConfig | None = None) -> str:
    """Render an SVG from an already computed layout."""

    visual_config = config or ComponentVisualConfig()
    total_width = layout.width_pt + layout.margin_pt * 2
    total_height = layout.height_pt + layout.margin_pt * 2
    body: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width:.2f}pt" height="{total_height:.2f}pt" '
        f'viewBox="0 0 {total_width:.2f} {total_height:.2f}" role="img" '
        f'aria-label="{escape(layout.component_name)} component">',
        _svg_style(),
        f'<rect class="sheet-background" x="0" y="0" width="{total_width:.2f}" height="{total_height:.2f}"/>',
        *_component_svg_body(layout, 0.0, 0.0),
        "</svg>",
    ]
    return "\n".join(body)


def svg_from_sheet_layout(sheet: ComponentSheetLayout, config: ComponentVisualConfig | None = None) -> str:
    """Render a multi-component SVG from a computed sheet layout."""

    visual_config = config or ComponentVisualConfig()
    total_width = sheet.width_pt + visual_config.margin_pt * 2
    total_height = sheet.height_pt + visual_config.margin_pt * 2
    body: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width:.2f}pt" height="{total_height:.2f}pt" '
        f'viewBox="0 0 {total_width:.2f} {total_height:.2f}" role="img" '
        'aria-label="PanelViz component sheet">',
        _svg_style(),
        f'<rect class="sheet-background" x="0" y="0" width="{total_width:.2f}" height="{total_height:.2f}"/>',
    ]

    for layout in sheet.layouts:
        x, y = sheet.positions[layout.component_name]
        body.append(f'<g class="component" data-component="{escape(layout.component_name)}">')
        body.extend(_component_svg_body(layout, x + visual_config.margin_pt, y + visual_config.margin_pt))
        body.append("</g>")

    body.append("</svg>")
    return "\n".join(body)


def svg_from_wiring_layout(
    sheet: ComponentSheetLayout,
    router: WireRouter,
    config: ComponentVisualConfig | None = None,
    wiring_mode: WiringMode | None = None,
) -> str:
    """Render a routed wiring SVG from a computed component sheet layout."""

    visual_config = config or ComponentVisualConfig()
    mode = wiring_mode or router.wiring_mode
    visual_config = _config_for_wiring_mode(router, visual_config, mode)
    canvas_margin = _wiring_canvas_margin(visual_config, mode)
    total_width = sheet.width_pt + canvas_margin * 2
    total_height = sheet.height_pt + canvas_margin * 2
    anchors = _pin_anchors(sheet, visual_config, canvas_margin)
    endpoint_slots = _endpoint_slots(router.routed_wires)
    wire_lines: list[str] = []
    wire_labels: list[str] = []
    for wire in router.routed_wires:
        line, label = _wire_svg(wire, anchors, visual_config, mode, router.visualization, endpoint_slots)
        wire_lines.append(line)
        wire_labels.append(label)

    body: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width:.2f}pt" height="{total_height:.2f}pt" '
        f'viewBox="0 0 {total_width:.2f} {total_height:.2f}" role="img" '
        'aria-label="PanelViz wiring diagram">',
        _svg_style(),
        f'<rect class="sheet-background" x="0" y="0" width="{total_width:.2f}" height="{total_height:.2f}"/>',
        '<g class="wires">',
        *wire_lines,
        "</g>",
    ]

    for layout in sheet.layouts:
        x, y = sheet.positions[layout.component_name]
        body.append(f'<g class="component" data-component="{escape(layout.component_name)}">')
        body.extend(_component_svg_body(layout, x + canvas_margin, y + canvas_margin))
        body.append("</g>")

    body.extend(['<g class="wire-labels">', *wire_labels, "</g>", "</svg>"])
    return "\n".join(body)


def _svg_style() -> str:
    return "\n".join(
        [
            "<style>",
            ".sheet-background{fill:#fff}",
            ".component-outline{fill:#ffffff;stroke:#334155;stroke-width:1.25}",
            ".component-center{fill:#ffffff;stroke:none}",
            ".pin-box{fill:#f8fafc;stroke:#475569;stroke-width:0.75}",
            ".pin-label,.component-name{font-family:Arial,Helvetica,sans-serif;dominant-baseline:middle;text-anchor:middle;fill:#0f172a}",
            ".component-name{font-weight:700}",
            ".component-type{font-family:Arial,Helvetica,sans-serif;dominant-baseline:middle;text-anchor:middle;fill:#64748b;font-weight:600}",
            ".wire-line{fill:none;stroke:var(--net-color,#475569);stroke-width:var(--net-weight,1.6);stroke-dasharray:var(--net-dasharray,none);stroke-linecap:round;stroke-linejoin:round;stroke-opacity:.92}",
            ".wire-endpoint{fill:var(--net-color,#475569);stroke:#fff;stroke-width:1.1}",
            ".wire-label-bg{fill:#fff;stroke:var(--net-color,#475569);stroke-width:0.75}",
            ".wire-label{font-family:Arial,Helvetica,sans-serif;dominant-baseline:middle;text-anchor:middle;fill:#0f172a;font-weight:700}",
            "</style>",
        ]
    )


def _component_svg_body(layout: ComponentLayout, offset_x: float, offset_y: float) -> list[str]:
    body: list[str] = [
        _rect(
            offset_x + layout.margin_pt,
            offset_y + layout.margin_pt,
            layout.width_pt,
            layout.height_pt,
            "component-outline",
        ),
        _rect(
            offset_x + layout.margin_pt + layout.center_x,
            offset_y + layout.margin_pt + layout.center_y,
            layout.center_width,
            layout.center_height,
            "component-center",
            fill="#ffffff",
            stroke="none",
        ),
    ]
    center_text_x = offset_x + layout.margin_pt + layout.center_x + layout.center_width / 2
    center_text_y = offset_y + layout.margin_pt + layout.center_y + layout.center_height / 2
    type_font_size = max(6.0, layout.typography.component_name_font_size_pt * 0.58)
    body.extend(
        [
            _text(
                center_text_x,
                center_text_y - type_font_size * 0.55,
                layout.component_name,
                layout.typography.component_name_font_size_pt,
                "component-name",
            ),
            _text(
                center_text_x,
                center_text_y + layout.typography.component_name_font_size_pt * 0.75,
                layout.component_type,
                type_font_size,
                "component-type",
            ),
        ]
    )

    for box in layout.pin_boxes:
        body.append(
            _rect(
                offset_x + layout.margin_pt + box.x,
                offset_y + layout.margin_pt + box.y,
                box.width,
                box.height,
                f"pin-box pin-{box.side.value}",
            )
        )
        body.append(
            _text(
                offset_x + layout.margin_pt + box.x + box.width / 2,
                offset_y + layout.margin_pt + box.y + box.height / 2,
                box.pin,
                layout.typography.pin_font_size_pt,
                f"pin-label pin-label-{box.side.value}",
            )
        )
    return body


def _outer_width(layout: ComponentLayout) -> float:
    return layout.width_pt + layout.margin_pt * 2


def _outer_height(layout: ComponentLayout) -> float:
    return layout.height_pt + layout.margin_pt * 2


def _auto_column_count(component_count: int) -> int:
    if component_count <= 4:
        return component_count
    return 3


def _wiring_canvas_margin(config: ComponentVisualConfig, wiring_mode: WiringMode) -> float:
    if wiring_mode == "labels":
        return max(config.margin_pt, config.wiring_label_margin_pt)
    return config.margin_pt


def _config_for_wiring_mode(
    router: WireRouter,
    config: ComponentVisualConfig,
    wiring_mode: WiringMode,
) -> ComponentVisualConfig:
    if wiring_mode != "labels":
        return config

    label_projection = _max_wire_label_projection(router, config)
    component_gap = max(config.component_gap_pt, label_projection * 2 + config.margin_pt * 2)
    canvas_margin = max(config.wiring_label_margin_pt, label_projection + config.margin_pt)
    return config.model_copy(
        update={
            "component_gap_pt": component_gap,
            "wiring_label_margin_pt": canvas_margin,
        }
    )


def _max_wire_label_projection(router: WireRouter, config: ComponentVisualConfig) -> float:
    max_label_width = max(
        (
            _estimated_text_width(
                wire.wire_label or f"wire-{wire.index}",
                config.wire_label_font_size_pt,
                2.5,
            )
            for wire in router.routed_wires
        ),
        default=0.0,
    )
    return config.wire_stub_pt + config.wire_label_gap_pt + max_label_width


@dataclass(frozen=True)
class _WireAnchor:
    x: float
    y: float
    side: PinSide
    component_bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class _EndpointSlot:
    index: int
    count: int


def _pin_anchors(
    sheet: ComponentSheetLayout,
    config: ComponentVisualConfig,
    canvas_margin: float | None = None,
) -> dict[str, _WireAnchor]:
    margin = config.margin_pt if canvas_margin is None else canvas_margin
    anchors: dict[str, _WireAnchor] = {}
    for layout in sheet.layouts:
        component_x, component_y = sheet.positions[layout.component_name]
        offset_x = component_x + margin + layout.margin_pt
        offset_y = component_y + margin + layout.margin_pt
        component_bounds = (
            offset_x,
            offset_y,
            offset_x + layout.width_pt,
            offset_y + layout.height_pt,
        )
        for box in layout.pin_boxes:
            x, y = _pin_anchor(box, offset_x, offset_y)
            anchors[f"{layout.component_name}.{box.pin}"] = _WireAnchor(
                x=x,
                y=y,
                side=box.side,
                component_bounds=component_bounds,
            )
    return anchors


def _pin_anchor(box: PinBox, offset_x: float, offset_y: float) -> tuple[float, float]:
    if box.side == PinSide.LEFT:
        return offset_x + box.x, offset_y + box.y + box.height / 2
    if box.side == PinSide.RIGHT:
        return offset_x + box.x + box.width, offset_y + box.y + box.height / 2
    if box.side == PinSide.TOP:
        return offset_x + box.x + box.width / 2, offset_y + box.y
    return offset_x + box.x + box.width / 2, offset_y + box.y + box.height


def _wire_svg(
    wire: RoutedWire,
    anchors: dict[str, _WireAnchor],
    config: ComponentVisualConfig,
    wiring_mode: WiringMode = "wires",
    visualization: VisualizationConfig | None = None,
    endpoint_slots: dict[tuple[int, str], _EndpointSlot] | None = None,
) -> tuple[str, str]:
    from_node = str(wire.from_pin)
    to_node = str(wire.to_pin)
    start = anchors[from_node]
    end = anchors[to_node]
    label = wire.wire_label or f"wire-{wire.index}"
    net_style = _style_for_wire(wire, visualization)
    style_attr = _net_style_attr(net_style)
    net_attr = escape(wire.net_name or "")
    if wiring_mode == "labels":
        slots = endpoint_slots or _endpoint_slots([wire])
        return _wire_label_mode_svg(
            wire,
            label,
            start,
            end,
            config,
            net_style,
            slots[(wire.index, "from")],
            slots[(wire.index, "to")],
        )

    points = _wire_route_points(start, end, wire.index, config)
    path_data = _svg_path(points)
    line = (
        f'<path class="wire-line {_net_class(wire.net_name)}" data-wire="{wire.index}" '
        f'data-net="{net_attr}" data-label="{escape(label)}" {style_attr} d="{path_data}"/>'
        "\n"
        f'<circle class="wire-endpoint {_net_class(wire.net_name)}" data-wire="{wire.index}" '
        f'data-net="{net_attr}" {style_attr} cx="{start.x:.2f}" cy="{start.y:.2f}" '
        f'r="{config.wire_endpoint_radius_pt:.2f}"/>'
        "\n"
        f'<circle class="wire-endpoint {_net_class(wire.net_name)}" data-wire="{wire.index}" '
        f'data-net="{net_attr}" {style_attr} cx="{end.x:.2f}" cy="{end.y:.2f}" '
        f'r="{config.wire_endpoint_radius_pt:.2f}"/>'
    )
    mid_x, mid_y = _path_label_point(points)
    label_width = _estimated_text_width(label, config.wire_label_font_size_pt, 2.5)
    label_height = config.wire_label_font_size_pt * 1.35
    label_svg = "\n".join(
        [
            f'<g class="wire-label-group {_net_class(wire.net_name)}" data-wire="{wire.index}" '
            f'data-net="{net_attr}" {style_attr}>',
            _rect(
                mid_x - label_width / 2,
                mid_y - label_height / 2,
                label_width,
                label_height,
                "wire-label-bg",
            ),
            _text(mid_x, mid_y, label, config.wire_label_font_size_pt, "wire-label"),
            "</g>",
        ]
    )
    return line, label_svg


def _wire_label_mode_svg(
    wire: RoutedWire,
    label: str,
    start: _WireAnchor,
    end: _WireAnchor,
    config: ComponentVisualConfig,
    net_style: NetStyle,
    start_slot: _EndpointSlot,
    end_slot: _EndpointSlot,
) -> tuple[str, str]:
    start_stub = _stub_point(start, config.wire_stub_pt, start_slot)
    end_stub = _stub_point(end, config.wire_stub_pt, end_slot)
    style_attr = _net_style_attr(net_style)
    net_class = _net_class(wire.net_name)
    net_attr = escape(wire.net_name or "")
    line = "\n".join(
        [
            f'<path class="wire-line wire-label-stub {net_class}" data-wire="{wire.index}" '
            f'data-net="{net_attr}" data-label="{escape(label)}" {style_attr} '
            f'd="{_svg_path([(start.x, start.y), start_stub])}"/>',
            f'<path class="wire-line wire-label-stub {net_class}" data-wire="{wire.index}" '
            f'data-net="{net_attr}" data-label="{escape(label)}" {style_attr} '
            f'd="{_svg_path([(end.x, end.y), end_stub])}"/>',
            f'<circle class="wire-endpoint {net_class}" data-wire="{wire.index}" '
            f'data-net="{net_attr}" {style_attr} cx="{start.x:.2f}" cy="{start.y:.2f}" '
            f'r="{config.wire_endpoint_radius_pt:.2f}"/>',
            f'<circle class="wire-endpoint {net_class}" data-wire="{wire.index}" '
            f'data-net="{net_attr}" {style_attr} cx="{end.x:.2f}" cy="{end.y:.2f}" '
            f'r="{config.wire_endpoint_radius_pt:.2f}"/>',
        ]
    )
    labels = "\n".join(
        [
            _endpoint_wire_label_svg(wire.index, label, wire.net_name, start, start_stub, config, net_style, start_slot),
            _endpoint_wire_label_svg(wire.index, label, wire.net_name, end, end_stub, config, net_style, end_slot),
        ]
    )
    return line, labels


def _endpoint_wire_label_svg(
    wire_index: int,
    label: str,
    net_name: str | None,
    anchor: _WireAnchor,
    stub: tuple[float, float],
    config: ComponentVisualConfig,
    net_style: NetStyle,
    slot: _EndpointSlot,
) -> str:
    label_width = _estimated_text_width(label, config.wire_label_font_size_pt, 2.5)
    label_height = config.wire_label_font_size_pt * 1.35
    rotate_vertical = anchor.side in {PinSide.TOP, PinSide.BOTTOM}
    rotation = 90 if rotate_vertical else 0

    if anchor.side == PinSide.LEFT:
        x = stub[0] - config.wire_label_gap_pt - label_width / 2
        y = stub[1]
    elif anchor.side == PinSide.RIGHT:
        x = stub[0] + config.wire_label_gap_pt + label_width / 2
        y = stub[1]
    elif anchor.side == PinSide.TOP:
        x = stub[0]
        y = stub[1] - config.wire_label_gap_pt - label_width / 2
    else:
        x = stub[0]
        y = stub[1] + config.wire_label_gap_pt + label_width / 2

    transform = f' transform="rotate({rotation} {x:.2f} {y:.2f})"' if rotate_vertical else ""
    style_attr = _net_style_attr(net_style)
    net_attr = escape(net_name or "")

    return "\n".join(
        [
            f'<g class="wire-label-group wire-label-end {_net_class(net_name)}" data-wire="{wire_index}" '
            f'data-net="{net_attr}" data-side="{anchor.side.value}" data-slot="{slot.index}" '
            f'data-slot-count="{slot.count}" {style_attr}{transform}>',
            _rect(
                x - label_width / 2,
                y - label_height / 2,
                label_width,
                label_height,
                "wire-label-bg",
            ),
            _text(x, y, label, config.wire_label_font_size_pt, "wire-label"),
            "</g>",
        ]
    )


def _style_for_wire(wire: RoutedWire, visualization: VisualizationConfig | None) -> NetStyle:
    style_config = visualization or VisualizationConfig()
    style = style_config.style_for_net(wire.net_name or "")
    return style.model_copy(update={"line_weight": _wire_line_weight(style.line_weight, wire.awg)})


def _wire_line_weight(base_weight: float, awg: int | None) -> float:
    if awg is None:
        return base_weight
    weight = base_weight + max(0, 20 - awg) * 0.12
    if awg <= 12:
        weight *= 2
    return max(base_weight, weight)


def _endpoint_slots(wires: list[RoutedWire]) -> dict[tuple[int, str], _EndpointSlot]:
    endpoints = []
    for wire in wires:
        endpoints.append(((wire.index, "from"), str(wire.from_pin)))
        endpoints.append(((wire.index, "to"), str(wire.to_pin)))

    counts = Counter(node for _, node in endpoints)
    seen: defaultdict[str, int] = defaultdict(int)
    slots: dict[tuple[int, str], _EndpointSlot] = {}
    for key, node in endpoints:
        slots[key] = _EndpointSlot(index=seen[node], count=counts[node])
        seen[node] += 1
    return slots


def _net_style_attr(style: NetStyle) -> str:
    return (
        'style="'
        f"--net-color:{escape(style.color)};"
        f"--net-weight:{style.line_weight:.2f};"
        f"--net-dasharray:{_dasharray(style.line_style)}"
        '"'
    )


def _dasharray(line_style: str) -> str:
    if line_style == "dashed":
        return "6 4"
    if line_style == "dotted":
        return "1 4"
    return "none"


def _net_class(net_name: str | None) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in (net_name or "default")).strip("-")
    return f"net-{safe or 'default'}"


def _wire_route_points(
    start: _WireAnchor,
    end: _WireAnchor,
    wire_index: int,
    config: ComponentVisualConfig,
) -> list[tuple[float, float]]:
    start_stub = _stub_point(start, config.wire_stub_pt)
    end_stub = _stub_point(end, config.wire_stub_pt)
    lane_offset = ((wire_index - 1) % 6) * config.wire_lane_spacing_pt
    clearance = config.wire_stub_pt + lane_offset
    horizontal_start = start.side in {PinSide.LEFT, PinSide.RIGHT}
    horizontal_end = end.side in {PinSide.LEFT, PinSide.RIGHT}

    if horizontal_start and horizontal_end:
        route_x = _outside_x(start, end, clearance)
        route = [start_stub, (route_x, start_stub[1]), (route_x, end_stub[1]), end_stub]
    elif not horizontal_start and not horizontal_end:
        route_y = _outside_y(start, end, clearance)
        route = [start_stub, (start_stub[0], route_y), (end_stub[0], route_y), end_stub]
    elif horizontal_start:
        route = [start_stub, (start_stub[0], end_stub[1]), end_stub]
    else:
        route = [start_stub, (end_stub[0], start_stub[1]), end_stub]

    return _dedupe_points([(start.x, start.y), *route, (end.x, end.y)])


def _stub_point(anchor: _WireAnchor, distance: float, slot: _EndpointSlot | None = None) -> tuple[float, float]:
    dx, dy = _side_vector(anchor.side)
    fan_x, fan_y = _fan_offset(anchor.side, slot, 20.0)
    return anchor.x + dx * distance + fan_x, anchor.y + dy * distance + fan_y


def _side_vector(side: PinSide) -> tuple[float, float]:
    if side == PinSide.LEFT:
        return -1.0, 0.0
    if side == PinSide.RIGHT:
        return 1.0, 0.0
    if side == PinSide.TOP:
        return 0.0, -1.0
    return 0.0, 1.0


def _fan_offset(side: PinSide, slot: _EndpointSlot | None, spacing: float) -> tuple[float, float]:
    if slot is None or slot.count <= 1:
        return 0.0, 0.0
    offset = (slot.index - (slot.count - 1) / 2) * spacing
    if side in {PinSide.LEFT, PinSide.RIGHT}:
        return 0.0, offset
    return offset, 0.0


def _outside_x(start: _WireAnchor, end: _WireAnchor, clearance: float) -> float:
    left = min(start.component_bounds[0], end.component_bounds[0]) - clearance
    right = max(start.component_bounds[2], end.component_bounds[2]) + clearance
    prefer_left = start.side == PinSide.LEFT or end.side == PinSide.LEFT
    prefer_right = start.side == PinSide.RIGHT or end.side == PinSide.RIGHT
    if prefer_left and not prefer_right:
        return left
    if prefer_right and not prefer_left:
        return right
    left_distance = abs(start.x - left) + abs(end.x - left)
    right_distance = abs(start.x - right) + abs(end.x - right)
    return left if left_distance <= right_distance else right


def _outside_y(start: _WireAnchor, end: _WireAnchor, clearance: float) -> float:
    top = min(start.component_bounds[1], end.component_bounds[1]) - clearance
    bottom = max(start.component_bounds[3], end.component_bounds[3]) + clearance
    prefer_top = start.side == PinSide.TOP or end.side == PinSide.TOP
    prefer_bottom = start.side == PinSide.BOTTOM or end.side == PinSide.BOTTOM
    if prefer_top and not prefer_bottom:
        return top
    if prefer_bottom and not prefer_top:
        return bottom
    top_distance = abs(start.y - top) + abs(end.y - top)
    bottom_distance = abs(start.y - bottom) + abs(end.y - bottom)
    return top if top_distance <= bottom_distance else bottom


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    deduped: list[tuple[float, float]] = []
    for point in points:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    return deduped


def _svg_path(points: list[tuple[float, float]]) -> str:
    first, *rest = points
    pieces = [f"M {first[0]:.2f} {first[1]:.2f}"]
    pieces.extend(f"L {x:.2f} {y:.2f}" for x, y in rest)
    return " ".join(pieces)


def _path_label_point(points: list[tuple[float, float]]) -> tuple[float, float]:
    if len(points) < 2:
        return points[0]

    segments = [
        (start, end, abs(end[0] - start[0]) + abs(end[1] - start[1]))
        for start, end in zip(points, points[1:])
    ]
    longest_start, longest_end, _ = max(segments, key=lambda segment: segment[2])
    return (longest_start[0] + longest_end[0]) / 2, (longest_start[1] + longest_end[1]) / 2


@dataclass(frozen=True)
class _ComponentMetrics:
    width: float
    height: float
    top_band: float
    bottom_band: float
    left_band: float
    right_band: float
    center_width: float
    center_height: float


def _component_metrics(
    component: Component,
    units: UnitsConfig,
    config: ComponentVisualConfig,
) -> _ComponentMetrics:
    if component.size is None:
        raise ValueError(f"Component {component.name!r} must define size before visualization")

    width = length_to_points(component.size.width, units)
    height = length_to_points(component.size.height, units)
    if isinstance(component, TerminalBlock):
        height *= component.position_count()

    visual_pins = _visual_pins_by_side(component)
    vertical_pin_count = max(len(visual_pins.get(PinSide.LEFT, [])), len(visual_pins.get(PinSide.RIGHT, [])))
    horizontal_pin_count = max(len(visual_pins.get(PinSide.TOP, [])), len(visual_pins.get(PinSide.BOTTOM, [])))
    min_pin_box_height = config.font.min_pin_size * 1.2 + config.pin_padding_y_pt * 2
    min_pin_box_width = config.font.min_pin_size * 2.8 + config.pin_padding_x_pt * 2
    if vertical_pin_count:
        height = max(height, vertical_pin_count * min_pin_box_height)
        if isinstance(component, TerminalBlock):
            height = max(height, vertical_pin_count * config.min_terminal_row_height_pt)
    if horizontal_pin_count:
        width = max(width, horizontal_pin_count * min_pin_box_width)

    terminal = isinstance(component, TerminalBlock)
    top_band = _band_depth(height, config, terminal) if component.pins.get(PinSide.TOP) else 0.0
    bottom_band = _band_depth(height, config, terminal) if component.pins.get(PinSide.BOTTOM) else 0.0
    left_band = _band_depth(width, config, terminal) if component.pins.get(PinSide.LEFT) else 0.0
    right_band = _band_depth(width, config, terminal) if component.pins.get(PinSide.RIGHT) else 0.0

    name_min_width = _estimated_text_width(
        component.name,
        config.font.max_component_name_size,
        config.pin_padding_x_pt,
    )
    min_center_width = config.min_terminal_center_width_pt if terminal else config.min_component_center_width_pt
    horizontal_pin_width = horizontal_pin_count * min_pin_box_width if horizontal_pin_count else 0.0
    vertical_pin_height = vertical_pin_count * (
        config.min_terminal_row_height_pt if terminal else min_pin_box_height
    )
    center_width = max(width - left_band - right_band, min_center_width, name_min_width, horizontal_pin_width)
    center_height = max(height - top_band - bottom_band, config.min_component_center_height_pt, vertical_pin_height)
    width = max(width, left_band + center_width + right_band)
    height = max(height, top_band + center_height + bottom_band)
    return _ComponentMetrics(
        width=width,
        height=height,
        top_band=top_band,
        bottom_band=bottom_band,
        left_band=left_band,
        right_band=right_band,
        center_width=center_width,
        center_height=center_height,
    )


def _visual_pins_by_side(component: Component) -> dict[PinSide, list[str]]:
    if not isinstance(component, TerminalBlock):
        return {side: list(component.pins.get(side, [])) for side in PinSide}

    visual_pins: dict[PinSide, list[str]] = {}
    for side in PinSide:
        base_pins = component.pins.get(side, [])
        visual_pins[side] = [
            f"{position}{pin}"
            for position in range(1, component.position_count() + 1)
            for pin in base_pins
        ]
    return visual_pins


def _band_depth(total: float, config: ComponentVisualConfig, terminal: bool = False) -> float:
    min_band = config.min_terminal_pin_band_pt if terminal else config.min_pin_band_pt
    return min(max(total * config.pin_band_fraction, min_band), config.max_pin_band_pt)


def _estimated_text_width(text: str, font_size_pt: float, padding_x: float) -> float:
    return len(text) * font_size_pt * 0.62 + padding_x * 2


def _pin_box_size_for_side(side: PinSide, count: int, metrics: _ComponentMetrics) -> tuple[float, float]:
    if side in {PinSide.TOP, PinSide.BOTTOM}:
        return metrics.center_width / count, metrics.top_band if side == PinSide.TOP else metrics.bottom_band
    return metrics.left_band if side == PinSide.LEFT else metrics.right_band, metrics.center_height / count


def _pin_box(
    side: PinSide,
    pin: str,
    index: int,
    box_width: float,
    box_height: float,
    metrics: _ComponentMetrics,
) -> PinBox:
    if side == PinSide.TOP:
        return PinBox(
            pin=pin,
            side=side,
            x=metrics.left_band + index * box_width,
            y=0.0,
            width=box_width,
            height=box_height,
        )
    if side == PinSide.BOTTOM:
        return PinBox(
            pin=pin,
            side=side,
            x=metrics.left_band + index * box_width,
            y=metrics.height - box_height,
            width=box_width,
            height=box_height,
        )
    if side == PinSide.LEFT:
        return PinBox(
            pin=pin,
            side=side,
            x=0.0,
            y=metrics.top_band + index * box_height,
            width=box_width,
            height=box_height,
        )
    return PinBox(
        pin=pin,
        side=side,
        x=metrics.width - box_width,
        y=metrics.top_band + index * box_height,
        width=box_width,
        height=box_height,
    )


def _max_font_size_for_text(
    text: str,
    box_width: float,
    box_height: float,
    config: ComponentVisualConfig,
    measurer: TextMeasurer,
) -> float:
    return _max_text_font_size(
        text,
        box_width,
        box_height,
        config.font.family,
        config.pin_padding_x_pt,
        config.pin_padding_y_pt,
        config.font.max_pin_size,
        measurer,
    )


def _max_text_font_size(
    text: str,
    box_width: float,
    box_height: float,
    font_family: str,
    padding_x: float,
    padding_y: float,
    max_size: float,
    measurer: TextMeasurer,
) -> float:
    low = 1.0
    high = max_size
    for _ in range(16):
        mid = (low + high) / 2
        fits_width = measurer.width(text, mid, font_family) <= max(0.0, box_width - padding_x * 2)
        fits_height = measurer.height(text, mid, font_family) <= max(0.0, box_height - padding_y * 2)
        if fits_width and fits_height:
            low = mid
        else:
            high = mid
    return low


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    class_name: str,
    fill: str | None = None,
    stroke: str | None = None,
) -> str:
    extra = ""
    if fill is not None:
        extra += f' fill="{fill}"'
    if stroke is not None:
        extra += f' stroke="{stroke}"'
    return (
        f'<rect class="{class_name}" x="{x:.2f}" y="{y:.2f}" '
        f'width="{width:.2f}" height="{height:.2f}"{extra}/>'
    )


def _text(x: float, y: float, value: str, font_size: float, class_name: str) -> str:
    return (
        f'<text class="{class_name}" x="{x:.2f}" y="{y:.2f}" '
        f'font-size="{font_size:.2f}pt">{escape(value)}</text>'
    )
