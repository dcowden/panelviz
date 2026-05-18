"""Typed component models for PanelViz."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComponentType(StrEnum):
    """Known component types in the PanelViz DSL."""

    CONNECTOR = "connector"
    SWITCH = "switch"
    POWER_SUPPLY = "power_supply"
    RELAY = "relay"
    DRIVER = "driver"
    VFD = "vfd"
    AVIATION_CONNECTOR = "aviation_connector"
    TERMINAL_BLOCK = "terminal_block"
    BUS_BLOCK = "bus_block"
    PCB = "pcb"


class PinSide(StrEnum):
    """Physical side of a component where pins are located."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


PIN_SIDE_ORDER = (PinSide.LEFT, PinSide.RIGHT, PinSide.TOP, PinSide.BOTTOM)


class PinAllocationError(ValueError):
    """Raised when no free pin exists on an exposed component net."""


class UnknownNetError(KeyError):
    """Raised when asking a component for a net it does not expose."""


class PinRef(BaseModel):
    """A parsed `component.pin` reference."""

    component: str
    pin: str

    model_config = ConfigDict(frozen=True)

    @classmethod
    def parse(cls, value: str) -> Self:
        parts = value.split(".")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Pin references must use component.pin form: {value!r}")
        return cls(component=parts[0], pin=parts[1])

    def __str__(self) -> str:
        return f"{self.component}.{self.pin}"


class NetDefinition(BaseModel):
    """A named net exposed by a component."""

    name: str
    positions: list[int] | None = None
    pins: list[str] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _stringify_name(cls, value: Any) -> str:
        return str(value)

    @field_validator("pins", mode="before")
    @classmethod
    def _stringify_pins(cls, value: Any) -> Any:
        if value is None:
            return value
        return [str(pin) for pin in value]

    @field_validator("positions")
    @classmethod
    def _positions_are_positive_unique(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        if any(position < 1 for position in value):
            raise ValueError("net positions must be positive")
        if len(set(value)) != len(value):
            raise ValueError("net positions must be unique")
        return value

    @field_validator("pins")
    @classmethod
    def _pins_are_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(set(value)) != len(value):
            raise ValueError("net pins must be unique")
        return value


class ComponentSize(BaseModel):
    """Conceptual physical component dimensions."""

    width: float
    height: float

    @field_validator("width", "height")
    @classmethod
    def _dimensions_are_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("component dimensions must be positive")
        return value


class Component(BaseModel):
    """Base component model with named pins and optional exposed nets."""

    name: str
    type: ComponentType
    pins: dict[PinSide, list[str]]
    size: ComponentSize | None = None
    nets: list[NetDefinition] = Field(default_factory=list)
    positions: int | None = None

    model_config = ConfigDict(validate_assignment=True)

    @field_validator("name", mode="before")
    @classmethod
    def _stringify_name(cls, value: Any) -> str:
        return str(value)

    @field_validator("pins", mode="before")
    @classmethod
    def _stringify_pin_map(cls, value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise ValueError("component pins must be grouped by side")
        return {str(side): [str(pin) for pin in pins] for side, pins in value.items()}

    @field_validator("pins")
    @classmethod
    def _pins_are_unique(cls, value: dict[PinSide, list[str]]) -> dict[PinSide, list[str]]:
        pin_labels = [pin for pins in value.values() for pin in pins]
        if not pin_labels:
            raise ValueError("components must define at least one pin")
        if len(set(pin_labels)) != len(pin_labels):
            raise ValueError("component pins must be unique")
        return value

    @field_validator("positions")
    @classmethod
    def _positions_are_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("positions must be positive")
        return value

    @model_validator(mode="after")
    def _validate_nets(self) -> Self:
        net_names = [net.name for net in self.nets]
        if len(set(net_names)) != len(net_names):
            raise ValueError("component net names must be unique")
        if self.type not in {ComponentType.TERMINAL_BLOCK, ComponentType.BUS_BLOCK}:
            known_pins = set(self.physical_pins())
            for net in self.nets:
                unknown_pins = set(net.pins or []) - known_pins
                if unknown_pins:
                    raise ValueError(f"net {net.name!r} references unknown pins: {sorted(unknown_pins)}")
        return self

    def physical_pins(self) -> list[str]:
        """Return concrete pin names addressable as `component.pin`."""

        return self.pin_labels()

    def pin_labels(self) -> list[str]:
        """Return base pin labels in canonical side order."""

        return [
            pin
            for side in PIN_SIDE_ORDER
            for pin in self.pins.get(side, [])
        ]

    def pin_side(self, pin: str) -> PinSide | None:
        """Return the physical side for a concrete pin, when known."""

        base_pin = self._base_pin_for_side_lookup(pin)
        for side in PIN_SIDE_ORDER:
            if base_pin in self.pins.get(side, []):
                return side
        return None

    def qualified_pins(self) -> list[str]:
        """Return concrete pins with the component name attached."""

        return [f"{self.name}.{pin}" for pin in self.physical_pins()]

    def has_pin(self, pin: str) -> bool:
        """Return whether a concrete pin exists on this component."""

        return pin in self.physical_pins()

    def exposes_net(self, net_name: str) -> bool:
        """Return whether this component exposes a named net."""

        return any(net.name == net_name for net in self.nets)

    def net_names(self) -> list[str]:
        """Return the names of nets exposed by this component."""

        return [net.name for net in self.nets]

    def pins_for_net(self, net_name: str) -> list[str]:
        """Return concrete pins belonging to an exposed net."""

        for net in self.nets:
            if net.name == net_name:
                if net.pins is None:
                    return []
                return list(net.pins)
        raise UnknownNetError(net_name)

    def next_available_pin(self, net_name: str, used_pins: Iterable[str] = ()) -> str:
        """Return the first unconsumed concrete pin on an exposed net."""

        used = set(used_pins)
        for pin in self.pins_for_net(net_name):
            if pin not in used:
                return pin
        raise PinAllocationError(f"No available pins on {self.name}.{net_name}")

    def _base_pin_for_side_lookup(self, pin: str) -> str:
        return pin


class Connector(Component):
    """Simple connector component."""

    type: ComponentType = ComponentType.CONNECTOR


class Switch(Component):
    """Simple switch/contactor component."""

    type: ComponentType = ComponentType.SWITCH


class PowerSupply(Component):
    """Power supply component."""

    type: ComponentType = ComponentType.POWER_SUPPLY


class Relay(Component):
    """Relay component."""

    type: ComponentType = ComponentType.RELAY


class Driver(Component):
    """Motor/servo/stepper driver component."""

    type: ComponentType = ComponentType.DRIVER


class Vfd(Component):
    """Variable frequency drive component."""

    type: ComponentType = ComponentType.VFD


class AviationConnector(Component):
    """Circular aviation connector component."""

    type: ComponentType = ComponentType.AVIATION_CONNECTOR


class Pcb(Component):
    """PCB component with explicitly named pins."""

    type: ComponentType = ComponentType.PCB


class TerminalBlock(Component):
    """Terminal block with positions and exposed nets."""

    type: ComponentType = ComponentType.TERMINAL_BLOCK

    @model_validator(mode="after")
    def _validate_terminal_nets(self) -> Self:
        for net in self.nets:
            if net.positions is None and self.type != ComponentType.BUS_BLOCK:
                raise ValueError("terminal block nets must define positions")
            if net.pins is not None:
                unknown_pins = set(net.pins) - set(self.pin_labels())
                if unknown_pins:
                    raise ValueError(f"net {net.name!r} references unknown pins: {sorted(unknown_pins)}")

        if self.positions is not None:
            max_position = max((position for net in self.nets for position in net.positions or []), default=0)
            if max_position > self.positions:
                raise ValueError("net position exceeds terminal block positions")
        return self

    def position_count(self) -> int:
        """Return explicit or inferred terminal position count."""

        if self.positions is not None:
            return self.positions
        return max((position for net in self.nets for position in net.positions or []), default=0)

    def physical_pins(self) -> list[str]:
        """Expand positions and per-position terminal names into concrete pins."""

        return [f"{position}{pin}" for position in range(1, self.position_count() + 1) for pin in self.pin_labels()]

    def position_pin_groups(self) -> list[list[str]]:
        """Return the concrete pins that are internally connected per position."""

        return [[f"{position}{pin}" for pin in self.pin_labels()] for position in range(1, self.position_count() + 1)]

    def pins_for_net(self, net_name: str) -> list[str]:
        """Return concrete terminal pins belonging to an exposed net."""

        for net in self.nets:
            if net.name != net_name:
                continue

            position_pins = net.pins or self.pin_labels()
            return [f"{position}{pin}" for position in net.positions or [] for pin in position_pins]
        raise UnknownNetError(net_name)

    def _base_pin_for_side_lookup(self, pin: str) -> str:
        return pin.lstrip("0123456789")


class BusBlock(TerminalBlock):
    """Bus block where each exposed net spans all positions unless specified."""

    type: ComponentType = ComponentType.BUS_BLOCK

    @model_validator(mode="after")
    def _fill_bus_net_positions(self) -> Self:
        if self.positions is None:
            raise ValueError("bus blocks must define positions")
        for net in self.nets:
            if net.positions is None:
                net.positions = list(range(1, self.positions + 1))
        return self


_COMPONENT_TYPES: dict[ComponentType, type[Component]] = {
    ComponentType.CONNECTOR: Connector,
    ComponentType.SWITCH: Switch,
    ComponentType.POWER_SUPPLY: PowerSupply,
    ComponentType.RELAY: Relay,
    ComponentType.DRIVER: Driver,
    ComponentType.VFD: Vfd,
    ComponentType.AVIATION_CONNECTOR: AviationConnector,
    ComponentType.TERMINAL_BLOCK: TerminalBlock,
    ComponentType.BUS_BLOCK: BusBlock,
    ComponentType.PCB: Pcb,
}


def create_component(name: str, data: dict[str, Any]) -> Component:
    """Create a concrete component model from parsed DSL data."""

    component_type = ComponentType(data["type"])
    component_class = _COMPONENT_TYPES[component_type]
    return component_class(name=name, **data)
