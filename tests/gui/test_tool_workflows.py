import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 is required for GUI workflow tests", allow_module_level=True)

from Main_App.gui import tool_workflows


def test_open_plot_generator_uses_src_tool_entrypoint(tmp_path: Path, monkeypatch) -> None:
    calls = []
    project_root = tmp_path / "project"
    host = SimpleNamespace(currentProject=SimpleNamespace(project_root=project_root))

    def fake_popen(cmd, *, close_fds, env):
        calls.append((cmd, close_fds, env))

    monkeypatch.setattr(tool_workflows.subprocess, "Popen", fake_popen)

    tool_workflows.open_plot_generator(host, tmp_path)

    cmd, close_fds, env = calls[0]
    assert close_fds is True
    assert cmd == [
        sys.executable,
        str(tmp_path / "src" / "Tools" / "Plot_Generator" / "plot_generator.py"),
    ]
    assert env["FPVS_PROJECT_ROOT"] == str(project_root)


def test_open_image_resizer_uses_src_tool_entrypoint(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_popen(cmd, *, close_fds):
        calls.append((cmd, close_fds))

    monkeypatch.setattr(tool_workflows.subprocess, "Popen", fake_popen)

    tool_workflows.open_image_resizer(tmp_path)

    cmd, close_fds = calls[0]
    assert close_fds is True
    assert cmd == [
        sys.executable,
        str(tmp_path / "src" / "Tools" / "Image_Resizer" / "pyside_resizer.py"),
    ]
