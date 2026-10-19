"""An ownership move may retain existing recovery, but cannot add or change it."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from tests import repo_root


_PATH = repo_root() / ".agents/scripts/audit/agent_audit.py"
_SPEC = importlib.util.spec_from_file_location("agent_audit_owner_moves", _PATH)
agent_audit = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = agent_audit
_SPEC.loader.exec_module(agent_audit)

CURRENT = "src/Main_App/io/load_utils.py"
HISTORICAL = "src/Main_App/Shared/load_utils.py"
BOUNDARY = """def load():
    try:
        return read_source()
    except Exception:
        return None
"""
ALIAS = """import sys
from Main_App.io import load_utils as implementation
sys.modules[__name__] = implementation
"""


@pytest.fixture
def moved_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(agent_audit, "_tracked_and_untracked_files", lambda: ())

    def configure(current=BOUNDARY, *, baseline=BOUNDARY, historical=ALIAS, path=CURRENT):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(current, encoding="utf-8")
        previous = tmp_path / HISTORICAL
        if historical is not None:
            previous.parent.mkdir(parents=True, exist_ok=True)
            previous.write_text(historical, encoding="utf-8")
        monkeypatch.setattr(agent_audit, "_changed_files", lambda: (path,))
        monkeypatch.setattr(agent_audit, "_added_lines", lambda _path: list(enumerate(current.splitlines(), 1)))
        monkeypatch.setattr(agent_audit, "_file_text_at_comparison_ref", lambda original: baseline if original == HISTORICAL else "")
        return agent_audit.check_garbage_collection()

    return configure


@pytest.mark.parametrize("historical", [ALIAS, None])
def test_unchanged_owner_move_allows_only_existing_handler(moved_owner, historical):
    current = "# Ownership changed; recovery did not.\n\n" + BOUNDARY
    assert moved_owner(current, historical=historical) == []


@pytest.mark.parametrize("current", [
    BOUNDARY.replace("return None", "return False"),
    BOUNDARY.replace("read_source()", "read_other_source()"),
    BOUNDARY.replace("def load", "def unrelated_owner"),
    BOUNDARY + "    finally:\n        erase_source()\n",
    BOUNDARY.replace("return read_source()", "read_source()") + "    else:\n        publish()\n",
])
def test_changed_try_recovery_or_owner_is_not_an_unchanged_move(moved_owner, current):
    issues = moved_owner(current)
    assert len(issues) == 1
    assert issues[0].path == CURRENT
    assert "new broad exception handler" in issues[0].message


def test_added_different_boundary_is_rejected_while_original_remains_allowed(moved_owner):
    current = BOUNDARY + "\n" + BOUNDARY.replace("def load", "def another_operation")
    issues = moved_owner(current)
    assert len(issues) == 1
    assert issues[0].line == 10


def test_identical_duplicate_cannot_spend_the_same_baseline_twice(moved_owner):
    issues = moved_owner(BOUNDARY + "\n" + BOUNDARY)
    assert len(issues) == 1
    assert issues[0].line == 10


def test_existing_repeated_boundaries_have_only_their_original_multiplicity(moved_owner):
    issues = moved_owner(BOUNDARY * 3, baseline=BOUNDARY * 2)
    assert len(issues) == 1
    assert issues[0].line == 14


@pytest.mark.parametrize("historical", [BOUNDARY, BOUNDARY.replace("except Exception:", "except Exception as exc:")])
def test_retaining_implementation_in_historical_owner_rejects_duplicate_move(moved_owner, historical):
    issues = moved_owner(historical=historical)
    assert len(issues) == 1
    assert issues[0].line == 4


@pytest.mark.parametrize("baseline", ["", "def broken("])
def test_missing_or_invalid_baseline_fails_closed(moved_owner, baseline):
    assert len(moved_owner(baseline=baseline)) == 1


def test_invalid_current_source_does_not_receive_migration_exemption(moved_owner):
    assert len(moved_owner(BOUNDARY + "def broken(")) == 1


def test_unlisted_destination_does_not_receive_migration_exemption(moved_owner):
    issues = moved_owner(path="src/Main_App/io/unlisted.py")
    assert len(issues) == 1
    assert issues[0].path.endswith("unlisted.py")


def test_changed_second_handler_also_invalidates_its_enclosing_try(moved_owner):
    original = BOUNDARY.replace("    except Exception:", "    except ValueError:\n        return False\n    except Exception:")
    current = original.replace("return False", "return True")
    assert len(moved_owner(current, baseline=original)) == 1


def test_older_retired_path_baseline_keeps_existing_count_policy(tmp_path, monkeypatch):
    current, historical = next(iter(agent_audit.BROAD_EXCEPTION_BASELINES.items()))
    destination = tmp_path / current
    destination.parent.mkdir(parents=True)
    destination.write_text(BOUNDARY.replace("return None", "return False"), encoding="utf-8")
    monkeypatch.setattr(agent_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(agent_audit, "_file_text_at_comparison_ref", lambda path: BOUNDARY if path == historical else "")
    assert agent_audit._broad_exception_increase_allowed(current)
    destination.write_text(BOUNDARY * 2, encoding="utf-8")
    assert not agent_audit._broad_exception_increase_allowed(current)


def test_owner_move_map_has_one_canonical_destination_per_historical_module():
    historical = list(agent_audit.BROAD_EXCEPTION_OWNER_MOVES.values())
    assert len(historical) == len(set(historical))
    assert all(Path(path).suffix == ".py" for path in historical)
