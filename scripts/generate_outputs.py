"""Generate stable example PanelViz outputs."""

from __future__ import annotations

from pathlib import Path

from panelviz.parser import parse_panel_yaml
from panelviz.routing import WireRouter
from panelviz.visualization import ApproximateTextMeasurer, write_wiring_diagram_svg


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "tests" / "outputs"
    output_dir.mkdir(exist_ok=True)

    parsed = parse_panel_yaml((root / "tests" / "fixtures" / "mycnc_valid.yml").read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    measurer = ApproximateTextMeasurer()

    write_wiring_diagram_svg(
        router,
        output_dir / "mycnc_wiring_diagram_labels.svg",
        units=parsed.config.units,
        columns=3,
        measurer=measurer,
        wiring_mode="labels",
    )
    write_wiring_diagram_svg(
        router,
        output_dir / "mycnc_wiring_diagram_wires.svg",
        units=parsed.config.units,
        columns=3,
        measurer=measurer,
        wiring_mode="wires",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
