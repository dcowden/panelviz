"""Final wire-label assignment and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from panelviz.components import Component
from panelviz.routing import RoutedWire, WireRouter, format_wire_label


@dataclass(frozen=True)
class AssignedWireLabel:
    """A final label binding for one routed physical wire."""

    key: str
    label: str
    net: str
    from_pin: str
    to_pin: str
    assigned_component: str


@dataclass(frozen=True)
class LabelAssignment:
    """Final label assignment sidecar contents."""

    source: str
    component_order: list[str]
    wires: list[AssignedWireLabel]

    def label_by_key(self) -> dict[str, str]:
        return {wire.key: wire.label for wire in self.wires}


@dataclass(frozen=True)
class ComponentLabelRow:
    """One label row for a component label sheet."""

    label: str
    net: str
    component: str
    pin: str
    other_endpoint: str


def labels_path_for_panel(path: str | Path) -> Path:
    """Return the final label sidecar path for a panel YAML file."""

    panel_path = Path(path)
    return panel_path.with_name(f"{panel_path.stem}.labels.yaml")


def assign_labels(router: WireRouter, component_order: list[str], wire_label_format: str = "%netname-%seq") -> LabelAssignment:
    """Assign final labels by walking components in the requested order."""

    order = _complete_component_order(router, component_order)
    labels_by_wire: dict[str, AssignedWireLabel] = {}
    counters: dict[str, int] = {}

    for component_name in order:
        for wire in _wires_for_component(router, component_name):
            key = wire_key(wire)
            if key in labels_by_wire:
                continue
            net_name = wire.net_name or str(wire.from_pin)
            counters[net_name] = counters.get(net_name, 0) + 1
            labels_by_wire[key] = AssignedWireLabel(
                key=key,
                label=format_wire_label(wire_label_format, net_name, counters[net_name]),
                net=net_name,
                from_pin=str(wire.from_pin),
                to_pin=str(wire.to_pin),
                assigned_component=component_name,
            )

    return LabelAssignment(
        source="",
        component_order=order,
        wires=[labels_by_wire[wire_key(wire)] for wire in router.routed_wires if wire_key(wire) in labels_by_wire],
    )


def apply_label_assignment(router: WireRouter, assignment: LabelAssignment | None) -> None:
    """Apply final labels to a routed model in-place."""

    if assignment is None:
        return
    label_by_key = assignment.label_by_key()
    for wire in router.routed_wires:
        label = label_by_key.get(wire_key(wire))
        if not label:
            continue
        wire.wire_label = label
        edge = router.physical_graph.edges[str(wire.from_pin), str(wire.to_pin), wire.index]
        edge["wire_label"] = label


def load_label_assignment(path: str | Path) -> LabelAssignment | None:
    """Load a final label assignment sidecar if it exists."""

    label_path = Path(path)
    if not label_path.exists():
        return None
    yaml = YAML(typ="safe")
    data = yaml.load(label_path.read_text(encoding="utf-8")) or {}
    wires = [
        AssignedWireLabel(
            key=str(row["key"]),
            label=str(row["label"]),
            net=str(row.get("net") or ""),
            from_pin=str(row.get("from") or ""),
            to_pin=str(row.get("to") or ""),
            assigned_component=str(row.get("assigned_component") or ""),
        )
        for row in data.get("wires", [])
        if isinstance(row, dict) and row.get("key") and row.get("label")
    ]
    return LabelAssignment(
        source=str(data.get("source") or ""),
        component_order=[str(component) for component in data.get("component_order", [])],
        wires=wires,
    )


def save_label_assignment(source: str | Path, assignment: LabelAssignment) -> Path:
    """Save a final label assignment sidecar."""

    label_path = labels_path_for_panel(source)
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    data: dict[str, Any] = {
        "source": Path(source).name,
        "component_order": assignment.component_order,
        "wires": [
            {
                "key": wire.key,
                "label": wire.label,
                "net": wire.net,
                "from": wire.from_pin,
                "to": wire.to_pin,
                "assigned_component": wire.assigned_component,
            }
            for wire in assignment.wires
        ],
    }
    label_path.write_text(_dump_yaml(yaml, data), encoding="utf-8")
    return label_path


def component_label_rows(router: WireRouter, assignment: LabelAssignment) -> dict[str, list[ComponentLabelRow]]:
    """Return component-oriented label sheet rows."""

    label_by_key = assignment.label_by_key()
    rows: dict[str, list[ComponentLabelRow]] = {component: [] for component in assignment.component_order}
    for wire in router.routed_wires:
        label = label_by_key.get(wire_key(wire), wire.wire_label or f"wire-{wire.index}")
        endpoints = ((wire.from_pin, wire.to_pin), (wire.to_pin, wire.from_pin))
        for endpoint, other in endpoints:
            rows.setdefault(endpoint.component, []).append(
                ComponentLabelRow(
                    label=label,
                    net=wire.net_name or "",
                    component=endpoint.component,
                    pin=endpoint.pin,
                    other_endpoint=str(other),
                )
            )
    for component_name, component_rows in rows.items():
        component = router.components.get(component_name)
        if component is None:
            continue
        component_rows.sort(key=lambda row: (_pin_sort_index(component, row.pin), row.label))
    return rows


def wire_key(wire: RoutedWire) -> str:
    """Return a stable key for a routed wire segment."""

    if wire.source_row_index is not None and wire.source_segment_index is not None:
        return f"row:{wire.source_row_index}:segment:{wire.source_segment_index}"
    return f"wire:{wire.index}:{wire.from_pin}->{wire.to_pin}"


def _complete_component_order(router: WireRouter, component_order: list[str]) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    for component_name in component_order:
        if component_name in router.components and component_name not in seen:
            order.append(component_name)
            seen.add(component_name)
    for component_name in router.components:
        if component_name not in seen:
            order.append(component_name)
    return order


def _wires_for_component(router: WireRouter, component_name: str) -> list[RoutedWire]:
    component = router.components[component_name]
    wires = [
        wire
        for wire in router.routed_wires
        if wire.from_pin.component == component_name or wire.to_pin.component == component_name
    ]
    return sorted(wires, key=lambda wire: (_wire_component_pin_sort_key(component, component_name, wire), wire.index))


def _wire_component_pin_sort_key(component: Component, component_name: str, wire: RoutedWire) -> int:
    pin = wire.from_pin.pin if wire.from_pin.component == component_name else wire.to_pin.pin
    return _pin_sort_index(component, pin)


def _pin_sort_index(component: Component, pin: str) -> int:
    try:
        return component.physical_pins().index(pin)
    except ValueError:
        return len(component.physical_pins())


def _dump_yaml(yaml: YAML, data: dict[str, Any]) -> str:
    from io import StringIO

    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()
