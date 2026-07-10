from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from tests import repo_root


_AGENT_AUDIT_PATH = repo_root() / ".agents" / "scripts" / "audit" / "agent_audit.py"
_AGENT_AUDIT_SPEC = importlib.util.spec_from_file_location(
    "agent_audit_change_detection", _AGENT_AUDIT_PATH
)
agent_audit = importlib.util.module_from_spec(_AGENT_AUDIT_SPEC)
assert _AGENT_AUDIT_SPEC.loader is not None
sys.modules[_AGENT_AUDIT_SPEC.name] = agent_audit
_AGENT_AUDIT_SPEC.loader.exec_module(agent_audit)


@pytest.fixture(autouse=True)
def _reset_git_state(monkeypatch):
    monkeypatch.delenv(agent_audit.AUDIT_BASE_REF_ENV, raising=False)
    agent_audit._set_base_ref(None)
    yield
    agent_audit._set_base_ref(None)


def test_comparison_ref_prefers_cli_then_environment_then_head(monkeypatch):
    assert agent_audit._comparison_ref() == "HEAD"

    monkeypatch.setenv(agent_audit.AUDIT_BASE_REF_ENV, "origin/main")
    assert agent_audit._comparison_ref() == "origin/main"

    agent_audit._set_base_ref("abc123")
    assert agent_audit._comparison_ref() == "abc123"


def test_all_zero_ci_base_falls_back_to_local_head(monkeypatch):
    monkeypatch.setenv(agent_audit.AUDIT_BASE_REF_ENV, "0" * 40)

    assert agent_audit._comparison_ref() == "HEAD"


def test_changed_files_uses_selected_base_and_caches_git_inventory(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_git_lines(*args: str) -> list[str]:
        calls.append(args)
        if args == ("ls-files",):
            return ["src/tracked.py"]
        if args == ("ls-files", "--others", "--exclude-standard"):
            return ["src/untracked.py"]
        if args == ("diff", "--name-only", "base-sha", "--"):
            return ["src/changed.py"]
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(agent_audit, "_git_lines", fake_git_lines)
    agent_audit._set_base_ref("base-sha")

    assert agent_audit._tracked_and_untracked_files() == (
        "src/tracked.py",
        "src/untracked.py",
    )
    assert agent_audit._tracked_and_untracked_files() == (
        "src/tracked.py",
        "src/untracked.py",
    )
    assert agent_audit._changed_files() == (
        "src/changed.py",
        "src/untracked.py",
    )
    assert agent_audit._changed_files() == (
        "src/changed.py",
        "src/untracked.py",
    )

    assert calls.count(("ls-files",)) == 1
    assert calls.count(("ls-files", "--others", "--exclude-standard")) == 1
    assert calls.count(("diff", "--name-only", "base-sha", "--")) == 1


def test_added_lines_diffs_against_selected_base(tmp_path, monkeypatch):
    rel_path = "src/example.py"
    source_path = tmp_path / rel_path
    source_path.parent.mkdir(parents=True)
    source_path.write_text("old = False\nnew = True\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="@@ -1 +1,2 @@\n old = False\n+new = True\n",
            stderr="",
        )

    monkeypatch.setattr(agent_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(agent_audit, "_untracked_files", lambda: ())
    monkeypatch.setattr(agent_audit.subprocess, "run", fake_run)
    agent_audit._set_base_ref("base-sha")

    assert agent_audit._added_lines(rel_path) == [(2, "new = True")]
    assert agent_audit._added_lines(rel_path) == [(2, "new = True")]
    assert commands == [
        ["git", "diff", "--unified=0", "base-sha", "--", rel_path]
    ]


def test_parse_args_accepts_explicit_base_ref():
    args = agent_audit.parse_args(["--check", "paths", "--base-ref", "HEAD~2"])

    assert args.check == "paths"
    assert args.base_ref == "HEAD~2"


@pytest.mark.parametrize(
    ("attribute", "message"),
    (
        ("VERIFICATION_DRIVER", "missing executable verification driver"),
        ("VERIFICATION_CONFIG", "missing machine-readable verification routing map"),
    ),
)
def test_agent_harness_requires_verification_routing_files(
    tmp_path, monkeypatch, attribute, message
):
    monkeypatch.setattr(agent_audit, attribute, tmp_path / "missing")
    monkeypatch.setattr(agent_audit, "_tracked_and_untracked_files", lambda: ())

    issues = agent_audit.check_agent_harness()

    assert any(issue.message == message for issue in issues)


def test_agent_harness_runs_verification_config_validation(monkeypatch):
    command: list[str] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        return subprocess.CompletedProcess(
            args,
            2,
            stdout="",
            stderr="verification config error: broken route",
        )

    monkeypatch.setattr(agent_audit, "_tracked_and_untracked_files", lambda: ())
    monkeypatch.setattr(agent_audit.subprocess, "run", fake_run)

    issues = agent_audit.check_agent_harness()

    assert command[-1] == "--check-config"
    assert any(
        issue.message
        == "verification routing validation failed: verification config error: broken route"
        for issue in issues
    )
