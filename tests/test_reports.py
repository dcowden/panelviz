from pathlib import Path

from panelviz.parser import parse_panel_yaml
from panelviz.reports import (
    component_summary_rows,
    component_summary_table,
    write_component_summary_csv,
    write_wire_list_csv,
)
from panelviz.routing import WireRouter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


def test_component_summary_rows_report_unconnected_nc_and_multi_connected_pins():
    parsed = parse_panel_yaml((PROJECT_ROOT / "mycnc.yml").read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)

    rows = {row.component: row for row in component_summary_rows(router)}

    assert rows["contactor_110"].unconnected_pins == "L1, 13, T1, 14"
    assert rows["contactor_110"].multi_connected_pins == "A1 (2), A2 (2)"
    assert rows["contactor_110"].warnings == "4 unconnected; 2 multi-connected"
    assert rows["estop_relay"].no_connects == "NC"
    assert rows["estop_relay"].warnings == "3 unconnected"
    assert rows["transformer"].warnings == "-"


def test_component_summary_table_is_pretty_printed():
    parsed = parse_panel_yaml((PROJECT_ROOT / "mycnc.yml").read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)

    table = component_summary_table(router)

    assert "component" in table
    assert "multi_connected_pins" in table
    assert "contactor_110" in table


def test_report_csv_writers_write_expected_files():
    parsed = parse_panel_yaml((PROJECT_ROOT / "mycnc.yml").read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    TEST_OUTPUTS.mkdir(exist_ok=True)
    wire_csv = TEST_OUTPUTS / "wire_list_from_report_test.csv"
    summary_csv = TEST_OUTPUTS / "component_summary_from_report_test.csv"

    assert write_wire_list_csv(router, wire_csv) == wire_csv
    assert write_component_summary_csv(router, summary_csv) == summary_csv

    assert wire_csv.read_text(encoding="utf-8").splitlines()[0] == (
        "wirenumber,from_component,from_pin,to_component,to_pin,netname,awg"
    )
    assert summary_csv.read_text(encoding="utf-8").splitlines()[0] == (
        "component,type,pins,unconnected_pins,no_connects,multi_connected_pins,warnings"
    )
