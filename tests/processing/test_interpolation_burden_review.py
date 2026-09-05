from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.io.eeg_geometry import biosemi64_geometry_identity
from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_DECISION_EXCLUDE,
    INTERPOLATION_BURDEN_DECISION_RETAIN,
    INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
    INTERPOLATION_BURDEN_SCOPE_RECORDING,
    build_interpolation_burden,
)
from Main_App.processing.interpolation_burden_review import (
    InterpolationBurdenReviewChoice,
    InterpolationBurdenReviewError,
    apply_interpolation_burden_review,
    collect_interpolation_burden_review,
)
from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUS_SUCCEEDED,
    PROCESSING_STATUS_COMPLETED,
    build_preprocessing_outcome,
)
from Main_App.projects import Project, load_project_dataset_index


def _burden_payload(channel_count: int) -> dict[str, object]:
    channels = ("Fp1", "AF7", "AF3", "F1", "F3")[:channel_count]
    outcome = build_preprocessing_outcome(
        processing_status=PROCESSING_STATUS_COMPLETED,
        interpolation_status=INTERPOLATION_STATUS_SUCCEEDED,
        interpolation_requested_channels=channels,
        interpolation_successful_channels=channels,
    )
    return build_interpolation_burden(
        outcome,
        biosemi64_geometry_identity(),
    ).to_payload()


def _ordinary_project(root: Path) -> Project:
    root.mkdir(parents=True)
    return Project.load(root)


def _ordinary_ledger(*, channel_count: int = 4) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": {
            "P01": {
                "status": "completed",
                "participant_id": "P01",
                "interpolation_burden": _burden_payload(channel_count),
            }
        },
    }


def _choice(
    decision: str,
    *,
    scope: str = INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
) -> InterpolationBurdenReviewChoice:
    return InterpolationBurdenReviewChoice(
        decision=decision,
        reason="Reviewed the repaired electrode locations and donor coverage.",
        exclusion_scope=scope,
    )


def test_collect_uses_strict_above_five_percent_and_requires_explicit_choice(
    tmp_path: Path,
) -> None:
    project = _ordinary_project(tmp_path / "Project")

    below = collect_interpolation_burden_review(
        project,
        ledger=_ordinary_ledger(channel_count=3),
    )
    above = collect_interpolation_burden_review(
        project,
        ledger=_ordinary_ledger(channel_count=4),
    )

    assert below.requires_review is False
    assert below.flagged_recording_count == 0
    assert above.requires_review is True
    assert above.flagged_recording_count == 1
    assert above.items[0].default_scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
    with pytest.raises(InterpolationBurdenReviewError, match="[Ee]very pending"):
        apply_interpolation_burden_review(project, above, {})
    with pytest.raises(InterpolationBurdenReviewError, match="Choose Retain or Exclude"):
        InterpolationBurdenReviewChoice(
            decision="",
            reason="Reviewed.",
            exclusion_scope=INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
        )


def test_current_receipt_is_reused_and_changed_evidence_requires_review(
    tmp_path: Path,
) -> None:
    project = _ordinary_project(tmp_path / "Project")
    first = collect_interpolation_burden_review(project, ledger=_ordinary_ledger())
    apply_interpolation_burden_review(
        project,
        first,
        {"P01": _choice(INTERPOLATION_BURDEN_DECISION_RETAIN)},
    )

    current = collect_interpolation_burden_review(project, ledger=_ordinary_ledger())
    stale = collect_interpolation_burden_review(
        project,
        ledger=_ordinary_ledger(channel_count=5),
    )

    assert current.requires_review is False
    assert current.current_decision_count == 1
    assert stale.requires_review is True
    assert stale.stale_decision_count == 1
    assert stale.items[0].evidence_status == "stale"


@pytest.mark.parametrize("decision", [INTERPOLATION_BURDEN_DECISION_RETAIN, INTERPOLATION_BURDEN_DECISION_EXCLUDE])
@pytest.mark.parametrize("reason", ["", "  \t"])
def test_blank_comment_preserves_explicit_burden_decision_and_fingerprint(tmp_path, decision, reason):
    project = _ordinary_project(tmp_path / "Project")
    batch = collect_interpolation_burden_review(project, ledger=_ordinary_ledger())
    choice = InterpolationBurdenReviewChoice(decision, reason, INTERPOLATION_BURDEN_SCOPE_PARTICIPANT)
    applied = apply_interpolation_burden_review(project, batch, {"P01": choice})
    receipt = applied.decisions[0]
    assert receipt.reason == "No reason provided" and receipt.decision == decision
    assert applied.excluded_participants == (("P01",) if decision == INTERPOLATION_BURDEN_DECISION_EXCLUDE else ())
    reloaded = Project.load(project.project_root)
    saved = reloaded.preprocessing["interpolation_burden_review_decisions"]["P01"]
    assert saved["reason"] == "No reason provided" and saved["fingerprint"] == receipt.fingerprint
    assert not collect_interpolation_burden_review(reloaded, ledger=_ordinary_ledger()).requires_review


def test_retain_removes_only_a_qc07_owned_participant_exclusion(
    tmp_path: Path,
) -> None:
    project = _ordinary_project(tmp_path / "Project")
    first = collect_interpolation_burden_review(project, ledger=_ordinary_ledger())
    applied = apply_interpolation_burden_review(
        project,
        first,
        {"P01": _choice(INTERPOLATION_BURDEN_DECISION_EXCLUDE)},
    )
    receipt = applied.decisions[0]

    assert applied.excluded_participants == ("P01",)
    assert receipt.owns_canonical_exclusion is True
    assert receipt.exclusion_scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT

    changed = collect_interpolation_burden_review(
        project,
        ledger=_ordinary_ledger(channel_count=5),
    )
    retained = apply_interpolation_burden_review(
        project,
        changed,
        {"P01": _choice(INTERPOLATION_BURDEN_DECISION_RETAIN)},
    )

    assert retained.excluded_participants == ()
    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["manual_excluded_participants"] == []
    saved_receipt = reloaded.preprocessing["interpolation_burden_review_decisions"][
        "P01"
    ]
    assert saved_receipt["decision"] == INTERPOLATION_BURDEN_DECISION_RETAIN
    assert saved_receipt["owns_canonical_exclusion"] is False


def test_retain_preserves_an_unrelated_manual_exclusion(tmp_path: Path) -> None:
    project = _ordinary_project(tmp_path / "Project")
    preprocessing = dict(project.preprocessing)
    preprocessing["manual_excluded_participants"] = ["P01"]
    project.update_preprocessing(preprocessing)
    project.save()

    first = collect_interpolation_burden_review(project, ledger=_ordinary_ledger())
    excluded = apply_interpolation_burden_review(
        project,
        first,
        {"P01": _choice(INTERPOLATION_BURDEN_DECISION_EXCLUDE)},
    )
    assert excluded.decisions[0].owns_canonical_exclusion is False

    changed = collect_interpolation_burden_review(
        project,
        ledger=_ordinary_ledger(channel_count=5),
    )
    retained = apply_interpolation_burden_review(
        project,
        changed,
        {"P01": _choice(INTERPOLATION_BURDEN_DECISION_RETAIN)},
    )
    assert retained.excluded_participants == ("P01",)


def test_repeated_session_defaults_to_recording_and_keeps_sibling_available(
    tmp_path: Path,
) -> None:
    project = _repeated_project(tmp_path / "Repeated")
    excel_root = project.project_root / "1 - Excel Data Files" / "Faces" / "Group"
    excel_root.mkdir(parents=True)
    for index in (1, 2):
        (excel_root / f"P01__visit_{index}_Faces_Results.xlsx").write_text(
            "fixture",
            encoding="utf-8",
        )
    ledger = _repeated_ledger()
    batch = collect_interpolation_burden_review(project, ledger=ledger)

    assert batch.is_repeated_session is True
    assert [item.default_scope for item in batch.items] == [
        INTERPOLATION_BURDEN_SCOPE_RECORDING,
        INTERPOLATION_BURDEN_SCOPE_RECORDING,
    ]
    result = apply_interpolation_burden_review(
        project,
        batch,
        {
            "P01__visit_1": _choice(
                INTERPOLATION_BURDEN_DECISION_EXCLUDE,
                scope=INTERPOLATION_BURDEN_SCOPE_RECORDING,
            ),
            "P01__visit_2": _choice(
                INTERPOLATION_BURDEN_DECISION_RETAIN,
                scope=INTERPOLATION_BURDEN_SCOPE_RECORDING,
            ),
        },
    )

    assert result.excluded_participants == ()
    assert result.excluded_recordings == ("P01__visit_1",)
    assert "P01__visit_2" not in result.excluded_recordings
    index = load_project_dataset_index(project.project_root)
    assert index.recording_ids == ("P01__visit_2",)
    assert {row.recording_id for row in index.excluded_workbooks} == {
        "P01__visit_1"
    }


def test_repeated_session_allows_explicit_participant_scope(tmp_path: Path) -> None:
    project = _repeated_project(tmp_path / "Repeated")
    batch = collect_interpolation_burden_review(project, ledger=_repeated_ledger())

    result = apply_interpolation_burden_review(
        project,
        batch,
        {
            item.processing_id: _choice(
                INTERPOLATION_BURDEN_DECISION_EXCLUDE
                if item.processing_id.endswith("visit_1")
                else INTERPOLATION_BURDEN_DECISION_RETAIN,
                scope=(
                    INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
                    if item.processing_id.endswith("visit_1")
                    else INTERPOLATION_BURDEN_SCOPE_RECORDING
                ),
            )
            for item in batch.items
        },
    )

    assert result.excluded_participants == ("P01",)
    assert result.excluded_recordings == ()


def test_one_retain_does_not_remove_another_qc07_participant_exclusion(
    tmp_path: Path,
) -> None:
    project = _repeated_project(tmp_path / "Repeated")
    first = collect_interpolation_burden_review(project, ledger=_repeated_ledger())
    apply_interpolation_burden_review(
        project,
        first,
        {
            item.processing_id: _choice(
                INTERPOLATION_BURDEN_DECISION_EXCLUDE,
                scope=INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
            )
            for item in first.items
        },
    )
    changed_ledger = _repeated_ledger()
    changed_ledger["entries"]["P01__visit_1"]["interpolation_burden"] = (
        _burden_payload(5)
    )
    changed = collect_interpolation_burden_review(project, ledger=changed_ledger)

    assert [item.processing_id for item in changed.items] == ["P01__visit_1"]
    retained = apply_interpolation_burden_review(
        project,
        changed,
        {
            "P01__visit_1": _choice(
                INTERPOLATION_BURDEN_DECISION_RETAIN,
                scope=INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
            )
        },
    )

    assert retained.excluded_participants == ("P01",)


def test_malformed_ledger_burden_blocks_review_collection(tmp_path: Path) -> None:
    project = _ordinary_project(tmp_path / "Project")
    ledger = _ordinary_ledger()
    burden = ledger["entries"]["P01"]["interpolation_burden"]
    burden["fingerprint"] = "0" * 64

    with pytest.raises(InterpolationBurdenReviewError, match="fingerprint is stale"):
        collect_interpolation_burden_review(project, ledger=ledger)


def _repeated_project(root: Path) -> Project:
    root.mkdir(parents=True)
    manifest = {
        "schema_version": "2.2.0",
        "event_map": {"Faces": 1},
        "groups": {
            "group": {
                "label": "Group",
                "folder_name": "Group",
                "raw_input_folder": "Raw/Group",
            }
        },
        "participants": {"P01": {"group_id": "group"}},
        "sessions": {
            "visit_1": {"label": "Visit 1", "visit_index": 1},
            "visit_2": {"label": "Visit 2", "visit_index": 2},
        },
        "recording_sources": {
            "group_visit_1": {
                "group_id": "group",
                "session_id": "visit_1",
                "raw_input_folder": "Raw/Group/visit_1",
            },
            "group_visit_2": {
                "group_id": "group",
                "session_id": "visit_2",
                "raw_input_folder": "Raw/Group/visit_2",
            },
        },
        "recordings": {
            "P01__visit_1": {
                "participant_id": "P01",
                "session_id": "visit_1",
                "source_id": "group_visit_1",
                "raw_file": "Raw/Group/visit_1/P01.bdf",
                "visit_index": 1,
            },
            "P01__visit_2": {
                "participant_id": "P01",
                "session_id": "visit_2",
                "source_id": "group_visit_2",
                "raw_file": "Raw/Group/visit_2/P01.bdf",
                "visit_index": 2,
            },
        },
    }
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    return Project.load(root)


def _repeated_ledger() -> dict[str, object]:
    entries = {}
    for index in (1, 2):
        recording_id = f"P01__visit_{index}"
        entries[recording_id] = {
            "status": "completed",
            "participant_id": "P01",
            "recording_id": recording_id,
            "interpolation_burden": _burden_payload(4),
        }
    return {"schema_version": 1, "entries": entries}
