from pathlib import Path

from panelviz import cli
from panelviz.cli import main, run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"
VALID_PANEL = Path(__file__).resolve().parent / "fixtures" / "panel_valid.yml"


def test_cli_run_writes_required_outputs_to_selected_directory():
    output_dir = TEST_OUTPUTS / "cli_selected"

    outputs = run(VALID_PANEL, output_dir)

    assert outputs[:5] == [
        output_dir / "wire_list.csv",
        output_dir / "wire_list.txt",
        output_dir / "component_summary.csv",
        output_dir / "component_summary.txt",
        output_dir / "wiring_diagram.svg",
    ]
    for output in outputs:
        assert output.exists()

    assert "wirenumber,from_component,from_pin,to_component,to_pin,netname" in (
        output_dir / "wire_list.csv"
    ).read_text(encoding="utf-8")
    assert "contactor_110,switch,10" in (output_dir / "component_summary.csv").read_text(encoding="utf-8")
    assert 'aria-label="PanelViz wiring diagram"' in (output_dir / "wiring_diagram.svg").read_text(encoding="utf-8")
    assert 'class="wire-line wire-label-stub ' in (output_dir / "wiring_diagram.svg").read_text(encoding="utf-8")


def test_cli_run_writes_wire_label_pdfs_for_tagged_wires():
    output_dir = TEST_OUTPUTS / "cli_wire_labels"
    source = TEST_OUTPUTS / "cli_wire_labels.yml"
    source.write_text(
        """
components:
  source:
    type: connector
    tags: [row_a]
    size: {width: 1, height: 1}
    pins:
      right: [A]
  load:
    type: connector
    tags: [row_b]
    size: {width: 1, height: 1}
    pins:
      left: [A]
connections:
  wires:
    - {from: source.A, to: load.A, net: SIG}
""",
        encoding="utf-8",
    )

    outputs = run(source, output_dir)

    assert output_dir / "wirelabel_row_a.pdf" in outputs
    assert output_dir / "wirelabel_row_b.pdf" in outputs
    assert (output_dir / "wirelabel_row_a.pdf").read_bytes().startswith(b"%PDF-")


def test_run_uses_selected_output_directory():
    output_dir = TEST_OUTPUTS / "cli_default"
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = run(VALID_PANEL, output_dir)

    assert (output_dir / "wire_list.csv").exists()
    assert (output_dir / "component_summary.txt").exists()
    assert (output_dir / "wiring_diagram.svg").exists()
    assert output_dir / "wire_list.csv" in outputs


def test_cli_main_launches_web_app_by_default(monkeypatch):
    launched = []

    monkeypatch.setattr(cli, "run_editor", lambda path, port, open_browser: launched.append((path, port, open_browser)))

    exit_code = main([str(VALID_PANEL)])

    assert exit_code == 0
    assert launched == [(str(VALID_PANEL), 8769, True)]


def test_cli_port_and_no_open_control_default_web_app(monkeypatch):
    launched = []

    monkeypatch.setattr(cli, "run_editor", lambda path, port, open_browser: launched.append((path, port, open_browser)))

    exit_code = main(["--port", "8768", "--no-open", str(VALID_PANEL)])

    assert exit_code == 0
    assert launched == [(str(VALID_PANEL), 8768, False)]
