"""Command-line entry point for PanelViz."""

from __future__ import annotations

import argparse
import functools
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from panelviz.label_assignment import apply_label_assignment, labels_path_for_panel, load_label_assignment
from panelviz.editor import run_editor
from panelviz.parser import parse_panel_yaml
from panelviz.reports import (
    component_summary_table,
    wire_list_table,
    write_component_summary_csv,
    write_wire_list_csv,
)
from panelviz.routing import WireRouter
from panelviz.viewer import write_static_viewer
from panelviz.visualization import component_visual_config_from_visualization, write_wiring_diagram_svg
from panelviz.wire_labels import write_wire_label_pdfs


def build_parser() -> argparse.ArgumentParser:
    """Build the PanelViz argument parser."""

    parser = argparse.ArgumentParser(description="Generate PanelViz wiring documentation.")
    parser.add_argument(
        "--port",
        type=int,
        default=8769,
        help="Localhost port for the PanelViz web app. Defaults to 8769.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser automatically.",
    )
    parser.add_argument("input_file", help="PanelViz YAML input file")
    return parser


def run(input_file: str | Path, output_dir: str | Path = ".", include_viewer: bool = False) -> list[Path]:
    """Generate the diagram, wire list, and component summary files."""

    input_path = Path(input_file)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    parsed = parse_panel_yaml(input_path.read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
    apply_label_assignment(router, load_label_assignment(labels_path_for_panel(input_path)))
    visual_config = component_visual_config_from_visualization(parsed.config.visualization)

    outputs = [
        write_wire_list_csv(router, destination / "wire_list.csv"),
        _write_text(destination / "wire_list.txt", wire_list_table(router) + "\n"),
        write_component_summary_csv(router, destination / "component_summary.csv"),
        _write_text(destination / "component_summary.txt", component_summary_table(router) + "\n"),
        write_wiring_diagram_svg(
            router,
            destination / "wiring_diagram.svg",
            units=parsed.config.units,
            config=visual_config,
            wiring_mode="labels",
        ),
    ]
    outputs.extend(write_wire_label_pdfs(router, destination, parsed.config.labels))
    if include_viewer:
        outputs.extend(write_static_viewer(router, destination, units=parsed.config.units, columns=3, config=visual_config))
    return outputs


def main(argv: list[str] | None = None) -> int:
    """Run the PanelViz CLI."""

    args = build_parser().parse_args(argv)
    run_editor(args.input_file, port=args.port, open_browser=not args.no_open)
    return 0


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def serve_viewer(output_dir: Path, port: int = 0) -> None:  # pragma: no cover - blocking local UI helper
    """Serve the generated static viewer and open it in the browser."""

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(output_dir))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{server.server_port}/viewer.html"
    print(f"Serving PanelViz viewer at {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
