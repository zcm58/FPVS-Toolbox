from __future__ import annotations

from scripts.audit import agent_audit


def test_stats_reporting_legibility_flags_oversized_reporting_module(tmp_path, monkeypatch):
    rel_path = "src/Tools/Stats/reporting/summary/big.py"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True)
    file_path.write_text("\n".join("x = 1" for _ in range(601)), encoding="utf-8")

    monkeypatch.setattr(agent_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(agent_audit, "_tracked_and_untracked_files", lambda: [rel_path])

    issues = agent_audit.check_stats_reporting_legibility()

    assert any(issue.check == "stats-reporting-legibility" for issue in issues)
    assert any("oversized" in issue.message for issue in issues)


def test_stats_reporting_legibility_flags_oversized_symbol(tmp_path, monkeypatch):
    rel_path = "src/Tools/Stats/reporting/summary/symbol.py"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        "def oversized():\n" + "\n".join("    value = 1" for _ in range(161)),
        encoding="utf-8",
    )

    monkeypatch.setattr(agent_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(agent_audit, "_tracked_and_untracked_files", lambda: [rel_path])

    issues = agent_audit.check_stats_reporting_legibility()

    assert any("oversized FunctionDef 'oversized'" in issue.message for issue in issues)


def test_stats_structure_flags_removed_stats_path_references(tmp_path, monkeypatch):
    rel_path = "tests/test_removed_stats_path.py"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True)
    removed_namespace = "Py" + "Side6"
    file_path.write_text(
        f'SUMMARY_PATH = ROOT / "src" / "Tools" / "Stats" / "{removed_namespace}" / "summary_utils.py"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(agent_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(agent_audit, "_tracked_and_untracked_files", lambda: [rel_path])

    issues = agent_audit.check_stats_structure()

    assert any(issue.check == "stats-structure" for issue in issues)
    assert any("removed Stats compatibility path reference" in issue.message for issue in issues)
