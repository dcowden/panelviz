import networkx as nx
import pytest

from panelviz.components import BusBlock, Connector, TerminalBlock
from panelviz.parser import PanelParseError, parse_components_tree, parse_panel_yaml


COMPONENTS_YAML = """
config:
  wire_label_format: "%netname-%seq"
  wiring_mode: labels
  defaults:
    awg: 20
  units:
    length: mm
  visualization:
    default_net_style:
      color: "#475569"
      line_weight: 1.6
      line_style: dashed
    net_styles:
      110L:
        color: "#1d4ed8"
        line_weight: 2.5
        line_style: solid

components:
  wall_plug:
    type: connector
    size:
      width: 24
      height: 24
    pins:
      right: [GND, 1, 2]
  power_t:
    type: terminal_block
    size:
      width: 6
      height: 50
    pins:
      left: [A]
      right: [B]
    nets:
      - name: 110L
        positions: [1]
      - name: 110N
        positions: [2]
  earth:
    type: bus_block
    size:
      width: 6
      height: 50
    pins:
      left: [A]
      right: [B]
    positions: 2
    nets:
      - name: earth
"""


def test_parse_panel_yaml_builds_typed_components_from_components_tree():
    result = parse_panel_yaml(COMPONENTS_YAML)

    assert result.config.wire_label_format == "%netname-%seq"
    assert result.config.wiring_mode == "labels"
    assert result.config.defaults.awg == 20
    assert result.config.units.length == "mm"
    assert result.config.visualization.default_net_style.line_style == "dashed"
    assert result.config.visualization.style_for_net("110L").color == "#1d4ed8"
    assert result.config.visualization.style_for_net("earth").color == "#16a34a"
    assert result.config.visualization.style_for_net("unknown").color == "#475569"
    assert result.wires == []
    assert result.no_connects == []
    assert set(result.components) == {"wall_plug", "power_t", "earth"}
    assert isinstance(result.component("wall_plug"), Connector)
    assert isinstance(result.component("power_t"), TerminalBlock)
    assert isinstance(result.component("earth"), BusBlock)
    assert result.component("wall_plug").physical_pins() == ["GND", "1", "2"]
    assert result.component("power_t").pins_for_net("110L") == ["1A", "1B"]
    assert result.component("earth").pins_for_net("earth") == ["1A", "1B", "2A", "2B"]


def test_parse_panel_yaml_accepts_mixed_compact_and_object_wire_rows():
    result = parse_panel_yaml(
        COMPONENTS_YAML
        + """
connections:
  wires:
    - [wall_plug.GND, earth.1A]
    - [wall_plug.2, power_t.2, transformer.110N]
    - from: wall_plug.1
      to: power_t.110L
      net: semantic_line
      awg: 12
    - route: [transformer.110L, power_t.1, wall_plug.1]
      net: chained_line
      awg: 14
"""
    )

    assert result.wires[0].endpoints() == ("wall_plug.GND", "earth.1A")
    assert result.wires[0].net_name is None
    assert result.wires[0].awg is None
    assert result.wires[1].route == ["wall_plug.2", "power_t.2", "transformer.110N"]
    assert result.wires[1].endpoints() == ("wall_plug.2", "transformer.110N")
    assert result.wires[2].endpoints() == ("wall_plug.1", "power_t.110L")
    assert result.wires[2].net_name == "semantic_line"
    assert result.wires[2].awg == 12
    assert result.wires[3].route == ["transformer.110L", "power_t.1", "wall_plug.1"]
    assert result.wires[3].net_name == "chained_line"
    assert result.wires[3].awg == 14


def test_parse_panel_yaml_builds_component_pin_graph_nodes_without_wire_edges():
    result = parse_panel_yaml(COMPONENTS_YAML)
    graph = result.component_pin_graph

    assert isinstance(graph, nx.MultiGraph)
    assert graph.number_of_edges() == 0
    assert set(graph.nodes) == {
        "wall_plug.GND",
        "wall_plug.1",
        "wall_plug.2",
        "power_t.1A",
        "power_t.1B",
        "power_t.2A",
        "power_t.2B",
        "earth.1A",
        "earth.1B",
        "earth.2A",
        "earth.2B",
    }


def test_component_pin_graph_nodes_include_routing_metadata():
    result = parse_panel_yaml(COMPONENTS_YAML)
    graph = result.component_pin_graph

    assert graph.nodes["wall_plug.1"]["component"] == "wall_plug"
    assert graph.nodes["wall_plug.1"]["pin"] == "1"
    assert graph.nodes["wall_plug.1"]["pin_side"] == "right"
    assert graph.nodes["wall_plug.1"]["component_type"] == "connector"
    assert graph.nodes["wall_plug.1"]["exposed_nets"] == []
    assert graph.nodes["wall_plug.1"]["component_width"] == 24
    assert graph.nodes["wall_plug.1"]["component_height"] == 24
    assert graph.nodes["wall_plug.1"]["terminal_pin"] is False
    assert graph.nodes["power_t.1A"]["exposed_nets"] == ["110L"]
    assert graph.nodes["power_t.1A"]["pin_side"] == "left"
    assert graph.nodes["power_t.2B"]["exposed_nets"] == ["110N"]
    assert graph.nodes["power_t.2B"]["pin_side"] == "right"
    assert graph.nodes["power_t.1A"]["terminal_pin"] is True
    assert graph.nodes["earth.2B"]["exposed_nets"] == ["earth"]


def test_parse_result_pin_node_validates_graph_membership():
    result = parse_panel_yaml(COMPONENTS_YAML)

    assert result.pin_node("power_t", "1A") == "power_t.1A"
    with pytest.raises(KeyError):
        result.pin_node("power_t", "3A")


def test_parse_components_tree_accepts_mapping_directly():
    result = parse_components_tree(
        {
            "relay": {
                "type": "relay",
                "pins": {"top": ["DC+", "DC-"], "bottom": ["IN", "NO", "COM", "NC"]},
            }
        }
    )

    assert result.component("relay").qualified_pins() == [
        "relay.DC+",
        "relay.DC-",
        "relay.IN",
        "relay.NO",
        "relay.COM",
        "relay.NC",
    ]
    assert list(result.component_pin_graph.nodes) == result.component("relay").qualified_pins()


def test_parser_rejects_bad_yaml_shapes():
    with pytest.raises(PanelParseError, match="YAML mapping"):
        parse_panel_yaml("- just\n- a\n- list\n")

    with pytest.raises(PanelParseError, match="components mapping"):
        parse_panel_yaml("connections: {}\n")

    with pytest.raises(PanelParseError, match="must be a mapping"):
        parse_components_tree({"bad": "connector"})

    with pytest.raises(ValueError, match="length unit"):
        parse_panel_yaml("config: {units: {length: cm}}\ncomponents: {}\n")

    with pytest.raises(ValueError, match="wiring_mode"):
        parse_panel_yaml("config: {wiring_mode: bogus}\ncomponents: {}\n")

    with pytest.raises(PanelParseError, match="connections must be a mapping"):
        parse_panel_yaml("components: {}\nconnections: []\n")

    with pytest.raises(PanelParseError, match="connections.wires"):
        parse_panel_yaml("components: {}\nconnections: {wires: nope}\n")

    with pytest.raises(PanelParseError, match="at least two endpoints"):
        parse_panel_yaml("components: {}\nconnections: {wires: [[a.b]]}\n")

    with pytest.raises(ValueError, match="wire awg"):
        parse_panel_yaml("components: {}\nconnections: {wires: [{from: a.b, to: c.d, awg: 0}]}\n")

    with pytest.raises(ValueError, match="either route or from/to"):
        parse_panel_yaml("components: {}\nconnections: {wires: [{from: a.b, to: c.d, route: [a.b, c.d]}]}\n")

    with pytest.raises(PanelParseError, match="no_connects"):
        parse_panel_yaml("components: {}\nno_connects: nope\n")
