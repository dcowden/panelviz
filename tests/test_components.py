import pytest
from pydantic import ValidationError

from panelviz.components import (
    AviationConnector,
    BusBlock,
    Component,
    ComponentSize,
    ComponentType,
    Connector,
    Driver,
    NetDefinition,
    Pcb,
    PinAllocationError,
    PinRef,
    PinSide,
    PowerSupply,
    Relay,
    Switch,
    TerminalBlock,
    UnknownNetError,
    Vfd,
    create_component,
)


SIDE_PINS = {"left": ["A"], "right": ["B"]}


def test_pin_ref_accepts_only_component_dot_pin_form():
    ref = PinRef.parse("earth.1A")

    assert ref.component == "earth"
    assert ref.pin == "1A"
    assert str(ref) == "earth.1A"

    with pytest.raises(ValueError):
        PinRef.parse("earth.1.A")

    with pytest.raises(ValueError):
        PinRef.parse("earth.")


def test_net_definition_validates_positions_and_pin_names():
    net = NetDefinition(name=110, positions=None, pins=[1, "B"])

    assert net.name == "110"
    assert net.positions is None
    assert net.pins == ["1", "B"]

    with pytest.raises(ValidationError, match="net positions must be positive"):
        NetDefinition(name="bad", positions=[0])

    with pytest.raises(ValidationError, match="net positions must be unique"):
        NetDefinition(name="bad", positions=[1, 1])

    with pytest.raises(ValidationError, match="net pins must be unique"):
        NetDefinition(name="bad", pins=["A", "A"])


def test_simple_component_stringifies_pin_names_and_qualifies_them():
    connector = Connector(name="wall_plug", pins={"right": ["GND", 1, 2]}, size={"width": 24, "height": 24})

    assert connector.type == ComponentType.CONNECTOR
    assert connector.physical_pins() == ["GND", "1", "2"]
    assert connector.qualified_pins() == ["wall_plug.GND", "wall_plug.1", "wall_plug.2"]
    assert connector.pin_side("GND") == PinSide.RIGHT
    assert connector.size == ComponentSize(width=24, height=24)
    assert connector.has_pin("1")
    assert not connector.has_pin("3")
    assert not connector.exposes_net("GND")


def test_simple_component_types_are_available_for_dispatch_and_diagrams():
    assert Switch(name="contactor", pins={"top": ["A1"], "bottom": ["A2"]}).type == ComponentType.SWITCH
    assert PowerSupply(name="supply", pins={"bottom": ["GND", "V+"]}).type == ComponentType.POWER_SUPPLY
    assert Relay(name="relay", pins={"bottom": ["NO", "COM", "NC"]}).type == ComponentType.RELAY
    assert Driver(name="x_axis", pins={"left": ["PUL"], "right": ["A+", "A-"]}).type == ComponentType.DRIVER
    assert Vfd(name="spindle", pins={"bottom": ["U", "V", "W"]}).type == ComponentType.VFD
    assert AviationConnector(name="motor", pins={"left": ["A", "B"]}).type == ComponentType.AVIATION_CONNECTOR
    assert Pcb(name="controller", pins={"left": ["IN"], "right": ["OUT"]}).type == ComponentType.PCB


def test_simple_component_can_expose_explicit_nets():
    component = Component(
        name="jumper",
        type=ComponentType.CONNECTOR,
        pins=SIDE_PINS,
        nets=[
            {"name": "LINK", "pins": ["A", "B"]},
            {"name": "EMPTY"},
        ],
    )

    assert component.exposes_net("LINK")
    assert component.pins_for_net("LINK") == ["A", "B"]
    assert component.pins_for_net("EMPTY") == []
    assert component.next_available_pin("LINK", used_pins={"A"}) == "B"

    with pytest.raises(PinAllocationError):
        component.next_available_pin("EMPTY")


def test_simple_component_nets_can_join_multiple_explicit_pins():
    component = Pcb(
        name="alarm_limit_board",
        pins={"top": ["A0", "A1"], "bottom": ["D2", "D3"]},
        nets=[
            {"name": "LIMITS", "pins": ["A0", "A1"]},
            {"name": "RESET", "pins": ["D2"]},
        ],
    )

    assert component.net_names() == ["LIMITS", "RESET"]
    assert component.pins_for_net("LIMITS") == ["A0", "A1"]
    assert component.next_available_pin("LIMITS", used_pins={"A0"}) == "A1"

    with pytest.raises(ValidationError, match="references unknown pins"):
        Pcb(name="bad", pins={"left": ["A"]}, nets=[{"name": "N", "pins": ["B"]}])


def test_component_rejects_duplicate_pins():
    with pytest.raises(ValidationError, match="component pins must be unique"):
        Connector(name="bad", pins={"left": ["A"], "right": ["A"]})


def test_component_rejects_empty_or_ungrouped_pins_bad_positions_size_and_duplicate_net_names():
    with pytest.raises(ValidationError, match="component pins must be grouped by side"):
        Connector(name="bad", pins=["A"])

    with pytest.raises(ValidationError, match="components must define at least one pin"):
        Connector(name="bad", pins={"left": []})

    with pytest.raises(ValidationError, match="positions must be positive"):
        Connector(name="bad", pins={"left": ["A"]}, positions=0)

    with pytest.raises(ValidationError, match="component dimensions must be positive"):
        Connector(name="bad", pins={"left": ["A"]}, size={"width": 0, "height": 1})

    with pytest.raises(ValidationError, match="component net names must be unique"):
        Component(
            name="bad",
            type=ComponentType.CONNECTOR,
            pins={"left": ["A"]},
            nets=[{"name": "N"}, {"name": "N"}],
        )


def test_terminal_block_expands_physical_pins_and_exposed_nets():
    block = TerminalBlock(
        name="power_t",
        pins=SIDE_PINS,
        nets=[
            {"name": "110L", "positions": [1, 3, 5]},
            {"name": "110N", "positions": [2, 4, 6]},
        ],
    )

    assert block.position_count() == 6
    assert block.physical_pins() == [
        "1A",
        "1B",
        "2A",
        "2B",
        "3A",
        "3B",
        "4A",
        "4B",
        "5A",
        "5B",
        "6A",
        "6B",
    ]
    assert block.net_names() == ["110L", "110N"]
    assert block.pins_for_net("110L") == ["1A", "1B", "3A", "3B", "5A", "5B"]
    assert block.position_pin_groups()[0] == ["1A", "1B"]
    assert block.pin_side("1A") == PinSide.LEFT
    assert block.pin_side("1B") == PinSide.RIGHT


def test_terminal_block_can_limit_exposed_net_to_selected_pin_labels():
    block = TerminalBlock(
        name="power_t",
        pins=SIDE_PINS,
        nets=[{"name": "110L", "positions": [1, 3], "pins": ["B"]}],
    )

    assert block.pins_for_net("110L") == ["1B", "3B"]

    with pytest.raises(ValidationError, match="references unknown pins"):
        TerminalBlock(
            name="bad",
            pins=SIDE_PINS,
            nets=[{"name": "110L", "positions": [1], "pins": ["C"]}],
        )


def test_terminal_block_honors_explicit_position_limit():
    TerminalBlock(
        name="coil_t",
        pins=SIDE_PINS,
        positions=4,
        nets=[{"name": "COIL+", "positions": [1, 2]}],
    )

    with pytest.raises(ValidationError, match="net position exceeds terminal block positions"):
        TerminalBlock(
            name="bad",
            pins=SIDE_PINS,
            positions=2,
            nets=[{"name": "TOO_FAR", "positions": [3]}],
        )


def test_terminal_block_requires_positions_for_each_net():
    with pytest.raises(ValidationError, match="terminal block nets must define positions"):
        TerminalBlock(name="bad", pins=SIDE_PINS, nets=[{"name": "MISSING"}])


def test_terminal_block_allocates_next_available_net_pin():
    block = TerminalBlock(
        name="power_t",
        pins=SIDE_PINS,
        nets=[{"name": "110L", "positions": [1, 3]}],
    )

    assert block.next_available_pin("110L") == "1A"
    assert block.next_available_pin("110L", used_pins={"1A"}) == "1B"
    assert block.next_available_pin("110L", used_pins={"1A", "1B"}) == "3A"

    with pytest.raises(PinAllocationError):
        block.next_available_pin("110L", used_pins={"1A", "1B", "3A", "3B"})


def test_unknown_net_raises_clear_domain_error():
    block = TerminalBlock(
        name="power_t",
        pins=SIDE_PINS,
        nets=[{"name": "110L", "positions": [1]}],
    )

    with pytest.raises(UnknownNetError):
        block.pins_for_net("110N")

    with pytest.raises(UnknownNetError):
        Connector(name="plain", pins={"left": ["A"]}).pins_for_net("A")


def test_bus_block_defaults_net_to_all_positions():
    earth = BusBlock(
        name="earth",
        pins=SIDE_PINS,
        positions=4,
        nets=[{"name": "earth"}],
    )

    assert earth.physical_pins() == ["1A", "1B", "2A", "2B", "3A", "3B", "4A", "4B"]
    assert earth.pins_for_net("earth") == ["1A", "1B", "2A", "2B", "3A", "3B", "4A", "4B"]


def test_bus_block_requires_positions_and_preserves_explicit_net_positions():
    with pytest.raises(ValidationError, match="bus blocks must define positions"):
        BusBlock(name="bad", pins=SIDE_PINS, nets=[{"name": "earth"}])

    earth = BusBlock(
        name="earth",
        pins=SIDE_PINS,
        positions=4,
        nets=[{"name": "earth", "positions": [2, 4]}],
    )

    assert earth.pins_for_net("earth") == ["2A", "2B", "4A", "4B"]


def test_create_component_dispatches_to_concrete_type():
    component = create_component("wall_plug", {"type": "connector", "pins": {"right": ["GND", 1, 2]}})

    assert isinstance(component, Connector)
    assert component.name == "wall_plug"


def test_create_component_rejects_unknown_component_type():
    with pytest.raises(ValueError, match="not_a_type"):
        create_component("mystery", {"type": "not_a_type", "pins": {"left": ["A"]}})
