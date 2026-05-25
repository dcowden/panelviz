from pathlib import Path

from panelviz.parser import parse_panel_yaml
from panelviz.reports import wire_list_rows, wire_list_table
from panelviz.routing import WireRouter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_PANEL = Path(__file__).resolve().parent / "fixtures" / "panel_valid.yml"


def test_fixture_file_routes_expected_wires_and_labels():
    parsed = parse_panel_yaml(VALID_PANEL.read_text())
    router = WireRouter.route_parse_result(parsed)

    assert parsed.config.wire_label_format == "%netname-%seq"
    assert parsed.config.wiring_mode == "labels"
    assert parsed.config.units.length == "in"
    assert parsed.config.defaults.awg == 20
    assert len(parsed.wires) == 18
    assert parsed.wires[0].net_name == "earth"
    assert parsed.wires[0].awg == 12
    assert set(parsed.no_connects) >= {"axbb-e.O1", "axbb-e.O17", "estop_relay.NC"}
    assert len(router.routed_wires) == 19
    assert router.physical_graph.number_of_edges() == 19
    assert router.no_connects >= {"axbb-e.O1", "axbb-e.O17", "estop_relay.NC"}

    wire_by_index = {wire.index: wire for wire in router.routed_wires}
    assert str(wire_by_index[2].to_pin) == "live_power_t.1A"
    assert str(wire_by_index[4].from_pin) == "live_power_t.1B"
    assert str(wire_by_index[7].from_pin) == "live_power_t.4A"
    assert str(wire_by_index[8].to_pin) == "earth.1B"
    assert str(wire_by_index[15].to_pin) == "coil_t.1A"
    assert str(wire_by_index[16].to_pin) == "coil_t.3A"
    assert str(wire_by_index[18].from_pin) == "contactor_220.L1"
    assert str(wire_by_index[18].to_pin) == "transformer.220L"

    expected_labels = {
        1: ("earth-1", "earth"),
        2: ("110L-1", "110L"),
        3: ("110N-1", "110N"),
        4: ("110L-2", "110L"),
        5: ("110N-2", "110N"),
        6: ("110L-3", "110L"),
        7: ("110N-3", "110N"),
        8: ("earth-2", "earth"),
        9: ("VFD_220L-1", "VFD_220L"),
        10: ("transformer.220N-1", "transformer.220N"),
        11: ("110L_SWITCHED-1", "110L_SWITCHED"),
        12: ("110N_SWITCHED-1", "110N_SWITCHED"),
        13: ("earth-3", "earth"),
        13: ("COIL+-1", "COIL+"),
        14: ("COIL--1", "COIL-"),
        15: ("COIL+-2", "COIL+"),
        16: ("COIL--2", "COIL-"),
        17: ("VFD_220L-2", "VFD_220L"),
        18: ("VFD_220L-3", "VFD_220L"),
        19: ("earth-3", "earth"),
    }
    assert {
        index: (wire_by_index[index].wire_label, wire_by_index[index].net_name)
        for index in expected_labels
    } == expected_labels

    edge = router.physical_graph.edges["wall_plug.1", "live_power_t.1A", 2]
    assert edge["wire_label"] == "110L-1"
    assert edge["net_name"] == "110L"
    assert edge["explicit_net_name"] == "110L"
    assert edge["awg"] == 12
    assert edge["to_auto_selected"] is True

    assert sorted(router.net_graph.nodes["110L"]["member_pins"]) == [
        "contactor_110.T2",
        "live_power_t.1A",
        "live_power_t.1B",
        "live_power_t.3A",
        "live_power_t.3B",
        "live_power_t.5A",
        "live_power_t.5B",
        "transformer.110L",
        "wall_plug.1",
    ]
    assert {"coil_t.1A", "coil_t.1B", "coil_t.2A", "coil_t.2B"} <= set(
        router.net_graph.nodes["COIL+"]["member_pins"]
    )
    axbbe_nets = {net.name for net in parsed.component("axbb-e").nets}
    assert "24V" not in axbbe_nets
    assert {"VFD REV"} <= axbbe_nets
    assert router.net_graph.nodes["VFD REV"]["member_pins"] == ["axbb-e.O2"]


def test_fixture_wire_list_report_is_grouped_by_netname():
    parsed = parse_panel_yaml(VALID_PANEL.read_text())
    router = WireRouter.route_parse_result(parsed)

    rows = wire_list_rows(router)
    assert len(rows) == 19
    assert [row.netname for row in rows] == sorted(row.netname for row in rows)
    assert rows[0].model_dump() == {
        "wirenumber": "110L-1",
        "from_component": "wall_plug",
        "from_pin": "1",
        "to_component": "live_power_t",
        "to_pin": "1A",
        "netname": "110L",
        "awg": 12,
        "tags": "field, terminals, vfd",
    }
    assert "wirenumber" in wire_list_table(router)
    assert "COIL+-1" in wire_list_table(router)
