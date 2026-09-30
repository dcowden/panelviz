"""Compile the real sketch + Bounce2 and exercise its electrical I/O contract.

Use a C++ compiler shell (Developer Command Prompt for MSVC), then:
python tests/firmware/run_tests.py --bounce-dir <Bounce2>/src
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bounce-dir", type=Path, required=True)
    parser.add_argument("--compiler", default=None)
    args = parser.parse_args()
    compiler = args.compiler or shutil.which("c++") or shutil.which("cl")
    if not compiler:
        parser.error("C++ compiler not found; use a compiler environment or --compiler")
    here = Path(__file__).resolve().parent
    bounce = args.bounce_dir.resolve()
    scenarios = [
        ["held_at_boot"], ["disconnected_cp_cannot_latch"], ["cp_before_alarms"],
        ["alarms_before_cp"], ["release_with_alarm"], ["cp_loss_during_start"],
        ["blocked_press_not_queued"], ["upper_limit_during_start"],
        ["cp_fault_needs_fresh_press"], ["held_reset_cannot_retry"],
        ["cp_noise_debounce"], ["upper_relay_independent"],
        *[["fault_each_input", str(pin)] for pin in range(2, 10)],
    ]
    with tempfile.TemporaryDirectory(prefix="panelviz-firmware-") as tmp:
        exe = Path(tmp) / "controller_test.exe"
        sources = [str(here / "controller_test.cpp"), str(bounce / "Bounce2.cpp")]
        if Path(compiler).stem.lower() == "cl":
            command = [compiler, "/nologo", "/EHsc", "/std:c++14", "/W4",
                       "/DARDUINO=10819", f"/I{here}", f"/I{bounce}", *sources, f"/Fe:{exe}"]
        else:
            command = [compiler, "-std=c++14", "-Wall", "-Wextra", "-DARDUINO=10819",
                       f"-I{here}", f"-I{bounce}", *sources, "-o", str(exe)]
        subprocess.run(command, cwd=tmp, check=True)
        failures = 0
        for scenario in scenarios:
            failures += subprocess.run([str(exe), *scenario], check=False).returncode != 0
        print(f"{len(scenarios) - failures}/{len(scenarios)} scenarios passed")
        return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
