"""Drawing reference grid helpers."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceGrid:
    """Map canvas points into drawing reference cells."""

    x: float
    y: float
    width: float
    height: float
    columns: int
    rows: int

    @classmethod
    def from_bounds(
        cls,
        x: float,
        y: float,
        width: float,
        height: float,
        columns: int | None = None,
        rows: int | None = None,
    ) -> "ReferenceGrid":
        grid_width = max(1.0, float(width))
        grid_height = max(1.0, float(height))
        return cls(
            x=float(x),
            y=float(y),
            width=grid_width,
            height=grid_height,
            columns=columns or max(8, min(80, math.ceil(grid_width / 90))),
            rows=rows or max(4, min(26, math.ceil(grid_height / 90))),
        )

    @classmethod
    def from_bounds_dict(
        cls,
        bounds: dict[str, Any],
        columns: int | None = None,
        rows: int | None = None,
    ) -> "ReferenceGrid":
        return cls.from_bounds(
            float(bounds.get("x", 0)),
            float(bounds.get("y", 0)),
            float(bounds.get("width", 1)),
            float(bounds.get("height", 1)),
            columns=columns,
            rows=rows,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReferenceGrid":
        verticals = data.get("verticals") or []
        horizontals = data.get("horizontals") or []
        if len(verticals) >= 2 and len(horizontals) >= 2:
            return cls.from_bounds(
                float(verticals[0]),
                float(horizontals[0]),
                float(verticals[-1]) - float(verticals[0]),
                float(horizontals[-1]) - float(horizontals[0]),
                columns=int(data.get("columns") or len(verticals) - 1),
                rows=int(data.get("rows") or len(horizontals) - 1),
            )
        return cls.from_bounds(0, 0, 1, 1)

    @property
    def verticals(self) -> list[float]:
        col_w = self.width / self.columns
        return [self.x + index * col_w for index in range(self.columns + 1)]

    @property
    def horizontals(self) -> list[float]:
        row_h = self.height / self.rows
        return [self.y + index * row_h for index in range(self.rows + 1)]

    def reference_for(self, x: float, y: float) -> str:
        col_index = bisect_right(self.verticals, float(x)) - 1
        row_index = bisect_right(self.horizontals, float(y)) - 1
        col_index = max(0, min(self.columns - 1, col_index))
        row_index = max(0, min(self.rows - 1, row_index))
        return f"{chr(ord('A') + row_index)}{col_index + 1}"

    def to_dict(self) -> dict[str, Any]:
        verticals = self.verticals
        horizontals = self.horizontals
        labels = []
        for row_index in range(self.rows):
            row_label = chr(ord("A") + row_index)
            for col_index in range(self.columns):
                labels.append(
                    {
                        "ref": f"{row_label}{col_index + 1}",
                        "x": (verticals[col_index] + verticals[col_index + 1]) / 2,
                        "y": (horizontals[row_index] + horizontals[row_index + 1]) / 2,
                    }
                )
        return {
            "columns": self.columns,
            "rows": self.rows,
            "verticals": verticals,
            "horizontals": horizontals,
            "labels": labels,
        }


def attach_wire_references(data: dict[str, Any], grid: ReferenceGrid | None = None) -> dict[int | str, dict[str, str]]:
    """Add from/to drawing references to wire view rows and return a lookup."""

    if grid is None:
        if isinstance(data.get("reference_grid"), dict):
            grid = ReferenceGrid.from_dict(data["reference_grid"])
        else:
            grid = ReferenceGrid.from_bounds_dict(data.get("scene") or data.get("canvas") or {})

    refs: dict[int | str, dict[str, str]] = {}
    for wire in data.get("wires", []):
        wire_refs: dict[str, str] = {}
        for ref_key, endpoint in zip(("from", "to"), wire.get("endpoints", [])[:2]):
            point = endpoint.get("anchor", {})
            if "x" not in point or "y" not in point:
                continue
            wire_refs[ref_key] = grid.reference_for(float(point["x"]), float(point["y"]))
        wire["from_ref"] = wire_refs.get("from", "")
        wire["to_ref"] = wire_refs.get("to", "")
        if wire_refs:
            refs[int(wire.get("index", 0))] = wire_refs
            refs[str(wire.get("label", ""))] = wire_refs
    return refs
