import random
from pathlib import Path

from panelviz.parser import parse_panel_yaml
from panelviz.pdf_export import (
    DrawingMeta,
    _diagram_references,
    _schematic_geometry,
    _zone_ref,
    export_schematic_pdf,
    export_wire_list_pdf,
)
from panelviz.routing import WireRouter
from panelviz.viewer import viewer_data


VALID_PANEL = Path(__file__).resolve().parent / "fixtures" / "mycnc_valid.yml"


def test_schematic_references_track_both_wire_endpoints_for_random_sample():
    parsed = parse_panel_yaml(VALID_PANEL.read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    data = viewer_data(router, units=parsed.config.units, columns=3)
    geometry = _schematic_geometry(data)

    refs = _diagram_references(data, geometry)

    sample = random.Random(42).sample(data["wires"], 30)
    for wire in sample:
        expected_from = _zone_ref(wire["endpoints"][0]["anchor"]["x"], wire["endpoints"][0]["anchor"]["y"], geometry)
        expected_to = _zone_ref(wire["endpoints"][1]["anchor"]["x"], wire["endpoints"][1]["anchor"]["y"], geometry)
        assert refs[wire["index"]] == {"from": expected_from, "to": expected_to}
        assert refs[wire["label"]] == {"from": expected_from, "to": expected_to}


def test_wire_list_pdf_accepts_two_endpoint_references():
    parsed = parse_panel_yaml(VALID_PANEL.read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    data = viewer_data(router, units=parsed.config.units, columns=3)

    schematic = export_schematic_pdf(router, data, DrawingMeta(file_name="mycnc_valid.yml"))
    wire_list = export_wire_list_pdf(router, schematic.diagram_refs, DrawingMeta(file_name="mycnc_valid.yml"))

    assert schematic.content.startswith(b"%PDF-")
    assert wire_list.startswith(b"%PDF-")
    assert isinstance(next(iter(schematic.diagram_refs.values())), dict)
