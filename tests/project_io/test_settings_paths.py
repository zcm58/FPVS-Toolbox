"""Widget-free platform contracts for the app's remembered settings location."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.Shared import settings_paths


def _platform(monkeypatch, name: str, environ: dict[str, str]) -> None:
    # Replace only this module's OS lookup; do not change pathlib's host OS.
    monkeypatch.setattr(settings_paths, "os", SimpleNamespace(name=name, environ=environ))


@pytest.mark.parametrize("override", ["", "   ", "relative-config", " ./relative-config "])
def test_windows_override_and_localappdata_behavior_is_unchanged(
    tmp_path, monkeypatch, override: str,
) -> None:
    local_appdata = tmp_path / "local-app-data"
    _platform(
        monkeypatch,
        "nt",
        {
            "FPVS_CONFIG_HOME": override,
            "LOCALAPPDATA": f" {local_appdata} ",
            "XDG_CONFIG_HOME": str(tmp_path / "ignored-xdg"),
        },
    )
    expected_root = (
        Path(override.strip())
        if override.strip()
        else local_appdata / "FPVS Toolbox"
    )

    assert settings_paths.app_config_home() == expected_root
    assert settings_paths.app_settings_file(ensure_writable=False) == (
        expected_root / "settings" / "settings.ini"
    )
    assert settings_paths.app_plot_settings_file(ensure_writable=False) == (
        expected_root / "settings" / "plot_settings.ini"
    )
    assert settings_paths.app_logs_dir(ensure_writable=False) == expected_root / "logs"


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_absolute_override_keeps_precedence(tmp_path, monkeypatch, platform: str) -> None:
    override = tmp_path / "override"
    _platform(
        monkeypatch,
        platform,
        {
            "FPVS_CONFIG_HOME": f" {override} ",
            "LOCALAPPDATA": str(tmp_path / "local-app-data"),
            "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        },
    )

    assert settings_paths.app_config_home() == override


def test_windows_relative_localappdata_is_not_reinterpreted(monkeypatch) -> None:
    _platform(monkeypatch, "nt", {"LOCALAPPDATA": "relative-app-data"})

    assert settings_paths.app_config_home() == Path("relative-app-data") / "FPVS Toolbox"


@pytest.mark.parametrize("local_appdata", ["", "   "])
def test_windows_missing_localappdata_still_errors(
    tmp_path, monkeypatch, local_appdata: str,
) -> None:
    _platform(
        monkeypatch,
        "nt",
        {
            "LOCALAPPDATA": local_appdata,
            "XDG_CONFIG_HOME": str(tmp_path / "must-not-be-used"),
        },
    )

    with pytest.raises(settings_paths.SettingsPathError, match="%LOCALAPPDATA%"):
        settings_paths.app_config_home()


@pytest.mark.parametrize("xdg", ["", "   ", "relative-config", "./relative-config"])
def test_linux_xdg_fallback_is_stable_across_launch_directories(
    tmp_path, monkeypatch, xdg: str,
) -> None:
    home_dir = tmp_path / "home"
    monkeypatch.setattr(settings_paths.Path, "home", lambda: home_dir)
    _platform(monkeypatch, "posix", {"XDG_CONFIG_HOME": xdg})
    expected = home_dir / ".config" / "FPVS Toolbox" / "settings" / "settings.ini"

    for folder in (tmp_path / "launch-one", tmp_path / "launch-two"):
        folder.mkdir()
        monkeypatch.chdir(folder)
        assert settings_paths.app_settings_file(ensure_writable=False) == expected
    assert not home_dir.exists()


def test_linux_absolute_xdg_is_preserved(tmp_path, monkeypatch) -> None:
    configured = tmp_path / "xdg"
    _platform(monkeypatch, "posix", {"XDG_CONFIG_HOME": f" {configured} "})

    assert settings_paths.app_config_home() == configured / "FPVS Toolbox"


def test_linux_relative_explicit_override_becomes_absolute(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _platform(
        monkeypatch,
        "posix",
        {"FPVS_CONFIG_HOME": "fpvs-config", "XDG_CONFIG_HOME": "ignored-xdg"},
    )

    assert settings_paths.app_config_home() == tmp_path / "fpvs-config"
