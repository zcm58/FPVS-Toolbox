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


@pytest.mark.parametrize(
    "filename, target",
    [("test_window.py", "tests/gui/test_window.py"), ("window_test.py", "tests/gui")],
)
def test_validate_config_rejects_qt_test_in_local_bundle(
    tmp_path: Path, filename: str, target: str,
) -> None:
    qt_test = tmp_path / "tests" / "gui" / filename
    qt_test.parent.mkdir(parents=True)
    qt_test.write_text("def test_placeholder(): pass\n", encoding="utf-8")
    registry = tmp_path / "tests" / "qt_test_files.txt"
    registry.write_text(f"tests/gui/{filename}\n", encoding="utf-8")
    scope = verify.VerificationScope(
        name="gui",
        audits=("gui",),
        tests=(target,),
        include=("tests/gui/**",),
        manual_smoke=(),
    )

    errors = verify.validate_config({"gui": scope}, registry, repo_root=tmp_path)

    assert errors == [f"gui: focused local bundle includes Qt test: tests/gui/{filename}"]


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


def test_precommit_keeps_full_audit_and_all_active_changed_python_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)
    source = "src/Tools/Stats/analysis/example.py"
    (tmp_path / source).parent.mkdir(parents=True)
    (tmp_path / source).touch()
    scope = verify.VerificationScope(
        name="repo",
        audits=("agent-harness",),
        tests=("tests/audit/test_invariant.py",),
        include=(".agents/**",),
        manual_smoke=(),
    )

    commands = verify.build_commands(
        scope,
        tier="precommit",
        python=Path("python.exe"),
        changed=(source, "docs/agent/example.md"),
        qt_tests=frozenset(),
    )

    assert ["python.exe", "-m", "ruff", "check", "src/Tools/Stats/analysis/example.py"] in commands
    assert ["python.exe", "-m", "py_compile", "src/Tools/Stats/analysis/example.py"] in commands
    assert commands[0] == ["python.exe", str(verify.AGENT_AUDIT)]
    assert commands[-1] == ["python.exe", "-m", "pytest", "tests/audit/test_invariant.py", "-q"]


def test_precommit_adds_changed_tests_once_unless_a_configured_target_covers_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)
    paths = (
        "tests/test_configured.py",
        "tests/group/test_covered.py",
        "tests/test_added.py",
        "tests/other_added_test.py",
    )
    for path in paths:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).touch()
    scope = verify.VerificationScope(
        name="repo", audits=(),
        tests=("tests/test_configured.py", "tests/group", "tests/test_configured.py"),
        include=(), manual_smoke=(),
    )

    commands = verify.build_commands(
        scope, tier="precommit", python=Path("python.exe"),
        changed=(*paths, "tests\\test_added.py"), qt_tests=frozenset(),
    )

    assert commands[-1] == [
        "python.exe", "-m", "pytest", "tests/test_configured.py", "tests/group",
        "tests/other_added_test.py", "tests/test_added.py", "-q",
    ]


def test_precommit_never_executes_changed_qt_or_opt_in_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)
    monkeypatch.setenv(verify.QT_OPT_IN_ENV, "1")
    qt_path = "tests/test_window.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / qt_path).touch()
    opt_in_paths = (
        "src/Standalone_Scripts/test_private.py",
        "tests/standalone_scripts/test_private.py",
    )
    real_is_file = Path.is_file

    def checked_is_file(path: Path) -> bool:
        assert "Standalone_Scripts" not in path.parts
        assert "standalone_scripts" not in path.parts
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", checked_is_file)
    scope = verify.VerificationScope(
        name="repo", audits=(), tests=(), include=(), manual_smoke=(),
    )

    commands = verify.build_commands(
        scope, tier="precommit", python=Path("python.exe"),
        changed=(qt_path, *opt_in_paths), qt_tests=frozenset({qt_path}),
    )

    assert not any(command[1:3] == ["-m", "pytest"] for command in commands)
    assert all(path not in command for path in opt_in_paths for command in commands)


def test_precommit_empty_selection_never_launches_unscoped_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)
    helper = tmp_path / "tests/helper.py"
    helper.parent.mkdir()
    helper.touch()
    outside = tmp_path / "test_outside.py"
    outside.touch()
    scope = verify.VerificationScope(
        name="repo", audits=(), tests=(), include=(), manual_smoke=(),
    )

    commands = verify.build_commands(
        scope, tier="precommit", python=Path("python.exe"),
        changed=("tests/helper.py", "test_outside.py", "tests/test_deleted.py"),
        qt_tests=frozenset(),
    )

    assert not any(command[1:3] == ["-m", "pytest"] for command in commands)
    assert all("tests/test_deleted.py" not in command for command in commands)


def test_focused_tests_remain_configured_without_changed_test_expansion() -> None:
    scope = verify.VerificationScope(
        name="repo", audits=(), tests=("tests/test_configured.py",), include=(), manual_smoke=(),
    )

    commands = verify.build_commands(
        scope, tier="focused", python=Path("python.exe"),
        changed=("tests/test_added.py",), qt_tests=frozenset(),
    )

    assert commands == [["python.exe", "-m", "pytest", "tests/test_configured.py", "-q"]]


def test_main_uses_configured_qt_registry_for_changed_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)
    for name in ("test_window.py", "test_changed.py"):
        path = tmp_path / "tests" / name
        path.parent.mkdir(exist_ok=True)
        path.touch()
    registry = tmp_path / "qt_tests.txt"
    registry.write_text("tests/test_window.py\n", encoding="utf-8")
    scope = verify.VerificationScope(
        name="repo", audits=(), tests=(), include=(), manual_smoke=(),
    )
    monkeypatch.setattr(verify, "load_scopes", lambda: ({"repo": scope}, registry))
    validate = verify.validate_config
    monkeypatch.setattr(
        verify, "validate_config",
        lambda scopes, path: validate(scopes, path, repo_root=tmp_path),
    )
    monkeypatch.setattr(verify, "resolve_repo_python", lambda: Path("python.exe"))
    monkeypatch.setattr(verify, "changed_files", lambda: ("tests/test_window.py", "tests/test_changed.py"))
    captured = []

    def capture_commands(commands, *, list_only):
        assert list_only
        captured.extend(commands)
        return 0

    monkeypatch.setattr(verify, "run_commands", capture_commands)

    assert verify.main(["--scope", "repo", "--tier", "precommit", "--list"]) == 0
    assert captured[-1] == ["python.exe", "-m", "pytest", "tests/test_changed.py", "-q"]


def test_full_ci_excludes_opt_in_standalone_script_tests(monkeypatch) -> None:
    monkeypatch.setenv(verify.QT_OPT_IN_ENV, "1")
    scope = verify.VerificationScope(
        name="repo", audits=(), tests=(), include=(), manual_smoke=(),
    )
    commands = verify.build_commands(
        scope, tier="full-ci", python=Path("python.exe"), changed=(),
        qt_tests=frozenset(),
    )
    assert [
        "python.exe", "-m", "pytest", "--allow-qt-tests",
        "--ignore=tests/standalone_scripts", "-q",
    ] in commands


def test_full_ci_still_requires_explicit_qt_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(verify.QT_OPT_IN_ENV, raising=False)
    scope = verify.VerificationScope(
        name="repo", audits=(), tests=(), include=(), manual_smoke=(),
    )

    with pytest.raises(ValueError, match="full-ci requires"):
        verify.build_commands(
            scope, tier="full-ci", python=Path("python.exe"), changed=(), qt_tests=frozenset(),
        )
