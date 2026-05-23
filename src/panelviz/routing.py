"""Wire routing primitives built on NetworkX."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from panelviz.components import Component, PinAllocationError, PinRef, TerminalBlock
from panelviz.parser import ComponentParseResult, VisualizationConfig, WireSpec, WiringMode


class RoutingError(ValueError):
    """Raised when a wire endpoint cannot be routed."""


class ResolvedEndpoint(BaseModel):
    """A wire endpoint resolved to a concrete component pin."""

    requested: str
    pin: PinRef
    exposed_net: str | None = None
    auto_selected: bool = False

    @property
    def node(self) -> str:
        """Return the physical graph node id for this endpoint."""

        return str(self.pin)


class RoutedWire(BaseModel):
    """One routed physical wire."""

    index: int
    requested_from: str
    requested_to: str
    from_pin: PinRef
    to_pin: PinRef
    from_auto_selected: bool = False
    to_auto_selected: bool = False
    from_exposed_net: str | None = None
    to_exposed_net: str | None = None
    explicit_net_name: str | None = None
    net_name: str | None = None
    wire_label: str | None = None
    awg: int = 20
    source_row_index: int | None = None
    source_segment_index: int | None = None
    source_route_length: int | None = None


class PinRouteStatus(BaseModel):
    """Routing status for a concrete component pin."""

    pin: PinRef
    connection_count: int
    is_routed: bool
    is_no_connect: bool
    exposed_nets: list[str] = Field(default_factory=list)


class WireRouter(BaseModel):
    """Stateful wire router that writes physical wires into a NetworkX graph."""

    components: dict[str, Component]
    physical_graph: nx.MultiGraph
    wiring_mode: WiringMode = "wires"
    visualization: VisualizationConfig = Field(default_factory=VisualizationConfig)
    default_awg: int = 20
    net_graph: nx.Graph = Field(default_factory=nx.Graph)
    no_connects: set[str] = Field(default_factory=set)
    allocations: dict[str, set[str]] = Field(default_factory=dict)
    routed_wires: list[RoutedWire] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_parse_result(
        cls,
        parse_result: ComponentParseResult,
        no_connects: Iterable[str] = (),
    ) -> "WireRouter":
        """Create a router from parsed components and the component-pin graph."""

        return cls(
            components=parse_result.components,
            physical_graph=parse_result.component_pin_graph.copy(),
            wiring_mode=parse_result.config.wiring_mode,
            visualization=parse_result.config.visualization,
            default_awg=parse_result.config.defaults.awg,
            no_connects={str(PinRef.parse(pin)) for pin in no_connects},
        )

    @classmethod
    def route_parse_result(cls, parse_result: ComponentParseResult) -> "WireRouter":
        """Route all wires from a parsed PanelViz document."""

        router = cls.from_parse_result(parse_result, no_connects=parse_result.no_connects)
        router.route_many(parse_result.wires)
        router.resolve_nets_and_labels(parse_result.config.wire_label_format)
        return router

    def route_many(self, wires: Iterable[Sequence[str] | Mapping[str, object] | WireSpec]) -> list[RoutedWire]:
        """Route many wire rows in input order, expanding route chains."""

        routed = []
        for wire in wires:
            wire_spec = self._coerce_wire_spec(wire)
            if wire_spec is None:
                raise RoutingError(f"Wire entries must have at least two endpoints: {wire!r}")
            route_length = len(wire_spec.route) - 1 if wire_spec.route is not None else 1
            for segment_index, (from_endpoint, to_endpoint) in enumerate(self._route_segments(wire_spec)):
                routed.append(
                    self.route_wire(
                        from_endpoint,
                        to_endpoint,
                        net_name=wire_spec.net_name,
                        awg=wire_spec.awg,
                        source_row_index=wire_spec.source_index,
                        source_segment_index=segment_index,
                        source_route_length=route_length,
                    )
                )
        return routed

    def route_wire(
        self,
        from_endpoint: str,
        to_endpoint: str,
        net_name: str | None = None,
        awg: int | None = None,
        source_row_index: int | None = None,
        source_segment_index: int | None = None,
        source_route_length: int | None = None,
    ) -> RoutedWire:
        """Resolve and add one physical wire to the graph."""

        from_resolved = self.resolve_endpoint(from_endpoint)
        to_resolved = self.resolve_endpoint(to_endpoint)
        self._consume_resolved_endpoint(from_resolved)
        self._consume_resolved_endpoint(to_resolved)

        wire = RoutedWire(
            index=len(self.routed_wires) + 1,
            requested_from=from_endpoint,
            requested_to=to_endpoint,
            from_pin=from_resolved.pin,
            to_pin=to_resolved.pin,
            from_auto_selected=from_resolved.auto_selected,
            to_auto_selected=to_resolved.auto_selected,
            from_exposed_net=from_resolved.exposed_net,
            to_exposed_net=to_resolved.exposed_net,
            explicit_net_name=net_name,
            awg=awg or self.default_awg,
            source_row_index=source_row_index,
            source_segment_index=source_segment_index,
            source_route_length=source_route_length,
        )
        self.routed_wires.append(wire)
        self.physical_graph.add_edge(
            str(wire.from_pin),
            str(wire.to_pin),
            key=wire.index,
            wire_index=wire.index,
            requested_from=wire.requested_from,
            requested_to=wire.requested_to,
            from_auto_selected=wire.from_auto_selected,
            to_auto_selected=wire.to_auto_selected,
            from_exposed_net=wire.from_exposed_net,
            to_exposed_net=wire.to_exposed_net,
            explicit_net_name=wire.explicit_net_name,
            net_name=wire.net_name,
            wire_label=wire.wire_label,
            awg=wire.awg,
            source_row_index=wire.source_row_index,
            source_segment_index=wire.source_segment_index,
            source_route_length=wire.source_route_length,
        )
        return wire

    def resolve_endpoint(self, endpoint: str) -> ResolvedEndpoint:
        """Resolve a DSL endpoint into a concrete pin."""

        pin_ref = PinRef.parse(endpoint)
        component = self._component(pin_ref.component)

        if component.has_pin(pin_ref.pin):
            return ResolvedEndpoint(
                requested=endpoint,
                pin=pin_ref,
                exposed_net=self._net_for_physical_pin(component, pin_ref.pin),
                auto_selected=False,
            )

        if component.exposes_net(pin_ref.pin):
            selected_pin = self.next_available_pin(component.name, pin_ref.pin)
            return ResolvedEndpoint(
                requested=endpoint,
                pin=PinRef(component=component.name, pin=selected_pin),
                exposed_net=pin_ref.pin,
                auto_selected=True,
            )

        raise RoutingError(f"Unknown pin or exposed net: {endpoint}")

    def next_available_pin(self, component_name: str, net_name: str) -> str:
        """Return the next unallocated concrete pin on a component's exposed net."""

        component = self._component(component_name)
        allocation_key = self._allocation_key(component_name, net_name)
        try:
            return component.next_available_pin(net_name, self.allocations.get(allocation_key, set()))
        except PinAllocationError as error:
            raise RoutingError(str(error)) from error

    def used_pins(self, component_name: str, net_name: str | None = None) -> set[str]:
        """Return pins consumed by auto-selection bookkeeping."""

        if net_name is not None:
            return set(self.allocations.get(self._allocation_key(component_name, net_name), set()))

        prefix = f"{component_name}."
        pins: set[str] = set()
        for key, allocated_pins in self.allocations.items():
            if key.startswith(prefix):
                pins.update(allocated_pins)
        return pins

    def pin_connection_counts(self) -> dict[str, int]:
        """Return physical wire connection counts by concrete pin node."""

        return {node: self.physical_graph.degree(node) for node in self.physical_graph.nodes}

    def pin_statuses(self, component: str | None = None) -> list[PinRouteStatus]:
        """Return routing status for concrete pins, optionally filtered by component."""

        statuses = []
        for node, attrs in self.physical_graph.nodes(data=True):
            if component is not None and attrs["component"] != component:
                continue
            pin = PinRef(component=attrs["component"], pin=attrs["pin"])
            connection_count = self.physical_graph.degree(node)
            statuses.append(
                PinRouteStatus(
                    pin=pin,
                    connection_count=connection_count,
                    is_routed=connection_count > 0,
                    is_no_connect=node in self.no_connects,
                    exposed_nets=list(attrs.get("exposed_nets", [])),
                )
            )
        return statuses

    def unrouted_pins(
        self,
        component: str | None = None,
        include_no_connects: bool = False,
    ) -> list[PinRef]:
        """Return pins with no physical wire edges."""

        return [
            status.pin
            for status in self.pin_statuses(component)
            if not status.is_routed and (include_no_connects or not status.is_no_connect)
        ]

    def resolve_nets_and_labels(self, wire_label_format: str = "%netname-%seq") -> None:
        """Resolve electrical nets and assign wire labels to routed wires."""

        electrical_graph = nx.Graph()
        electrical_graph.add_nodes_from(self.physical_graph.nodes)
        for from_node, to_node in self.physical_graph.edges(keys=False):
            electrical_graph.add_edge(from_node, to_node)

        for component in self.components.values():
            if isinstance(component, TerminalBlock):
                for pins in component.position_pin_groups():
                    electrical_graph.add_nodes_from(f"{component.name}.{pin}" for pin in pins)
                    for pin in pins[1:]:
                        electrical_graph.add_edge(
                            f"{component.name}.{pins[0]}",
                            f"{component.name}.{pin}",
                            internal=True,
                            terminal_position=True,
                        )
            for net_name in component.net_names():
                pins = [f"{component.name}.{pin}" for pin in component.pins_for_net(net_name)]
                if not pins:
                    continue
                electrical_graph.add_nodes_from(pins)
                for pin in pins[1:]:
                    electrical_graph.add_edge(pins[0], pin, internal=True, net_name=net_name)

        node_to_net = self._resolve_node_net_names(electrical_graph)
        sequence_by_net: dict[str, int] = defaultdict(int)
        global_sequence = 0
        self.net_graph = nx.Graph()

        for net_name in sorted(set(node_to_net.values())):
            members = sorted(node for node, node_net in node_to_net.items() if node_net == net_name)
            self.net_graph.add_node(net_name, name=net_name, member_pins=members)

        for wire in self.routed_wires:
            net_name = node_to_net[str(wire.from_pin)]
            global_sequence += 1
            sequence_by_net[net_name] += 1
            sequence = sequence_by_net[net_name] if "%netname" in wire_label_format else global_sequence
            wire.net_name = net_name
            wire.wire_label = format_wire_label(wire_label_format, net_name, sequence)
            self.physical_graph.edges[str(wire.from_pin), str(wire.to_pin), wire.index]["net_name"] = wire.net_name
            self.physical_graph.edges[str(wire.from_pin), str(wire.to_pin), wire.index]["wire_label"] = wire.wire_label

    def _resolve_node_net_names(self, electrical_graph: nx.Graph) -> dict[str, str]:
        node_to_net: dict[str, str] = {}
        wire_by_node = self._first_wire_by_node()

        for members in nx.connected_components(electrical_graph):
            member_set = set(members)
            explicit_net_names = {
                wire.explicit_net_name
                for node in member_set
                for wire in wire_by_node.get(node, [])
                if wire.explicit_net_name
            }
            candidate_net_names = {
                net_name
                for node in member_set
                for net_name in self.physical_graph.nodes[node].get("exposed_nets", [])
            }
            if len(explicit_net_names) > 1:
                raise RoutingError(f"Net conflict between wire-declared nets: {sorted(explicit_net_names)}")
            if len(candidate_net_names) > 1:
                raise RoutingError(f"Net conflict between named nets: {sorted(candidate_net_names)}")

            if explicit_net_names:
                net_name = next(iter(explicit_net_names))
            elif candidate_net_names:
                net_name = next(iter(candidate_net_names))
            else:
                first_wire = min(
                    (wire for node in member_set for wire in wire_by_node.get(node, [])),
                    key=lambda wire: wire.index,
                    default=None,
                )
                net_name = str(first_wire.from_pin) if first_wire else sorted(member_set)[0]

            for node in member_set:
                node_to_net[node] = net_name
        return node_to_net

    def _first_wire_by_node(self) -> dict[str, list[RoutedWire]]:
        wires_by_node: dict[str, list[RoutedWire]] = defaultdict(list)
        for wire in self.routed_wires:
            wires_by_node[str(wire.from_pin)].append(wire)
            wires_by_node[str(wire.to_pin)].append(wire)
        return wires_by_node

    def _consume_resolved_endpoint(self, endpoint: ResolvedEndpoint) -> None:
        if endpoint.node not in self.physical_graph:
            raise RoutingError(f"Resolved endpoint is not a graph node: {endpoint.node}")

        component = self._component(endpoint.pin.component)
        net_names = [endpoint.exposed_net] if endpoint.exposed_net else []
        if not endpoint.auto_selected:
            net_names.extend(self._nets_for_physical_pin(component, endpoint.pin.pin))

        for net_name in net_names:
            if net_name is None:
                continue
            self.allocations.setdefault(self._allocation_key(component.name, net_name), set()).add(endpoint.pin.pin)

    def _component(self, component_name: str) -> Component:
        try:
            return self.components[component_name]
        except KeyError as error:
            raise RoutingError(f"Unknown component: {component_name}") from error

    def _net_for_physical_pin(self, component: Component, pin: str) -> str | None:
        net_names = self._nets_for_physical_pin(component, pin)
        if not net_names:
            return None
        return net_names[0]

    def _nets_for_physical_pin(self, component: Component, pin: str) -> list[str]:
        net_names = []
        for net_name in component.net_names():
            if pin in component.pins_for_net(net_name):
                net_names.append(net_name)
        return net_names

    @staticmethod
    def _allocation_key(component_name: str, net_name: str) -> str:
        return f"{component_name}.{net_name}"

    def _route_segments(self, wire_spec: WireSpec) -> list[tuple[str, str]]:
        route = list(wire_spec.route) if wire_spec.route is not None else [wire_spec.from_endpoint, wire_spec.to_endpoint]
        if len(route) < 2:
            raise RoutingError(f"Wire routes must have at least two endpoints: {route!r}")

        segments = []
        for index in range(len(route) - 1):
            segments.append(
                (
                    self._route_endpoint_for_segment(route[index], index, route, outgoing=True),
                    self._route_endpoint_for_segment(route[index + 1], index + 1, route, outgoing=False),
                )
            )
        return segments

    def _route_endpoint_for_segment(
        self,
        endpoint: str | None,
        route_index: int,
        route: Sequence[str | None],
        *,
        outgoing: bool,
    ) -> str:
        if endpoint is None:
            raise RoutingError(f"Wire routes cannot contain empty endpoints: {route!r}")
        if not (0 < route_index < len(route) - 1):
            return endpoint

        pass_through = self._terminal_position_pass_through_endpoint(endpoint, outgoing=outgoing)
        return pass_through or endpoint

    def _terminal_position_pass_through_endpoint(self, endpoint: str, *, outgoing: bool) -> str | None:
        try:
            pin_ref = PinRef.parse(endpoint)
        except ValueError:
            return None

        component = self.components.get(pin_ref.component)
        if not isinstance(component, TerminalBlock) or not pin_ref.pin.isdigit():
            return None

        position = int(pin_ref.pin)
        if position < 1 or position > component.position_count():
            raise RoutingError(f"Terminal block position is out of range: {endpoint}")

        pins = component.position_pin_groups()[position - 1]
        if len(pins) < 2:
            raise RoutingError(f"Terminal block pass-through requires at least two pins at position: {endpoint}")
        return f"{component.name}.{pins[1 if outgoing else 0]}"

    @staticmethod
    def _coerce_wire_spec(wire: Sequence[str] | Mapping[str, object] | WireSpec) -> WireSpec | None:
        if isinstance(wire, WireSpec):
            return wire
        if isinstance(wire, Mapping):
            return WireSpec.model_validate(dict(wire))
        if len(wire) < 2:
            return None
        if len(wire) == 2:
            return WireSpec(from_endpoint=str(wire[0]), to_endpoint=str(wire[1]))
        return WireSpec(route=[str(endpoint) for endpoint in wire])


def allocation_snapshot(allocations: dict[str, set[str]]) -> dict[str, list[str]]:
    """Return allocations as sorted lists for reports and tests."""

    return {key: sorted(value) for key, value in allocations.items()}


def format_wire_label(wire_label_format: str, net_name: str, sequence: int) -> str:
    """Format a unique physical wire label."""

    label = wire_label_format.replace("%netname", net_name)

    def replace_padded(match: re.Match[str]) -> str:
        width = int(match.group(1))
        return f"{sequence:0{width}d}"

    label = re.sub(r"%\{(\d+)d\}seq", replace_padded, label)
    return label.replace("%seq", str(sequence))
