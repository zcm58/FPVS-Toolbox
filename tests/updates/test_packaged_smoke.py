"""Packaged diagnostics and release gates, without creating a Qt application."""

from __future__ import annotations

import configparser
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from Main_App.diagnostics import packaged_smoke

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts" / "packaging"


def test_dependency_entrypoint_is_gui_free_and_isolates_user_settings(tmp_path: Path) -> None:
    settings = tmp_path / "user-settings" / "settings"
    settings.mkdir(parents=True)
    sentinel = settings / "settings.ini"
    sentinel.write_bytes(b"user settings must remain untouched")
    report = tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, str(REPO / "src/main.py"), "--packaging-check", str(report)],
        env=dict(os.environ, FPVS_CONFIG_HOME=str(settings.parent)),
        capture_output=True, text=True, timeout=90, check=False,
    )
    actual = json.loads(report.read_text())
    assert completed.returncode == 0, (actual, completed.stderr)
    assert actual["passed"] is True
    assert actual["frozen"] is False
    assert actual["gui_exercised"] is False
    assert actual["qt_widgets_loaded"] is False
    assert actual["version"] == actual["metadata_version"]
    assert set(actual["dependencies"]) == set(packaged_smoke.DEPENDENCY_IMPORTS)
    assert sentinel.read_bytes() == b"user settings must remain untouched"


def test_isolated_settings_seed_all_legacy_migration_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FPVS_CONFIG_HOME", "original-setting")
    with packaged_smoke.isolated_environment() as projects:
        root = Path(os.environ["FPVS_CONFIG_HOME"])
        config = configparser.ConfigParser()
        config.read(root / "settings/settings.ini")
        assert Path(config["paths"]["projectsRoot"]) == projects
        assert config["recent"]["projects"] == "[]"
        assert config["updates"]["last_checked_utc"]
        assert projects.is_dir()
    assert os.environ["FPVS_CONFIG_HOME"] == "original-setting"
    assert not root.exists()


def test_failed_dependency_reports_actionable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> dict:
        raise ModuleNotFoundError("missing scientific dependency")

    monkeypatch.setattr(packaged_smoke, "dependency_report", fail)
    report = tmp_path / "failed.json"
    assert packaged_smoke.run_check(report) == 1
    result = json.loads(report.read_text())
    assert result["passed"] is False
    assert "missing scientific dependency" in result["error"]


def test_mismatched_main_and_updater_versions_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Main_App.updates import application

    monkeypatch.setattr(application, "APP_VERSION", "0.0.0-invalid")
    monkeypatch.setattr(packaged_smoke, "dependency_report", lambda: {})
    report = tmp_path / "mismatch.json"
    assert packaged_smoke.run_check(report) == 1
    assert "differs from embedded updater metadata" in json.loads(report.read_text())["error"]


def test_visible_smoke_without_opt_in_fails_before_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FPVS_ALLOW_QT_TESTS", raising=False)
    monkeypatch.setattr(packaged_smoke, "dependency_report", lambda: pytest.fail("must not import"))
    report = tmp_path / "visible.json"
    assert packaged_smoke.run_check(report, visible=True) == 1
    assert "requires FPVS_ALLOW_QT_TESTS=1" in json.loads(report.read_text())["error"]


def _windows_version(version: str) -> str:
    spec = importlib.util.spec_from_file_location("metadata_smoke", SCRIPTS / "updater_metadata.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.windows_version(version)


@pytest.mark.parametrize(
    ("display", "numeric"),
    [("3.0.0", "3.0.0.0"), ("3.0.0rc1", "3.0.0.0"), ("3.1.dev2", "3.1.0.0"),
     ("3.0.0.post1", "3.0.0.0"), ("3.1.2.5", "3.1.2.5")],
)
def test_prerelease_labels_use_numeric_windows_version(display: str, numeric: str) -> None:
    assert _windows_version(display) == numeric


@pytest.mark.parametrize("display", ["65536.0.0", "1.2.3.4.5", "1!3.0.0", "not-a-version"])
def test_unrepresentable_windows_version_is_rejected(display: str) -> None:
    with pytest.raises(ValueError):
        _windows_version(display)


def test_missing_packaged_smoke_fails_instead_of_skipping(tmp_path: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell packaging gate requires PowerShell")
    command = r"""
$errors = $null
$tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SMOKE_BUILDER, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw 'Packaging script has syntax errors.' }
$function = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-PackagedSmoke' }, $true)
Invoke-Expression $function.Extent.Text
$SmokePackagedAppScript = $env:SMOKE_MISSING_SCRIPT
try { Invoke-PackagedSmoke; exit 3 } catch { if ($_.Exception.Message -notmatch 'smoke script was not found') { throw }; exit 0 }
"""
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        env=dict(os.environ, SMOKE_BUILDER=str(SCRIPTS / "build_installer.ps1"),
                 SMOKE_MISSING_SCRIPT=str(tmp_path / "absent.ps1")),
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "overrides",
    [{}, {"frozen": False}, {"version": "2.1.2"}, {"metadata_version": "2.1.2"},
     {"passed": False, "error": "missing module"}, {"executable": "wrong.exe"},
     {"gui_exercised": True}, {"network": True}, {"schema_version": 0}],
)
def test_powershell_smoke_validates_frozen_report_without_launching_any_app(
    tmp_path: Path, overrides: dict,
) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell packaging gate requires PowerShell")
    executable = tmp_path / "FPVS_Toolbox.exe"
    executable.write_text("inert fixture; Start-Process is replaced below")
    # Copy under a temporary repo layout so even generated report files are
    # private test output. The process mock only serializes a fixture report.
    scripts = tmp_path / "scripts/packaging"
    scripts.mkdir(parents=True)
    script = scripts / "smoke_packaged_app.ps1"
    shutil.copyfile(SCRIPTS / script.name, script)
    report = {
        "schema_version": 1, "mode": "dependencies", "frozen": True,
        "version": "3.0.0rc1", "metadata_version": "3.0.0rc1",
        "executable": str(executable), "passed": True, "network": False,
        "installer": False, "gui_exercised": False, "qt_widgets_loaded": False,
        **overrides,
    }
    command = r"""
function Start-Process {
    param($FilePath, $WindowStyle, [switch]$PassThru, $ArgumentList)
    if ($WindowStyle -ne 'Hidden' -or $ArgumentList[0] -ne '--packaging-check') { throw 'Unexpected process launch request.' }
    $path = $ArgumentList[1].Trim('"')
    [System.IO.File]::WriteAllText($path, $env:SMOKE_REPORT)
    $process = [pscustomobject]@{ ExitCode = 0 }
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($milliseconds) return $true }
    $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value { }
    return $process
}
try { & $env:SMOKE_SCRIPT -ExePath $env:SMOKE_EXE -ExpectedVersion '3.0.0rc1'; exit 0 } catch { Write-Output $_; exit 1 }
"""
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        env=dict(os.environ, SMOKE_SCRIPT=str(script), SMOKE_EXE=str(executable),
                 SMOKE_REPORT=json.dumps(report)),
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode == (1 if overrides else 0), completed.stdout + completed.stderr
