"""The independent helper's diagnostic mode must work without importing the GUI."""

import json
import subprocess
import sys


def test_packaging_check_is_headless_and_reports_protocol(tmp_path):
    report = tmp_path / "updater-report.json"
    process = subprocess.run(
        [sys.executable, "-m", "Main_App.updater_main", "--packaging-check", str(report)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["protocol_version"] == 1
    assert result["gui_loaded"] is False
    assert result["analysis_loaded"] is False
    assert result["frozen"] is False
    assert result["version"]
