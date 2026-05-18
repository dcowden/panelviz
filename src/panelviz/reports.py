"""Report helpers for routed PanelViz data."""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel
from tabulate import tabulate

from panelviz.routing import WireRouter


class WireListRow(BaseModel):
    """One row in the required wire list output."""

    wirenumber: str
    from_component: str
    from_pin: str
    to_component: str
    to_pin: str
    netname: str
    awg: int


WIRE_LIST_COLUMNS = ["wirenumber", "from_component", "from_pin", "to_component", "to_pin", "netname", "awg"]


class ComponentSummaryRow(BaseModel):
    """One row in the component summary output."""

    component: str
    type: str
    pins: int
    unconnected_pins: str
    no_connects: str
    multi_connected_pins: str
    warnings: str


COMPONENT_SUMMARY_COLUMNS = [
    "component",
    "type",
    "pins",
    "unconnected_pins",
    "no_connects",
    "multi_connected_pins",
    "warnings",
]


def wire_list_rows(router: WireRouter, grouped: bool = True) -> list[WireListRow]:
    """Return routed wires in the required wire-list shape."""

    wires = router.routed_wires
    if grouped:
        wires = sorted(wires, key=lambda wire: (wire.net_name or "", wire.index))

    return [
        WireListRow(
            wirenumber=wire.wire_label or "",
            from_component=wire.from_pin.component,
            from_pin=wire.from_pin.pin,
            to_component=wire.to_pin.component,
            to_pin=wire.to_pin.pin,
            netname=wire.net_name or "",
            awg=wire.awg,
        )
        for wire in wires
    ]


def wire_list_table(router: WireRouter, grouped: bool = True, tablefmt: str = "github") -> str:
    """Return a pretty table for the required wire list."""

    rows = [row.model_dump() for row in wire_list_rows(router, grouped=grouped)]
    return tabulate(rows, headers="keys", tablefmt=tablefmt)


def write_wire_list_csv(router: WireRouter, path: str | Path, grouped: bool = True) -> Path:
    """Write the required wire list as CSV."""

    output_path = Path(path)
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=WIRE_LIST_COLUMNS)
        writer.writeheader()
        writer.writerows(row.model_dump() for row in wire_list_rows(router, grouped=grouped))
    return output_path


def component_summary_rows(router: WireRouter) -> list[ComponentSummaryRow]:
    """Return component summary rows with warning-oriented pin status."""

    rows: list[ComponentSummaryRow] = []
    for name, component in router.components.items():
        statuses = router.pin_statuses(name)
        unconnected = [status.pin.pin for status in statuses if not status.is_routed and not status.is_no_connect]
        no_connects = [status.pin.pin for status in statuses if status.is_no_connect]
        multi_connected = [
            f"{status.pin.pin} ({status.connection_count})"
            for status in statuses
            if status.connection_count > 1
        ]
        warnings = []
        if unconnected:
            warnings.append(f"{len(unconnected)} unconnected")
        if multi_connected:
            warnings.append(f"{len(multi_connected)} multi-connected")

        rows.append(
            ComponentSummaryRow(
                component=name,
                type=component.type.value,
                pins=len(component.physical_pins()),
                unconnected_pins=_list_or_dash(unconnected),
                no_connects=_list_or_dash(no_connects),
                multi_connected_pins=_list_or_dash(multi_connected),
                warnings="; ".join(warnings) or "-",
            )
        )
    return rows


def component_summary_table(router: WireRouter, tablefmt: str = "github") -> str:
    """Return a pretty table for component warnings and pin status."""

    rows = [row.model_dump() for row in component_summary_rows(router)]
    return tabulate(rows, headers="keys", tablefmt=tablefmt)


def write_component_summary_csv(router: WireRouter, path: str | Path) -> Path:
    """Write the component summary as CSV."""

    output_path = Path(path)
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=COMPONENT_SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(row.model_dump() for row in component_summary_rows(router))
    return output_path


def _list_or_dash(values: list[str]) -> str:
    return ", ".join(values) if values else "-"
