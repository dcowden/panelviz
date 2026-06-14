from pathlib import Path

from panelviz.label_assignment import (
    AssignedWireLabel,
    LabelAssignment,
    apply_label_assignment,
    assign_labels,
    component_label_rows,
    labels_path_for_panel,
    load_label_assignment,
    save_label_assignment,
    wire_key,
)
from panelviz.parser import parse_panel_yaml
from panelviz.routing import WireRouter


TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


def _router(text: str) -> WireRouter:
    return WireRouter.route_parse_result(parse_panel_yaml(text))


LABEL_YAML = """
components:
  first:
    type: connector
    pins:
      right: [A, B]
  second:
    type: connector
    pins:
      left: [A, B, C]
  third:
    type: connector
    pins:
      left: [A]
connections:
  wires:
    - {from: first.A, to: second.A, net: BUS}
    - {from: first.B, to: second.B, net: BUS}
    - {from: third.A, to: second.C, net: AUX}
"""


def test_assign_labels_walks_component_order_and_preserves_existing_wire_keys():
    router = _router(LABEL_YAML)

    assignment = assign_labels(router, ["second", "first"], "%netname-%seq")

    assert assignment.component_order == ["second", "first", "third"]
    assert [wire.label for wire in assignment.wires] == ["BUS-1", "BUS-2", "AUX-1"]
    assert [wire.key for wire in assignment.wires] == [wire_key(wire) for wire in router.routed_wires]
    assert assignment.wires[0].assigned_component == "second"


def test_apply_label_assignment_overrides_router_labels():
    router = _router(LABEL_YAML)
    assignment = assign_labels(router, ["third", "first"], "%netname-%seq")

    apply_label_assignment(router, assignment)

    assert [wire.wire_label for wire in router.routed_wires] == ["BUS-1", "BUS-2", "AUX-1"]
    assert router.physical_graph.edges["second.C", "third.A", 3]["wire_label"] == "AUX-1"


def test_apply_label_assignment_accepts_partial_or_missing_sidecar():
    router = _router(LABEL_YAML)
    first_key = wire_key(router.routed_wires[0])
    partial = LabelAssignment(
        source="panel.yml",
        component_order=["ghost", "first"],
        wires=[
            AssignedWireLabel(
                key=first_key,
                label="FINAL-1",
                net="BUS",
                from_pin="first.A",
                to_pin="second.A",
                assigned_component="first",
            )
        ],
    )

    apply_label_assignment(router, None)
    apply_label_assignment(router, partial)
    rows = component_label_rows(router, partial)

    assert router.routed_wires[0].wire_label == "FINAL-1"
    assert router.routed_wires[1].wire_label == "BUS-2"
    assert rows["ghost"] == []


def test_label_assignment_round_trips_to_panel_sidecar_path():
    TEST_OUTPUTS.mkdir(exist_ok=True)
    panel_path = TEST_OUTPUTS / "label_assignment_panel.yml"
    panel_path.write_text(LABEL_YAML, encoding="utf-8")
    router = _router(LABEL_YAML)
    assignment = assign_labels(router, ["third", "second"], "%netname-%seq")

    path = save_label_assignment(panel_path, assignment)
    loaded = load_label_assignment(path)

    assert path == labels_path_for_panel(panel_path)
    assert loaded is not None
    assert loaded.component_order == ["third", "second", "first"]
    assert loaded.label_by_key() == assignment.label_by_key()


def test_load_label_assignment_returns_none_for_missing_sidecar():
    assert load_label_assignment(TEST_OUTPUTS / "missing.labels.yaml") is None


def test_component_label_rows_include_one_row_for_each_wire_end():
    router = _router(LABEL_YAML)
    assignment = assign_labels(router, ["first", "second", "third"], "%netname-%seq")

    rows = component_label_rows(router, assignment)

    assert [row.label for row in rows["first"]] == ["BUS-1", "BUS-2"]
    assert [row.other_endpoint for row in rows["first"]] == ["second.A", "second.B"]
    assert [row.label for row in rows["second"]] == ["BUS-1", "BUS-2", "AUX-1"]
