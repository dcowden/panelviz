import networkx as nx
import pytest

from panelviz.components import PinRef
from panelviz.parser import parse_panel_yaml
from panelviz.routing import RoutingError, WireRouter, allocation_snapshot, format_wire_label


ROUTING_YAML = """
components:
  wall_plug:
    type: connector
    pins:
      right: [GND, 1, 2]
  transformer:
    type: power_supply
    pins:
      bottom: [GND, 110L, 110N]
  power_t:
    type: terminal_block
    pins:
      left: [A]
      right: [B]
    nets:
      - name: 110L
        positions: [1, 3]
      - name: 110N
        positions: [2]
  earth:
    type: bus_block
    pins:
      left: [A]
      right: [B]
    positions: 2
    nets:
      - name: earth
  relay:
    type: relay
    pins:
      bottom: [NO, COM, NC]
"""


def make_router(no_connects=()) -> WireRouter:
    return WireRouter.from_parse_result(parse_panel_yaml(ROUTING_YAML), no_connects=no_connects)


def test_route_wire_adds_multigraph_edge_with_endpoint_metadata():
    router = make_router()

    wire = router.route_wire("wall_plug.GND", "earth.1A")

    assert wire.index == 1
    assert wire.from_pin == PinRef(component="wall_plug", pin="GND")
    assert wire.to_pin == PinRef(component="earth", pin="1A")
    assert wire.to_exposed_net == "earth"
    assert wire.to_auto_selected is False
    assert isinstance(router.physical_graph, nx.MultiGraph)
    assert router.physical_graph.number_of_edges() == 1

    edge = router.physical_graph.edges["wall_plug.GND", "earth.1A", 1]
    assert edge["wire_index"] == 1
    assert edge["requested_from"] == "wall_plug.GND"
    assert edge["requested_to"] == "earth.1A"
    assert edge["to_exposed_net"] == "earth"


def test_auto_selection_consumes_next_available_exposed_net_pin_in_order():
    router = make_router()

    first = router.route_wire("wall_plug.1", "power_t.110L")
    second = router.route_wire("power_t.110L", "transformer.110L")
    third = router.resolve_endpoint("power_t.110L")

    assert first.to_pin == PinRef(component="power_t", pin="1A")
    assert first.to_auto_selected is True
    assert second.from_pin == PinRef(component="power_t", pin="1B")
    assert third.pin == PinRef(component="power_t", pin="3A")
    assert allocation_snapshot(router.allocations)["power_t.110L"] == ["1A", "1B"]


def test_terminal_block_positions_are_internally_connected_even_without_named_nets():
    parsed = parse_panel_yaml(
        """
components:
  plug:
    type: connector
    pins:
      left: [L]
  cnc_terminals:
    type: terminal_block
    positions: 10
    pins:
      left: [A]
      right: [B]
  load:
    type: connector
    pins:
      right: [L]
connections:
  wires:
    - [plug.L, cnc_terminals.5A]
    - [cnc_terminals.5B, load.L]
"""
    )

    router = WireRouter.route_parse_result(parsed)

    assert router.routed_wires[0].to_pin == PinRef(component="cnc_terminals", pin="5A")
    assert router.routed_wires[1].from_pin == PinRef(component="cnc_terminals", pin="5B")
    assert router.routed_wires[0].net_name == "plug.L"
    assert router.routed_wires[1].net_name == "plug.L"
    assert sorted(router.net_graph.nodes["plug.L"]["member_pins"]) == [
        "cnc_terminals.5A",
        "cnc_terminals.5B",
        "load.L",
        "plug.L",
    ]


def test_route_chain_terminal_position_passes_through_a_to_b():
    parsed = parse_panel_yaml(
        """
components:
  plug:
    type: connector
    pins:
      left: [L]
  cnc_terminals:
    type: terminal_block
    positions: 10
    pins:
      left: [A]
      right: [B]
  load:
    type: connector
    pins:
      right: [L]
connections:
  wires:
    - [plug.L, cnc_terminals.5, load.L]
"""
    )

    router = WireRouter.route_parse_result(parsed)

    assert len(router.routed_wires) == 2
    assert router.routed_wires[0].from_pin == PinRef(component="plug", pin="L")
    assert router.routed_wires[0].to_pin == PinRef(component="cnc_terminals", pin="5A")
    assert router.routed_wires[1].from_pin == PinRef(component="cnc_terminals", pin="5B")
    assert router.routed_wires[1].to_pin == PinRef(component="load", pin="L")
    assert [wire.net_name for wire in router.routed_wires] == ["plug.L", "plug.L"]
    assert [wire.wire_label for wire in router.routed_wires] == ["plug.L-1", "plug.L-2"]


def test_route_chain_concrete_terminal_pin_creates_true_multiconnect():
    parsed = parse_panel_yaml(
        """
components:
  plug:
    type: connector
    pins:
      left: [L]
  cnc_terminals:
    type: terminal_block
    positions: 10
    pins:
      left: [A]
      right: [B]
  load:
    type: connector
    pins:
      right: [L]
connections:
  wires:
    - [plug.L, cnc_terminals.5A, load.L]
"""
    )

    router = WireRouter.route_parse_result(parsed)

    assert len(router.routed_wires) == 2
    assert router.routed_wires[0].to_pin == PinRef(component="cnc_terminals", pin="5A")
    assert router.routed_wires[1].from_pin == PinRef(component="cnc_terminals", pin="5A")
    assert router.physical_graph.degree("cnc_terminals.5A") == 2
    assert [wire.net_name for wire in router.routed_wires] == ["plug.L", "plug.L"]


def test_object_route_chain_applies_net_name_and_awg_to_each_wire():
    parsed = parse_panel_yaml(
        """
components:
  supply:
    type: connector
    pins:
      left: [L]
  block:
    type: terminal_block
    positions: 2
    pins:
      left: [A]
      right: [B]
  load:
    type: connector
    pins:
      right: [L]
connections:
  wires:
    - route: [supply.L, block.1, load.L]
      net: LINE
      awg: 12
"""
    )

    router = WireRouter.route_parse_result(parsed)

    assert [wire.explicit_net_name for wire in router.routed_wires] == ["LINE", "LINE"]
    assert [wire.net_name for wire in router.routed_wires] == ["LINE", "LINE"]
    assert [wire.wire_label for wire in router.routed_wires] == ["LINE-1", "LINE-2"]
    assert [wire.awg for wire in router.routed_wires] == [12, 12]


def test_simple_component_exported_net_connects_multiple_pins():
    parsed = parse_panel_yaml(
        """
components:
  board:
    type: pcb
    pins:
      left: [D2, D3]
      right: [OUT]
    nets:
      - name: LIMIT_BUS
        pins: [D2, D3]
  sensor:
    type: connector
    pins:
      right: [SIG]
connections:
  wires:
    - [sensor.SIG, board.D2]
"""
    )

    router = WireRouter.route_parse_result(parsed)

    assert router.routed_wires[0].net_name == "LIMIT_BUS"
    assert sorted(router.net_graph.nodes["LIMIT_BUS"]["member_pins"]) == [
        "board.D2",
        "board.D3",
        "sensor.SIG",
    ]


def test_explicit_pin_on_exposed_net_consumes_that_pin_for_future_auto_selection():
    router = make_router()

    router.route_wire("wall_plug.GND", "earth.1A")
    auto = router.route_wire("transformer.GND", "earth.earth")

    assert auto.to_pin == PinRef(component="earth", pin="1B")
    assert allocation_snapshot(router.allocations)["earth.earth"] == ["1A", "1B"]


def test_explicit_reuse_of_a_pin_is_allowed_and_creates_multiple_incident_edges():
    router = make_router()

    router.route_wire("wall_plug.GND", "earth.1A")
    router.route_wire("transformer.GND", "earth.1A")

    assert router.physical_graph.degree("earth.1A") == 2
    assert router.pin_connection_counts()["earth.1A"] == 2
    assert allocation_snapshot(router.allocations)["earth.earth"] == ["1A"]


def test_route_many_preserves_input_order_and_rejects_bad_wire_shapes():
    router = make_router()

    wires = router.route_many(
        [
            ["wall_plug.1", "power_t.110L"],
            ["wall_plug.2", "power_t.110N"],
        ]
    )

    assert [wire.index for wire in wires] == [1, 2]
    assert [wire.index for wire in router.routed_wires] == [1, 2]

    with pytest.raises(RoutingError, match="at least two endpoints"):
        router.route_many([["wall_plug.GND"]])


def test_wire_object_rows_can_assign_semantic_net_name_and_awg():
    parsed = parse_panel_yaml(
        ROUTING_YAML
        + """
connections:
  wires:
    - from: wall_plug.1
      to: power_t.110L
      net: line_power
      awg: 12
"""
    )

    router = WireRouter.route_parse_result(parsed)
    wire = router.routed_wires[0]

    assert wire.explicit_net_name == "line_power"
    assert wire.net_name == "line_power"
    assert wire.wire_label == "line_power-1"
    assert wire.awg == 12
    assert router.physical_graph.edges["wall_plug.1", "power_t.1A", 1]["awg"] == 12


def test_conflicting_wire_declared_net_names_are_rejected():
    router = make_router()
    router.route_wire("wall_plug.1", "power_t.110L", net_name="line_a")
    router.route_wire("wall_plug.2", "power_t.110L", net_name="line_b")

    with pytest.raises(RoutingError, match="wire-declared nets"):
        router.resolve_nets_and_labels()


def test_resolve_endpoint_reports_unknown_components_pins_and_exhausted_nets():
    router = make_router()

    with pytest.raises(RoutingError, match="Unknown component"):
        router.resolve_endpoint("missing.1")

    with pytest.raises(RoutingError, match="Unknown pin or exposed net"):
        router.resolve_endpoint("wall_plug.missing")

    router.route_wire("wall_plug.1", "power_t.110N")
    router.route_wire("wall_plug.2", "power_t.110N")

    with pytest.raises(RoutingError, match="No available pins"):
        router.resolve_endpoint("power_t.110N")


def test_pin_statuses_and_unrouted_pins_support_no_connect_filtering():
    router = make_router(no_connects=["relay.NC"])

    router.route_wire("wall_plug.GND", "earth.1A")
    statuses = {str(status.pin): status for status in router.pin_statuses()}

    assert statuses["wall_plug.GND"].is_routed is True
    assert statuses["wall_plug.GND"].connection_count == 1
    assert statuses["relay.NC"].is_no_connect is True
    assert statuses["relay.NC"].is_routed is False
    assert statuses["earth.1A"].exposed_nets == ["earth"]

    unrouted = {str(pin) for pin in router.unrouted_pins()}
    assert "relay.NC" not in unrouted
    assert "relay.NO" in unrouted

    unrouted_with_nc = {str(pin) for pin in router.unrouted_pins(include_no_connects=True)}
    assert "relay.NC" in unrouted_with_nc


def test_unrouted_pins_can_filter_by_component():
    router = make_router(no_connects=["relay.NC"])
    router.route_wire("wall_plug.GND", "earth.1A")

    assert {str(pin) for pin in router.unrouted_pins(component="wall_plug")} == {
        "wall_plug.1",
        "wall_plug.2",
    }
    assert {str(pin) for pin in router.unrouted_pins(component="relay")} == {
        "relay.NO",
        "relay.COM",
    }


def test_format_wire_label_supports_net_sequence_global_sequence_and_padding():
    assert format_wire_label("%netname-%seq", "110L", 3) == "110L-3"
    assert format_wire_label("%seq", "110L", 12) == "12"
    assert format_wire_label("%{5d}seq", "110L", 12) == "00012"
