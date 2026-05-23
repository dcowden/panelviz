import random
import re
import zlib
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
    wire_pdf_text = _pdf_stream_text(wire_list)
    schematic_pdf_text = _pdf_stream_text(schematic.content)
    assert "From Ref" in wire_pdf_text
    assert "To Ref" in wire_pdf_text
    assert "earth-1" in wire_pdf_text
    assert "0.0863 0.6392 0.2902 RG" in schematic_pdf_text


def _pdf_stream_text(content: bytes) -> str:
    parts = [content]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", content, flags=re.DOTALL):
        stream = match.group(1)
        try:
            parts.append(zlib.decompress(stream))
        except zlib.error:
            parts.append(stream)
    return b"\n".join(parts).decode("latin1", errors="ignore")
