from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from tests import repo_root

_VERIFY_PATH = repo_root() / ".agents" / "scripts" / "verify.py"
_VERIFY_SPEC = importlib.util.spec_from_file_location("agent_verify", _VERIFY_PATH)
assert _VERIFY_SPEC is not None and _VERIFY_SPEC.loader is not None
verify = importlib.util.module_from_spec(_VERIFY_SPEC)
sys.modules[_VERIFY_SPEC.name] = verify
_VERIFY_SPEC.loader.exec_module(verify)


def test_resolve_repo_python_prefers_venv1_then_venv(tmp_path: Path) -> None:
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    assert verify.resolve_repo_python(tmp_path) == venv_python

    venv1_python = tmp_path / ".venv1" / "Scripts" / "python.exe"
    venv1_python.parent.mkdir(parents=True)
    venv1_python.touch()
    assert verify.resolve_repo_python(tmp_path) == venv1_python


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv launchers are symlinks")
def test_resolve_repo_python_preserves_posix_venv_launcher(tmp_path: Path) -> None:
    interpreter = tmp_path / ".venv" / "bin" / "python3.13"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    launcher = interpreter.with_name("python")
    launcher.symlink_to(interpreter.name)

    assert verify.resolve_repo_python(tmp_path) == launcher
    assert verify.resolve_repo_python(tmp_path) != launcher.resolve()


def test_validate_config_rejects_qt_test_in_local_bundle(tmp_path: Path) -> None:
    qt_test = tmp_path / "tests" / "gui" / "test_window.py"
    qt_test.parent.mkdir(parents=True)
    qt_test.write_text("def test_placeholder(): pass\n", encoding="utf-8")
    registry = tmp_path / "tests" / "qt_test_files.txt"
    registry.write_text("tests/gui/test_window.py\n", encoding="utf-8")
    scope = verify.VerificationScope(
        name="gui",
        audits=("gui",),
        tests=("tests/gui/test_window.py",),
        include=("tests/gui/**",),
        manual_smoke=(),
    )

    errors = verify.validate_config({"gui": scope}, registry, repo_root=tmp_path)

    assert errors == ["gui: focused local bundle includes Qt test: tests/gui/test_window.py"]


def test_changed_files_omits_deleted_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = tmp_path / "src" / "kept.py"
    existing.parent.mkdir(parents=True)
    existing.touch()

    def fake_git_lines(_repo_root: Path, *args: str) -> list[str]:
        if args[:2] == ("diff", "--name-only"):
            return ["src/kept.py", "src/deleted.py"]
        return []

    monkeypatch.setattr(verify, "_git_lines", fake_git_lines)

    assert verify.changed_files(tmp_path) == ("src/kept.py",)


def test_precommit_lints_all_changed_python_files() -> None:
    scope = verify.VerificationScope(
        name="repo",
        audits=("agent-harness",),
        tests=(),
        include=(".agents/**",),
        manual_smoke=(),
    )

    commands = verify.build_commands(
        scope,
        tier="precommit",
        python=Path("python.exe"),
        changed=("src/Tools/Stats/analysis/example.py", "docs/agent/example.md"),
    )

    assert ["python.exe", "-m", "ruff", "check", "src/Tools/Stats/analysis/example.py"] in commands
    assert ["python.exe", "-m", "py_compile", "src/Tools/Stats/analysis/example.py"] in commands
    assert ["python.exe", "-m", "pytest", "-q"] in commands
