from pathlib import Path

from panelviz import cli
from panelviz.cli import main, run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUTS = Path(__file__).resolve().parent / "outputs"


def test_cli_run_writes_required_outputs_to_selected_directory():
    output_dir = TEST_OUTPUTS / "cli_selected"

    outputs = run(PROJECT_ROOT / "mycnc.yml", output_dir)

    assert outputs == [
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


def test_cli_main_uses_current_directory_when_output_dir_is_omitted(monkeypatch, capsys):
    output_dir = TEST_OUTPUTS / "cli_default"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(output_dir)

    exit_code = main([str(PROJECT_ROOT / "mycnc.yml")])

    assert exit_code == 0
    assert (output_dir / "wire_list.csv").exists()
    assert (output_dir / "component_summary.txt").exists()
    assert (output_dir / "wiring_diagram.svg").exists()
    assert "wire_list.csv" in capsys.readouterr().out


def test_cli_view_writes_static_viewer_and_serves_selected_output_dir(monkeypatch):
    output_dir = TEST_OUTPUTS / "cli_view"
    served = []

    monkeypatch.setattr(cli, "serve_viewer", lambda path: served.append(path))

    exit_code = main(["--view", str(PROJECT_ROOT / "mycnc.yml"), str(output_dir)])

    assert exit_code == 0
    assert served == [output_dir]
    assert (output_dir / "viewer.html").exists()
    assert (output_dir / "viewer.js").exists()
    assert (output_dir / "panel-data.json").exists()
