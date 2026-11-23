import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from smart_elevator.__main__ import main

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize("options", [[], ["--allocator", "insertion"], ["--allocator", "baseline"]])
def test_headless_entry_point(options: list[str]) -> None:
    env = os.environ.copy()
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    result = subprocess.run(
        [
            sys.executable, "-m", "smart_elevator", str(EXAMPLES / "explicit.json"),
            "--headless", *options,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "completed_count": 1,
        "total_journey_ms": 3500,
        "mean_journey_ms": 3500,
        "mean_wait_ms": 0,
        "max_journey_ms": 3500,
    }


def test_headless_generated_scenario_without_tkinter(monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "tkinter", None)
    args = ["--headless", str(EXAMPLES / "generated.json")]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["completed_count"] == 20
    assert main(args) == 0
    assert capsys.readouterr().out == output


def test_headless_invalid_scenario(tmp_path, capsys) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--headless", str(path)])
    assert exc.value.code == 1
    assert "schema_version" in capsys.readouterr().err
