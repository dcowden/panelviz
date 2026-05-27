import re
import zlib
from pathlib import Path

import pytest

from panelviz.parser import LabelConfig, parse_panel_yaml
from panelviz.routing import WireRouter
from panelviz.wire_labels import (
    WireLabelCalculator,
    paginate_wire_labels,
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
    assert short.height_in == pytest.approx(0.85)
    assert short.text_count == 4
    assert long.width_in >= 1.0
    assert long.width_in % 0.5 == 0


def test_wire_label_layout_adds_configured_top_and_bottom_clearance():
    config = LabelConfig(font_height=0.1, text_clearance=2, text_clearance_unit="pt", whitespace=[1])

    layout = wire_label_layout("CLEARANCE", config)

    assert layout.height_in == pytest.approx(0.3 + 4 / 72)


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
    assert [cell.y_in for cell in first_page[8:]] == pytest.approx([0.55, 0.55])
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
    assert set(first_page_column_counts.values()) == {3}


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

    assert groups == {"dc_power": ["VBUS-1"], "control": ["VBUS-1"]}


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


def test_render_wire_label_pdf_repeats_label_for_each_configured_stripe():
    config = LabelConfig(font_height=0.1, whitespace=[1, 1.5, 2])
    cells = paginate_wire_labels(["VBUS-1"], config)[0]

    pdf = render_wire_label_pdf(cells, config)
    text = _pdf_stream_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert text.count("VBUS-1") == 4


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

    assert [path.name for path in written] == ["wirelabel_row_a.pdf", "wirelabel_row_b.pdf"]
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
