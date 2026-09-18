"""Keep every updater fixture away from the user's cache and installed app."""
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_updater_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "settings"))
    source = Path(__file__).resolve().parents[2] / "src"
    monkeypatch.setenv("PYTHONPATH", str(source) + os.pathsep + os.environ.get("PYTHONPATH", ""))
