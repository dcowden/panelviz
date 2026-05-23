"""Command-line entry point for PanelViz."""

from __future__ import annotations

import argparse
import functools
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def build_parser() -> argparse.ArgumentParser:
    """Build the PanelViz argument parser."""

    parser = argparse.ArgumentParser(description="Generate PanelViz wiring documentation.")
    parser.add_argument(
        "--view",
        action="store_true",
        help="Generate and launch the interactive static viewer.",
    )
    parser.add_argument(
        "--edit",
        action="store_true",
        help="Launch the local NiceGUI YAML wire editor.",
    )
    parser.add_argument(
        "--edit-port",
        type=int,
        default=8769,
        help="Localhost port to use with --edit. Defaults to 8769.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser automatically with --edit.",
    )
    parser.add_argument("input_file", help="PanelViz YAML input file")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Output directory. Defaults to the current working directory.",
    )
    return parser


def run(input_file: str | Path, output_dir: str | Path = ".", include_viewer: bool = False) -> list[Path]:
    """Generate the diagram, wire list, and component summary files."""

    input_path = Path(input_file)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    parsed = parse_panel_yaml(input_path.read_text(encoding="utf-8"))
    router = WireRouter.route_parse_result(parsed)
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
    if include_viewer:
        outputs.extend(write_static_viewer(router, destination, units=parsed.config.units, columns=3, config=visual_config))
    return outputs


def main(argv: list[str] | None = None) -> int:
    """Run the PanelViz CLI."""

    args = build_parser().parse_args(argv)
    if args.edit:
        run_editor(args.input_file, port=args.edit_port, open_browser=not args.no_open)
        return 0

    outputs = run(args.input_file, args.output_dir, include_viewer=args.view)
    for output in outputs:
        print(output)
    if args.view:
        serve_viewer(Path(args.output_dir))
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
