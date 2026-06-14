import re
import zlib
from pathlib import Path

import pytest
from fpdf import FPDF

from panelviz.label_assignment import ComponentLabelRow
from panelviz.parser import LabelConfig, parse_panel_yaml
from panelviz.routing import WireRouter
from panelviz.wire_labels import (
    WireLabelCalculator,
    all_wire_labels,
    compact_component_map_layout,
    paginate_wire_labels,
    render_component_label_sheet_pdf,
    render_wire_label_pages_pdf,
    render_wire_label_pdf,
    wire_label_groups,
    wire_label_layout,
    write_wire_label_pdfs,
)


TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


def test_wire_label_layout_uses_margin_snap_and_whitespace_formula():
    config = LabelConfig(
        font_height=0.1,
        left_margin=0.25,
        right_margin=0.25,
        text_clearance=0,
        whitespace=[1, 1.5, 2],
    )

    short = wire_label_layout("A", config)
    long = wire_label_layout("THIS_IS_A_LONG_WIRE_NAME", config)

    assert short.width_in == 1.0
    assert short.height_in == pytest.approx(1.6)
    assert short.text_count == 4
    assert long.width_in >= 1.0
    assert long.width_in % 0.5 == 0


def test_wire_label_layout_adds_configured_top_and_bottom_clearance():
    config = LabelConfig(font_height=0.1, text_clearance=2, text_clearance_unit="pt", whitespace=[1])

    layout = wire_label_layout("CLEARANCE", config)

    assert layout.height_in == pytest.approx(0.3 + 4 / 72 + 0.75)


def test_wire_label_layout_uses_existing_measurement_pdf_and_css_style():
    config = LabelConfig(
        style={"font-size": "8pt", "font-weight": "700", "color": "not-a-color"},
        font_height=0.5,
        whitespace=[1],
    )
    pdf = FPDF(unit="pt", format="letter")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 8)

    layout = wire_label_layout("CSS-SIZED", config, pdf)
    rendered = render_wire_label_pdf(paginate_wire_labels(["CSS-SIZED"], config)[0], config)

    assert layout.font_height_in == pytest.approx(8 / 72)
    assert rendered.startswith(b"%PDF-")


def test_wire_label_tail_length_is_configurable():
    with_tail = wire_label_layout("TAIL", LabelConfig(font_height=0.1, whitespace=[1], tail_length=0.75))
    without_tail = wire_label_layout("TAIL", LabelConfig(font_height=0.1, whitespace=[1], tail_length=0))

    assert with_tail.height_in - without_tail.height_in == pytest.approx(0.75)


def test_paginate_wire_labels_returns_no_pages_for_empty_labels():
    assert paginate_wire_labels([], LabelConfig()) == []


def test_pre_cut_label_stock_places_two_labels_on_each_address_label():
    config = LabelConfig(stock="premium_2_625x1_split")

    pages = paginate_wire_labels([f"W{index}" for index in range(1, 62)], config)

    assert len(pages) == 2
    assert len(pages[0]) == 60
    assert len(pages[1]) == 1
    assert (pages[0][0].x_in, pages[0][0].y_in, pages[0][0].width_in, pages[0][0].height_in) == pytest.approx(
        (0.1875, 0.5, 1.3125, 1.0)
    )
    assert (pages[0][1].x_in, pages[0][1].y_in, pages[0][1].width_in, pages[0][1].height_in) == pytest.approx(
        (1.5, 0.5, 1.3125, 1.0)
    )
    assert (pages[0][2].x_in, pages[0][2].y_in, pages[0][2].width_in, pages[0][2].height_in) == pytest.approx(
        (2.9375, 0.5, 1.3125, 1.0)
    )
    assert (pages[0][4].x_in, pages[0][4].width_in) == pytest.approx((5.6875, 1.3125))
    for first_half in (pages[0][0], pages[0][2], pages[0][4]):
        center_line_x = first_half.x_in + first_half.width_in
        assert center_line_x - first_half.x_in == pytest.approx(1.3125)
    assert pages[0][6].x_in == pytest.approx(0.1875)
    assert pages[0][6].y_in == pytest.approx(1.5)


def test_pre_cut_label_pdf_uses_full_stock_page_and_cut_lines():
    config = LabelConfig(stock="premium_2_625x1_split", font_height=0.08, whitespace=[2])
    cells = paginate_wire_labels(["110L_SWITCHED-1", "VERY_LONG_WIRE_LABEL"], config)[0]

    pdf = render_wire_label_pdf(cells, config)
    text = _pdf_stream_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert text.count("110L_SWITCHED-1") == 2
    assert "VERY_LONG_WIRE_LABEL" in text


def test_wire_label_calculator_packs_width_columns_without_starting_each_width_on_a_new_page():
    config = LabelConfig(
        font_height=0.1,
        left_margin=0.25,
        right_margin=0.25,
        text_clearance=0,
        width_increment=0.5,
        whitespace=[1],
    )
    labels = ["A", "B", "THIS_LABEL_NEEDS_MORE_WIDTH", "C", "ANOTHER_WIDE_LABEL"]

    pages = WireLabelCalculator(config).paginate(labels)

    assert len(pages) == 1
    assert {cell.width_in for cell in pages[0]} == {1.0, 2.0, 2.5}
    assert [cell.text for cell in pages[0]] == labels
    assert {cell.y_in for cell in pages[0]} == {0.25}
    assert sorted({cell.x_in for cell in pages[0]}) == [0.25, 1.25, 2.25, 4.75, 5.75]


def test_wire_label_calculator_fills_across_before_down():
    config = LabelConfig(
        font_height=0.1,
        left_margin=0.25,
        right_margin=0.25,
        text_clearance=0,
        width_increment=0.5,
        whitespace=[1],
    )

    pages = WireLabelCalculator(config).paginate([f"W{index}" for index in range(10)])

    first_page = pages[0]
    assert [cell.text for cell in first_page[:8]] == [f"W{index}" for index in range(8)]
    assert {cell.y_in for cell in first_page[:8]} == {0.25}
    assert [cell.text for cell in first_page[8:]] == ["W8", "W9"]
    assert [cell.y_in for cell in first_page[8:]] == pytest.approx([1.3, 1.3])
    assert [cell.x_in for cell in first_page[8:]] == [0.25, 1.25]


def test_wire_label_calculator_pushes_partial_columns_to_later_pages():
    config = LabelConfig(
        font_height=0.1,
        left_margin=0.25,
        right_margin=0.25,
        text_clearance=0,
        width_increment=0.5,
        whitespace=[30],
    )
    labels = ["THIS_LABEL_NEEDS_MORE_WIDTH"] * 4 + [f"N{index}" for index in range(18)]

    pages = WireLabelCalculator(config).paginate(labels)

    first_page_column_counts: dict[float, int] = {}
    for cell in pages[0]:
        first_page_column_counts[cell.x_in] = first_page_column_counts.get(cell.x_in, 0) + 1
    assert len(pages) == 2
    assert set(first_page_column_counts.values()) == {2}


def test_paginate_wire_labels_packs_rows_and_pages():
    config = LabelConfig(font_height=0.5, whitespace=[1], page_margin=0.25)

    pages = paginate_wire_labels([f"WIRE-{index}" for index in range(1, 80)], config)

    assert len(pages) > 1
    assert pages[0][0].x_in == 0.25
    assert pages[0][0].y_in == 0.25
    assert all(cell.width_in >= 1.0 for page in pages for cell in page)


def test_wire_label_groups_duplicate_cross_tag_wires_by_endpoint_tags():
    router = _router(
        """
components:
  supply:
    type: connector
    tags: [dc_power]
    pins:
      right: [V]
  load:
    type: connector
    tags: [control]
    pins:
      left: [V]
connections:
  wires:
    - {from: supply.V, to: load.V, net: VBUS}
"""
    )

    groups = wire_label_groups(router)

    assert groups == {"dc_power": ["VBUS-1", "VBUS-1"], "control": ["VBUS-1", "VBUS-1"]}


def test_wire_label_groups_include_both_ends_when_endpoints_share_tag():
    router = _router(
        """
components:
  source:
    type: connector
    tags: [vfd]
    pins:
      right: [L]
  load:
    type: connector
    tags: [vfd]
    pins:
      left: [L]
connections:
  wires:
    - {from: source.L, to: load.L, net: 110L_SWITCHED}
"""
    )

    groups = wire_label_groups(router)

    assert groups == {"vfd": ["110L_SWITCHED-1", "110L_SWITCHED-1"]}


def test_wire_label_groups_sort_by_net_then_wire_label():
    router = _router(
        """
components:
  source:
    type: connector
    tags: [row_a]
    pins:
      right: [A, B, C]
  load:
    type: connector
    tags: [row_b]
    pins:
      left: [A, B, C]
connections:
  wires:
    - {from: source.A, to: load.A, net: BETA}
    - {from: source.B, to: load.B, net: ALPHA}
    - {from: source.C, to: load.C, net: ALPHA}
"""
    )

    groups = wire_label_groups(router)

    assert groups["row_a"] == ["ALPHA-1", "ALPHA-1", "ALPHA-2", "ALPHA-2", "BETA-1", "BETA-1"]
    assert groups["row_b"] == groups["row_a"]


def test_all_wire_labels_sort_alphabetically_and_keep_pairs_together():
    router = _router(
        """
components:
  source:
    type: connector
    tags: [row_a]
    pins:
      right: [A, B, C]
  load:
    type: connector
    tags: [row_b]
    pins:
      left: [A, B, C]
connections:
  wires:
    - {from: source.A, to: load.A, net: BETA}
    - {from: source.B, to: load.B, net: ALPHA}
    - {from: source.C, to: load.C, net: GAMMA}
"""
    )

    assert all_wire_labels(router) == ["ALPHA-1", "ALPHA-1", "BETA-1", "BETA-1", "GAMMA-1", "GAMMA-1"]


def test_render_wire_label_pdf_repeats_label_for_each_configured_stripe():
    config = LabelConfig(font_height=0.1, whitespace=[1, 1.5, 2])
    cells = paginate_wire_labels(["VBUS-1"], config)[0]

    pdf = render_wire_label_pdf(cells, config)
    text = _pdf_stream_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert text.count("VBUS-1") == 4


def test_render_wire_label_pages_pdf_keeps_multiple_label_pages_in_one_pdf():
    config = LabelConfig(stock="premium_2_625x1_split")
    pages = paginate_wire_labels([f"W{index}" for index in range(1, 62)], config)

    pdf = render_wire_label_pages_pdf(pages, config)

    assert pdf.startswith(b"%PDF-")
    assert pdf.count(b"/Type /Page") >= 2


def test_render_component_label_sheet_pdf_includes_table_and_multiple_labels():
    rows = [
        ComponentLabelRow(
            label=f"SIG-{index}",
            net="SIG",
            component="board",
            pin=f"P{index}",
            other_endpoint=f"term.{index}A",
        )
        for index in range(1, 47)
    ]

    pdf = render_component_label_sheet_pdf("board", rows, LabelConfig(font_height=0.1, whitespace=[1]))
    text = _pdf_stream_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert "board wire labels" in text
    assert "Page 1 of" in text
    assert "Page 2 of" in text
    assert "... 4 more wire ends" in text
    assert "SIG-1" in text


def test_render_component_label_sheet_pdf_draws_component_terminals_and_nets():
    rows = [
        ComponentLabelRow(label="SIG-1", net="SIGNAL", component="board", pin="A", other_endpoint="term.1A"),
        ComponentLabelRow(label="RET-1", net="RETURN", component="board", pin="B", other_endpoint="term.2A"),
    ]
    component = {
        "name": "board",
        "type": "pcb",
        "tags": ["control"],
        "width": 72,
        "height": 96,
        "center": {"x": 12, "y": 18, "width": 48, "height": 60},
        "pins": [
            {"pin": "A", "side": "left", "x": 0, "y": 20, "width": 8, "height": 12, "nets": ["SIGNAL"]},
            {"pin": "B", "side": "bottom", "x": 28, "y": 88, "width": 12, "height": 8, "nets": ["RETURN"]},
        ],
    }

    pdf = render_component_label_sheet_pdf("board", rows, LabelConfig(font_height=0.1, whitespace=[1]), component)
    text = _pdf_stream_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert "board" in text
    assert "control" in text
    assert "SIGNAL" in text
    assert "RETURN" in text


def test_component_label_map_keeps_terminal_scale_but_compacts_component_body():
    component = {
        "name": "large_physical_part",
        "type": "driver",
        "tags": ["control"],
        "width": 500,
        "height": 900,
        "pins": [
            {"pin": "L1", "side": "left", "width": 18, "height": 7.2, "nets": ["LINE"]},
            {"pin": "L2", "side": "left", "width": 18, "height": 7.2, "nets": []},
            {"pin": "T1", "side": "top", "width": 7.2, "height": 18, "nets": ["TOP"]},
            {"pin": "B1", "side": "bottom", "width": 7.2, "height": 18, "nets": []},
        ],
    }
    pdf = FPDF(unit="in", format="letter")
    pdf.add_page()

    layout = compact_component_map_layout(pdf, component, {"L2": "RETURN", "B1": "BOTTOM"})

    assert layout.width_in < 2.0
    assert layout.height_in < 2.0
    assert layout.body_height_in < component["height"] / 72
    assert {pin.pin: pin.width_in for pin in layout.pins}["L1"] == pytest.approx(18 / 72)
    assert {pin.pin: pin.height_in for pin in layout.pins}["T1"] == pytest.approx(18 / 72)
    assert {pin.pin: pin.nets for pin in layout.pins}["L2"] == ("RETURN",)
    assert {pin.pin: pin.nets for pin in layout.pins}["B1"] == ("BOTTOM",)


def test_component_label_map_uses_saved_ui_rotation_for_terminal_orientation():
    component = {
        "name": "terminal_block",
        "type": "terminal_block",
        "tags": ["terminals"],
        "rotation": 90,
        "width": 72,
        "height": 360,
        "pins": [
            {"pin": f"{index}A", "side": "left", "width": 18, "height": 7.2, "nets": []}
            for index in range(1, 9)
        ],
    }
    pdf = FPDF(unit="in", format="letter")
    pdf.add_page()

    layout = compact_component_map_layout(pdf, component)

    assert {pin.side for pin in layout.pins} == {"top"}
    assert layout.width_in > layout.height_in
    assert layout.width_in < 2.5
    assert layout.height_in < 1.0


def test_write_wire_label_pdfs_writes_one_pdf_per_tag_and_page():
    router = _router(
        """
components:
  source:
    type: connector
    tags: [row_a]
    pins:
      right: [A, B]
  load:
    type: connector
    tags: [row_b]
    pins:
      left: [A, B]
connections:
  wires:
    - {from: source.A, to: load.A, net: ALPHA}
    - {from: source.B, to: load.B, net: BETA}
"""
    )
    output_dir = TEST_OUTPUTS / "wire_labels"

    written = write_wire_label_pdfs(router, output_dir, LabelConfig())

    assert [path.name for path in written] == ["all_labels.pdf", "wirelabel_row_a.pdf", "wirelabel_row_b.pdf"]
    for path in written:
        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF-")


def _router(text: str) -> WireRouter:
    return WireRouter.route_parse_result(parse_panel_yaml(text))


def _pdf_stream_text(content: bytes) -> str:
    parts = [content]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", content, flags=re.DOTALL):
        stream = match.group(1)
        try:
            parts.append(zlib.decompress(stream))
        except zlib.error:
            parts.append(stream)
    return b"\n".join(parts).decode("latin1", errors="ignore")
