"""YAML parser for PanelViz input files."""

from __future__ import annotations

from collections.abc import Mapping
from io import StringIO
from typing import Any, Literal, TypeAlias

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ruamel.yaml import YAML

from panelviz.components import Component, TerminalBlock, create_component

WiringMode: TypeAlias = Literal["wires", "labels"]
LineStyle: TypeAlias = Literal["solid", "dashed", "dotted"]


class PanelParseError(ValueError):
    """Raised when input YAML does not match the PanelViz file shape."""


class UnitsConfig(BaseModel):
    """Measurement units used by physical component metadata."""

    length: str = "mm"

    @field_validator("length")
    @classmethod
    def _length_unit_is_supported(cls, value: str) -> str:
        if value not in {"mm", "in"}:
            raise ValueError("length unit must be 'mm' or 'in'")
        return value


class NetStyle(BaseModel):
    """Visual style for a rendered electrical net."""

    color: str = "#475569"
    line_weight: float = 1.6
    line_style: LineStyle = "solid"


def default_net_styles() -> dict[str, NetStyle]:
    """Return common default net colors for immediate readability."""

    blue = NetStyle(color="#2563eb", line_weight=1.8, line_style="solid")
    green = NetStyle(color="#16a34a", line_weight=2.0, line_style="solid")
    return {
        "110L": blue,
        "110N": blue,
        "220L": blue,
        "220N": blue,
        "earth": green,
    }


class VisualizationConfig(BaseModel):
    """Top-level visual styling configuration."""

    default_net_style: NetStyle = Field(default_factory=NetStyle)
    net_styles: dict[str, NetStyle] = Field(default_factory=default_net_styles)
    terminal_width: float = 0.1
    terminal_width_unit: str = "in"

    @field_validator("terminal_width")
    @classmethod
    def _terminal_width_is_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("terminal_width must be positive")
        return value

    @field_validator("terminal_width_unit")
    @classmethod
    def _terminal_width_unit_is_supported(cls, value: str) -> str:
        if value not in {"mm", "in"}:
            raise ValueError("terminal_width_unit must be 'mm' or 'in'")
        return value

    @model_validator(mode="after")
    def _merge_default_net_styles(self) -> "VisualizationConfig":
        merged = default_net_styles()
        merged.update(self.net_styles)
        self.net_styles = merged
        return self

    def style_for_net(self, net_name: str) -> NetStyle:
        """Return the configured style for a resolved net."""

        if net_name in self.net_styles:
            return self.net_styles[net_name]
        if "earth" in net_name.lower():
            return self.net_styles.get("earth", self.default_net_style)
        return self.default_net_style


class DefaultsConfig(BaseModel):
    """Default values applied to parsed connection rows."""

    awg: int = 20

    @field_validator("awg")
    @classmethod
    def _awg_is_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("default wire awg must be positive")
        return value


class DrawingConfig(BaseModel):
    """Metadata used in drawing title blocks."""

    company: str = ""
    author: str = ""
    title: str = "PanelViz Wiring Schematic"


class PanelConfig(BaseModel):
    """Top-level PanelViz configuration."""

    wire_label_format: str = "%netname-%seq"
    wiring_mode: WiringMode = "wires"
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    drawing: DrawingConfig = Field(default_factory=DrawingConfig)
    units: UnitsConfig = Field(default_factory=UnitsConfig)
    visualization: VisualizationConfig = Field(default_factory=VisualizationConfig)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class WireSpec(BaseModel):
    """One connection row from the YAML DSL.

    A row may describe one physical wire with `from`/`to`, or a route chain
    that expands to one physical wire per adjacent endpoint pair.
    """

    from_endpoint: str | None = Field(default=None, alias="from")
    to_endpoint: str | None = Field(default=None, alias="to")
    route: list[str] | None = None
    net_name: str | None = Field(default=None, alias="net")
    awg: int | None = None
    source_index: int | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("from_endpoint", "to_endpoint", "net_name", mode="before")
    @classmethod
    def _stringify_optional_names(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    @field_validator("route", mode="before")
    @classmethod
    def _stringify_route(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("wire route must be a list")
        return [str(endpoint) for endpoint in value]

    @field_validator("awg")
    @classmethod
    def _awg_is_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("wire awg must be positive")
        return value

    @model_validator(mode="after")
    def _validate_endpoint_shape(self) -> "WireSpec":
        has_pair = self.from_endpoint is not None or self.to_endpoint is not None
        has_route = self.route is not None
        if has_pair and has_route:
            raise ValueError("wire rows must use either route or from/to, not both")
        if has_route:
            if len(self.route or []) < 2:
                raise ValueError("wire routes must contain at least two endpoints")
            return self
        if self.from_endpoint is None or self.to_endpoint is None:
            raise ValueError("wire rows must define from/to or route")
        return self

    def endpoints(self) -> tuple[str, str]:
        """Return the first and last endpoint references for this connection row."""

        if self.route is not None:
            return self.route[0], self.route[-1]
        assert self.from_endpoint is not None
        assert self.to_endpoint is not None
        return self.from_endpoint, self.to_endpoint


class ComponentParseResult(BaseModel):
    """Parsed components and their component-pin graph."""

    config: PanelConfig = Field(default_factory=PanelConfig)
    components: dict[str, Component]
    component_pin_graph: nx.MultiGraph
    wires: list[WireSpec] = Field(default_factory=list)
    no_connects: list[str] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def component(self, name: str) -> Component:
        """Return a parsed component by name."""

        return self.components[name]

    def pin_node(self, component: str, pin: str) -> str:
        """Return the graph node id for a concrete component pin."""

        node = f"{component}.{pin}"
        if node not in self.component_pin_graph:
            raise KeyError(node)
        return node


def parse_panel_yaml(text: str) -> ComponentParseResult:
    """Parse a PanelViz YAML document and build the component-pin graph."""

    yaml = YAML(typ="safe")
    data = yaml.load(StringIO(text))
    if not isinstance(data, Mapping):
        raise PanelParseError("PanelViz input must be a YAML mapping")

    config = PanelConfig.model_validate(data.get("config", {}))
    components_tree = data.get("components")
    wires = _parse_wires(data.get("connections", {}))
    no_connects = _parse_no_connects(data.get("no_connects", []))
    return parse_components_tree(components_tree, config=config, wires=wires, no_connects=no_connects)


def parse_components_tree(
    components_tree: Any,
    config: PanelConfig | None = None,
    wires: list[WireSpec] | None = None,
    no_connects: list[str] | None = None,
) -> ComponentParseResult:
    """Parse the top-level `components` tree into models and graph nodes."""

    if not isinstance(components_tree, Mapping):
        raise PanelParseError("PanelViz input must contain a components mapping")

    components: dict[str, Component] = {}
    for name, component_data in components_tree.items():
        if not isinstance(component_data, Mapping):
            raise PanelParseError(f"Component {name!r} must be a mapping")
        components[str(name)] = create_component(str(name), dict(component_data))

    return ComponentParseResult(
        config=config or PanelConfig(),
        components=components,
        component_pin_graph=build_component_pin_graph(components),
        wires=wires or [],
        no_connects=no_connects or [],
    )


def build_component_pin_graph(components: Mapping[str, Component]) -> nx.MultiGraph:
    """Build a NetworkX graph containing one node per concrete component pin."""

    graph = nx.MultiGraph()
    for component in components.values():
        exposed_nets_by_pin = _exposed_nets_by_pin(component)
        for pin in component.physical_pins():
            pin_side = component.pin_side(pin)
            graph.add_node(
                f"{component.name}.{pin}",
                component=component.name,
                pin=pin,
                pin_side=pin_side.value if pin_side else None,
                component_type=component.type.value,
                exposed_nets=exposed_nets_by_pin.get(pin, []),
                component_width=component.size.width if component.size else None,
                component_height=component.size.height if component.size else None,
                terminal_pin=isinstance(component, TerminalBlock),
            )
    return graph


def _exposed_nets_by_pin(component: Component) -> dict[str, list[str]]:
    exposed: dict[str, list[str]] = {pin: [] for pin in component.physical_pins()}
    for net_name in component.net_names():
        for pin in component.pins_for_net(net_name):
            exposed.setdefault(pin, []).append(net_name)
    return exposed


def _parse_wires(connections_tree: Any) -> list[WireSpec]:
    if connections_tree in (None, {}):
        return []
    if not isinstance(connections_tree, Mapping):
        raise PanelParseError("connections must be a mapping")

    raw_wires = connections_tree.get("wires", [])
    if not isinstance(raw_wires, list):
        raise PanelParseError("connections.wires must be a list")

    wires: list[WireSpec] = []
    for source_index, raw_wire in enumerate(raw_wires):
        if isinstance(raw_wire, Mapping):
            wire_spec = WireSpec.model_validate(dict(raw_wire))
            wire_spec.source_index = source_index
            wires.append(wire_spec)
            continue
        if not isinstance(raw_wire, list) or len(raw_wire) < 2:
            raise PanelParseError(f"wire entries must contain at least two endpoints: {raw_wire!r}")
        if len(raw_wire) == 2:
            wires.append(WireSpec(from_endpoint=str(raw_wire[0]), to_endpoint=str(raw_wire[1]), source_index=source_index))
        else:
            wires.append(WireSpec(route=[str(endpoint) for endpoint in raw_wire], source_index=source_index))
    return wires


def _parse_no_connects(no_connects_tree: Any) -> list[str]:
    if no_connects_tree is None:
        return []
    if not isinstance(no_connects_tree, list):
        raise PanelParseError("no_connects must be a list")
    return [str(pin) for pin in no_connects_tree]
