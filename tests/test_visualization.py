import re
from pathlib import Path

import pytest

from panelviz.components import Connector, PowerSupply, TerminalBlock
from panelviz.parser import UnitsConfig, VisualizationConfig
from panelviz.routing import WireRouter
from panelviz.visualization import (
    ApproximateTextMeasurer,
    ComponentVisualConfig,
    WireLabelSizeCalculator,
    length_to_points,
    component_visual_config_from_visualization,
    plan_component_layout,
    plan_component_sheet_layout,
    plan_typography,
    render_component_svg,
    render_components_svg,
    render_wiring_diagram_svg,
    write_component_svg,
    write_components_svg,
    write_wiring_diagram_svg,
)


TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


def output_path(filename: str) -> Path:
    TEST_OUTPUTS.mkdir(exist_ok=True)
    return TEST_OUTPUTS / filename


def test_wire_label_font_scales_to_fit_terminal_width():
    small = component_visual_config_from_visualization(VisualizationConfig(terminal_width=0.1))
    large = component_visual_config_from_visualization(VisualizationConfig(terminal_width=0.25))

    assert small.wire_label_font_size_pt * 1.35 <= small.terminal_width_pt
    assert large.wire_label_font_size_pt * 1.35 <= large.terminal_width_pt
    assert large.wire_label_font_size_pt > small.wire_label_font_size_pt


def test_wire_label_size_calculator_uses_endpoint_terminal_width():
    calculator = WireLabelSizeCalculator()

    small = calculator.for_label("earth-1", 7.2)
    large = calculator.for_label("earth-1", 18.0)

    assert small.height_pt == pytest.approx(7.2)
    assert large.height_pt == pytest.approx(18.0)
    assert small.font_size_pt * calculator.line_height <= small.height_pt
    assert large.font_size_pt * calculator.line_height <= large.height_pt
    assert large.font_size_pt > small.font_size_pt
    assert large.corner_radius_pt < large.height_pt / 2
    assert large.corner_radius_pt <= calculator.max_corner_radius_pt


def test_length_to_points_supports_inches_and_mm():
    assert length_to_points(1, UnitsConfig(length="in")) == 72
    assert round(length_to_points(25.4, UnitsConfig(length="mm")), 5) == 72

    with pytest.raises(ValueError, match="Unsupported"):
        length_to_points(1, type("Units", (), {"length": "cm"})())


def test_typography_is_global_across_components():
    compact = Connector(
        name="tiny",
        type="connector",
        size={"width": 0.6, "height": 0.4},
        pins={"bottom": ["VERY_LONG_PIN_LABEL"]},
    )
    roomy = PowerSupply(
        name="roomy",
        type="power_supply",
        size={"width": 4, "height": 2},
        pins={"bottom": ["A"]},
    )

    typography = plan_typography(
        [compact, roomy],
        UnitsConfig(length="in"),
        measurer=ApproximateTextMeasurer(),
    )
    roomy_only = plan_typography(
        [roomy],
        UnitsConfig(length="in"),
        measurer=ApproximateTextMeasurer(),
    )

    assert typography.pin_font_size_pt < roomy_only.pin_font_size_pt
    assert typography.pin_font_size_pt >= 1.5
    assert typography.pin_font_fits is False


def test_component_layout_places_pins_on_all_four_sides():
    component = Connector(
        name="io_module",
        type="connector",
        size={"width": 2, "height": 1},
        pins={
            "top": ["T1"],
            "right": ["R1"],
            "bottom": ["B1"],
            "left": ["L1"],
        },
    )
    typography = plan_typography([component], UnitsConfig(length="in"), measurer=ApproximateTextMeasurer())
    layout = plan_component_layout(component, UnitsConfig(length="in"), typography)

    boxes = {box.pin: box for box in layout.pin_boxes}
    assert boxes["T1"].y == 0
    assert boxes["T1"].x == pytest.approx(layout.center_x + (layout.center_width - boxes["T1"].width) / 2)
    assert boxes["T1"].width == ComponentVisualConfig().terminal_width_pt
    assert boxes["L1"].x == 0
    assert boxes["L1"].y == pytest.approx(layout.center_y + (layout.center_height - boxes["L1"].height) / 2)
    assert boxes["L1"].height == ComponentVisualConfig().terminal_width_pt
    assert boxes["R1"].x + boxes["R1"].width == layout.width_pt
    assert boxes["R1"].y == pytest.approx(boxes["L1"].y)
    assert boxes["B1"].y + boxes["B1"].height == layout.height_pt
    assert boxes["B1"].x == pytest.approx(boxes["T1"].x)
    assert boxes["B1"].width == ComponentVisualConfig().terminal_width_pt
    assert boxes["B1"].x + boxes["B1"].width <= boxes["R1"].x
    assert boxes["R1"].y + boxes["R1"].height <= boxes["B1"].y
    assert layout.center_width > 0
    assert layout.center_height > 0


def test_terminal_block_layout_height_scales_by_position_count():
    block = TerminalBlock(
        name="tb",
        type="terminal_block",
        size={"width": 0.25, "height": 1},
        pins={"left": ["A"], "right": ["B"]},
        nets=[{"name": "N", "positions": [1, 2, 3]}],
    )
    typography = plan_typography([block], UnitsConfig(length="in"), measurer=ApproximateTextMeasurer())
    layout = plan_component_layout(block, UnitsConfig(length="in"), typography)

    assert layout.height_pt == 216
    assert [box.pin for box in layout.pin_boxes] == ["1A", "2A", "3A", "1B", "2B", "3B"]


def test_terminal_block_layout_preserves_physical_size_even_for_narrow_blocks():
    block = TerminalBlock(
        name="tb",
        type="terminal_block",
        size={"width": 6, "height": 3},
        pins={"left": ["A"], "right": ["B"]},
        positions=4,
        nets=[{"name": "N", "positions": [1, 2, 3, 4]}],
    )
    config = ComponentVisualConfig(
        min_component_center_width_pt=80,
        min_component_center_height_pt=36,
        min_terminal_center_width_pt=80,
        min_terminal_pin_band_pt=22,
    )
    typography = plan_typography(
        [block],
        UnitsConfig(length="mm"),
        config=config,
        measurer=ApproximateTextMeasurer(),
    )
    layout = plan_component_layout(block, UnitsConfig(length="mm"), typography, config=config)

    assert layout.width_pt == pytest.approx(length_to_points(6, UnitsConfig(length="mm")))
    assert layout.height_pt == pytest.approx(length_to_points(3 * 4, UnitsConfig(length="mm")))
    assert layout.center_width == 1.0


def test_terminal_block_layout_uses_configured_physical_terminal_size():
    block = TerminalBlock(
        name="power_t",
        type="terminal_block",
        size={"width": 6, "height": 3},
        pins={"left": ["A"], "right": ["B"]},
        nets=[{"name": "N", "positions": [1, 2, 3, 4]}],
    )
    typography = plan_typography([block], UnitsConfig(length="mm"), measurer=ApproximateTextMeasurer())
    layout = plan_component_layout(block, UnitsConfig(length="mm"), typography)
    boxes = {box.pin: box for box in layout.pin_boxes}

    assert boxes["1A"].width >= ComponentVisualConfig().min_pin_band_pt
    assert boxes["1B"].width >= ComponentVisualConfig().min_pin_band_pt
    assert boxes["1A"].height >= typography.pin_font_size_pt * 1.2
    assert layout.width_pt == pytest.approx(length_to_points(6, UnitsConfig(length="mm")))
    assert layout.center_width == pytest.approx(1.0)


def test_terminal_block_layout_separates_a_and_b_side_labels():
    block = TerminalBlock(
        name="power_t",
        type="terminal_block",
        size={"width": 6, "height": 3},
        pins={"left": ["A"], "right": ["B"]},
        nets=[{"name": "N", "positions": [1, 2, 3]}],
    )
    typography = plan_typography([block], UnitsConfig(length="mm"), measurer=ApproximateTextMeasurer())
    layout = plan_component_layout(block, UnitsConfig(length="mm"), typography)
    boxes = {box.pin: box for box in layout.pin_boxes}

    assert boxes["1A"].x == 0
    terminal_depth = ComponentVisualConfig().terminal_width_pt * ComponentVisualConfig().terminal_depth_factor
    assert boxes["1A"].width == pytest.approx(terminal_depth)
    assert boxes["1B"].x == pytest.approx(layout.width_pt - boxes["1B"].width)
    assert boxes["1B"].x + boxes["1B"].width == layout.width_pt


def test_terminal_block_svg_contains_both_a_and_b_side_labels():
    block = TerminalBlock(
        name="power_t",
        type="terminal_block",
        size={"width": 6, "height": 3},
        pins={"left": ["A"], "right": ["B"]},
        nets=[{"name": "N", "positions": [1, 2]}],
    )

    svg = render_component_svg(block, units=UnitsConfig(length="mm"), measurer=ApproximateTextMeasurer())

    assert ">1A</text>" in svg
    assert ">2A</text>" in svg
    assert ">1B</text>" in svg
    assert ">2B</text>" in svg


def test_render_component_svg_contains_component_name_and_pin_labels():
    component = PowerSupply(
        name="48v",
        type="power_supply",
        size={"width": 45, "height": 90},
        pins={"bottom": ["GND", "110L", "110N", "48V0", "48V"]},
    )

    svg = render_component_svg(component, units=UnitsConfig(length="mm"), measurer=ApproximateTextMeasurer())

    assert svg.startswith("<svg")
    assert 'aria-label="48v component"' in svg
    assert ">48v</text>" in svg
    assert ">GND</text>" in svg
    assert ">48V0</text>" in svg
    assert 'class="pin-box pin-bottom"' in svg


def test_write_component_svg_writes_file():
    component = Connector(
        name="plug",
        type="connector",
        size={"width": 1, "height": 1},
        pins={"right": ["A"]},
    )
    output = output_path("plug.svg")

    written = write_component_svg(
        component,
        output,
        units=UnitsConfig(length="in"),
        measurer=ApproximateTextMeasurer(),
    )

    assert written == output
    assert output.read_text(encoding="utf-8").startswith("<svg")


def test_component_sheet_layout_places_components_in_grid():
    components = [
        Connector(name="plug", type="connector", size={"width": 1, "height": 1}, pins={"right": ["A"]}),
        PowerSupply(name="supply", type="power_supply", size={"width": 2, "height": 1}, pins={"bottom": ["GND"]}),
        Connector(name="io", type="connector", size={"width": 1, "height": 1}, pins={"left": ["I"]}),
    ]

    sheet = plan_component_sheet_layout(
        components,
        UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
    )

    assert len(sheet.layouts) == 3
    assert sheet.positions["plug"] == (0, 0)
    assert sheet.positions["supply"][0] > sheet.positions["plug"][0]
    assert sheet.positions["io"][1] > sheet.positions["plug"][1]
    assert sheet.typography.pin_font_size_pt == sheet.layouts[0].typography.pin_font_size_pt


def test_render_components_svg_contains_all_components():
    components = [
        Connector(name="plug", type="connector", size={"width": 1, "height": 1}, pins={"right": ["A"]}),
        PowerSupply(name="supply", type="power_supply", size={"width": 2, "height": 1}, pins={"bottom": ["GND"]}),
    ]

    svg = render_components_svg(
        components,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
    )

    assert 'aria-label="PanelViz component sheet"' in svg
    assert 'class="sheet-background"' in svg
    assert 'data-component="plug"' in svg
    assert 'data-component="supply"' in svg
    assert ">plug</text>" in svg
    assert ">supply</text>" in svg
    assert ">GND</text>" in svg


def test_write_components_svg_writes_file():
    components = [
        Connector(name="plug", type="connector", size={"width": 1, "height": 1}, pins={"right": ["A"]}),
    ]
    output = output_path("components.svg")

    written = write_components_svg(
        components,
        output,
        units=UnitsConfig(length="in"),
        measurer=ApproximateTextMeasurer(),
    )

    assert written == output
    assert 'PanelViz component sheet' in output.read_text(encoding="utf-8")


def test_component_sheet_requires_components_and_positive_columns():
    with pytest.raises(ValueError, match="At least one component"):
        plan_component_sheet_layout([], UnitsConfig(length="in"))

    component = Connector(name="plug", type="connector", size={"width": 1, "height": 1}, pins={"right": ["A"]})
    with pytest.raises(ValueError, match="columns must be positive"):
        plan_component_sheet_layout([component], UnitsConfig(length="in"), columns=0)


def test_render_wiring_diagram_svg_contains_labeled_wires():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        components:
          plug:
            type: connector
            size: {width: 1, height: 1}
            pins:
              right: [A]
          load:
            type: connector
            size: {width: 1, height: 1}
            pins:
              left: [B]
        connections:
          wires:
            - [plug.A, load.B]
        """
    )
    router = WireRouter.route_parse_result(parsed)

    svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
    )

    assert 'aria-label="PanelViz wiring diagram"' in svg
    assert '<path class="wire-line ' in svg
    assert '<line class="wire-line"' not in svg
    assert 'class="wire-endpoint ' in svg
    assert svg.count('class="wire-endpoint ') == 2
    assert 'data-wire="1"' in svg
    assert ">plug.A-1</text>" in svg
    assert 'data-component="plug"' in svg
    assert 'data-component="load"' in svg


def test_render_wiring_diagram_svg_label_mode_uses_endpoint_labels():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        config:
          wiring_mode: labels
        components:
          plug:
            type: connector
            size: {width: 1, height: 1}
            pins:
              right: [A]
          load:
            type: connector
            size: {width: 1, height: 1}
            pins:
              left: [B]
        connections:
          wires:
            - [plug.A, load.B]
        """
    )
    router = WireRouter.route_parse_result(parsed)

    svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
    )

    assert svg.count('class="wire-line wire-label-stub') == 2
    assert svg.count('class="wire-label-group wire-label-end') == 2
    assert 'data-side="right"' in svg
    assert 'data-side="left"' in svg
    assert ">plug.A-1</text>" in svg


def test_render_wiring_diagram_svg_uses_configured_net_styles():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        config:
          wiring_mode: labels
          visualization:
            net_styles:
              N:
                color: "#dc2626"
                line_weight: 3.5
                line_style: dashed
        components:
          plug:
            type: connector
            size: {width: 1, height: 1}
            pins:
              right: [A]
          block:
            type: terminal_block
            size: {width: 1, height: 1}
            pins:
              left: [A]
              right: [B]
            nets:
              - name: N
                positions: [1]
        connections:
          wires:
            - [plug.A, block.N]
        """
    )
    router = WireRouter.route_parse_result(parsed)

    svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
    )

    assert 'data-net="N"' in svg
    assert "--net-color:#dc2626" in svg
    assert "--net-weight:3.50" in svg
    assert "--net-dasharray:6 4" in svg


def test_render_wiring_diagram_svg_label_mode_places_label_edge_after_fixed_gap():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        config:
          wiring_mode: labels
        components:
          plug:
            type: connector
            size: {width: 1, height: 1}
            pins:
              right: [A]
          load:
            type: connector
            size: {width: 1, height: 1}
            pins:
              left: [B]
        connections:
          wires:
            - [plug.A, load.B]
        """
    )
    router = WireRouter.route_parse_result(parsed)
    config = ComponentVisualConfig(wire_stub_pt=10, wire_label_gap_pt=12)

    svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=2,
        config=config,
        measurer=ApproximateTextMeasurer(),
    )

    right_stub_match = re.search(r'd="M ([0-9.]+) ([0-9.]+) L ([0-9.]+) ([0-9.]+)"', svg)
    right_label_match = re.search(
        r'data-side="right"[^>]*>\n<rect class="wire-label-bg" x="([0-9.]+)" y="[0-9.]+" width="([0-9.]+)"',
        svg,
    )
    assert right_stub_match is not None
    assert right_label_match is not None

    stub_end_x = float(right_stub_match.group(3))
    label_left_x = float(right_label_match.group(1))
    assert label_left_x - stub_end_x == pytest.approx(config.wire_label_gap_pt, abs=0.02)


def test_render_wiring_diagram_svg_label_mode_stacks_labels_for_multi_connected_pin():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        config:
          wiring_mode: labels
        components:
          source:
            type: connector
            size: {width: 1, height: 1}
            pins:
              top: [A]
          load_one:
            type: connector
            size: {width: 1, height: 1}
            pins:
              bottom: [B]
          load_two:
            type: connector
            size: {width: 1, height: 1}
            pins:
              bottom: [C]
        connections:
          wires:
            - [source.A, load_one.B]
            - [source.A, load_two.C]
        """
    )
    router = WireRouter.route_parse_result(parsed)

    svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=3,
        measurer=ApproximateTextMeasurer(),
    )

    assert 'data-slot="0" data-slot-count="2"' in svg
    assert 'data-slot="1" data-slot-count="2"' in svg
    source_label_groups = re.findall(
        r'data-side="top" data-slot="[01]" data-slot-count="2"[^>]*transform="rotate\(90 ([0-9.]+) ([0-9.]+)\)',
        svg,
    )
    assert len(source_label_groups) == 2
    assert len({x for x, _ in source_label_groups}) == 1
    assert len({y for _, y in source_label_groups}) == 2


def test_render_wiring_diagram_svg_label_mode_expands_component_spacing_for_labels():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        config:
          wiring_mode: labels
        components:
          left_device:
            type: connector
            size: {width: 1, height: 1}
            pins:
              right: [VERY_LONG_LEFT_PIN_NAME]
          right_device:
            type: connector
            size: {width: 1, height: 1}
            pins:
              left: [VERY_LONG_RIGHT_PIN_NAME]
        connections:
          wires:
            - [left_device.VERY_LONG_LEFT_PIN_NAME, right_device.VERY_LONG_RIGHT_PIN_NAME]
        """
    )
    router = WireRouter.route_parse_result(parsed)

    wires_svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
        wiring_mode="wires",
    )
    labels_svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
        wiring_mode="labels",
    )

    wires_width = float(re.search(r'viewBox="0 0 ([0-9.]+)', wires_svg).group(1))
    labels_width = float(re.search(r'viewBox="0 0 ([0-9.]+)', labels_svg).group(1))
    assert labels_width > wires_width + 100


def test_render_wiring_diagram_svg_label_mode_rotates_top_and_bottom_labels():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        config:
          wiring_mode: labels
        components:
          top_device:
            type: connector
            size: {width: 1, height: 1}
            pins:
              bottom: [A]
          bottom_device:
            type: connector
            size: {width: 1, height: 1}
            pins:
              top: [B]
        connections:
          wires:
            - [top_device.A, bottom_device.B]
        """
    )
    router = WireRouter.route_parse_result(parsed)

    svg = render_wiring_diagram_svg(
        router,
        units=UnitsConfig(length="in"),
        columns=1,
        measurer=ApproximateTextMeasurer(),
    )

    assert re.search(r'data-side="bottom"[^>]*transform="rotate\(90 ', svg)
    assert re.search(r'data-side="top"[^>]*transform="rotate\(90 ', svg)


def test_write_wiring_diagram_svg_writes_file():
    from panelviz.parser import parse_panel_yaml

    parsed = parse_panel_yaml(
        """
        components:
          plug:
            type: connector
            size: {width: 1, height: 1}
            pins:
              right: [A]
          load:
            type: connector
            size: {width: 1, height: 1}
            pins:
              left: [B]
        connections:
          wires:
            - [plug.A, load.B]
        """
    )
    router = WireRouter.route_parse_result(parsed)
    output = output_path("wiring.svg")

    written = write_wiring_diagram_svg(
        router,
        output,
        units=UnitsConfig(length="in"),
        columns=2,
        measurer=ApproximateTextMeasurer(),
    )

    assert written == output
    assert "plug.A-1" in output.read_text(encoding="utf-8")
