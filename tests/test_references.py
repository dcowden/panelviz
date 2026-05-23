from panelviz.references import ReferenceGrid, attach_wire_references


def test_reference_grid_maps_canvas_points_to_cells():
    grid = ReferenceGrid.from_bounds(x=100, y=200, width=400, height=300, columns=4, rows=3)

    assert grid.reference_for(100, 200) == "A1"
    assert grid.reference_for(199.9, 299.9) == "A1"
    assert grid.reference_for(200, 200) == "A2"
    assert grid.reference_for(499.9, 499.9) == "C4"
    assert grid.reference_for(-999, -999) == "A1"
    assert grid.reference_for(999, 999) == "C4"


def test_reference_grid_round_trips_dict_shape():
    grid = ReferenceGrid.from_bounds(x=-50, y=25, width=300, height=200, columns=6, rows=4)
    restored = ReferenceGrid.from_dict(grid.to_dict())

    assert restored == grid
    assert restored.reference_for(0, 25) == grid.reference_for(0, 25)


def test_attach_wire_references_adds_from_and_to_refs_to_wire_data():
    data = {
        "wires": [
            {
                "index": 1,
                "label": "W1",
                "endpoints": [
                    {"anchor": {"x": 10, "y": 10}},
                    {"anchor": {"x": 90, "y": 90}},
                ],
            }
        ]
    }
    grid = ReferenceGrid.from_bounds(x=0, y=0, width=100, height=100, columns=2, rows=2)

    refs = attach_wire_references(data, grid)

    assert data["wires"][0]["from_ref"] == "A1"
    assert data["wires"][0]["to_ref"] == "B2"
    assert refs[1] == {"from": "A1", "to": "B2"}
    assert refs["W1"] == {"from": "A1", "to": "B2"}
