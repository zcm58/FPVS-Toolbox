from __future__ import annotations

import json
from pathlib import Path

import pytest

import Main_App.processing.artifact_freshness as freshness_module
from Main_App.processing.artifact_freshness import (
    ANALYSIS_READY_FULL_AUDIT_ARTIFACT,
    ARTIFACT_STATUS_CURRENT,
    ARTIFACT_STATUS_FAILED,
    ARTIFACT_STATUS_STALE,
    SELECTION_DEPENDENT_ARTIFACTS,
    STATS_READY_SUMMED_BCA_ARTIFACT,
    activate_selection_freshness,
    canonical_artifact_path,
    load_active_selection_fingerprint,
    load_artifact_freshness_registry,
    mark_artifact_current,
    mark_artifact_failed,
    mark_selection_derivatives_stale,
    preserve_artifact_for_rebuild,
    require_current_artifact,
    selection_dependent_artifacts_are_current,
    selection_fingerprint_from_metadata,
)


def _project(tmp_path: Path, payload: dict | None = None) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps(payload or {"schema_version": "2.1.0"}),
        encoding="utf-8",
    )
    return root


def _summary(root: Path, text: str = "selection") -> Path:
    path = root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_canonical_selection_fingerprint_is_required_for_new_metadata() -> None:
    metadata = {
        "selection_fingerprint": "selection-v1-abc",
        "selection_cache_key": "old-cache-key",
    }

    assert selection_fingerprint_from_metadata(metadata) == "selection-v1-abc"
    with pytest.raises(ValueError, match="selection_fingerprint"):
        selection_fingerprint_from_metadata(
            {"selection_cache_key": "old-cache-key"},
            allow_legacy_migration=False,
        )


def test_legacy_selection_fingerprint_fallback_is_stable_and_ignores_cache_state() -> None:
    first = selection_fingerprint_from_metadata(
        {
            "selected_harmonics_hz": [1.2, 2.4],
            "selection_cache_saved_at": "2026-01-01T00:00:00Z",
        }
    )
    second = selection_fingerprint_from_metadata(
        {
            "selection_cache_saved_at": "2026-08-01T00:00:00Z",
            "selected_harmonics_hz": [1.2, 2.4],
        }
    )

    assert first == second
    assert first.startswith("legacy-metadata:")


def test_load_active_fingerprint_migrates_read_only_from_latest_legacy_cache(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path,
        {
            "tools": {
                "stats": {
                    "group_significant_harmonics_cache": {
                        "entries": {
                            "older": {
                                "saved_at": "2026-01-01T00:00:00Z",
                                "selection_metadata": {
                                    "selection_cache_key": "older"
                                },
                            },
                            "newer": {
                                "saved_at": "2026-02-01T00:00:00Z",
                                "selection_metadata": {
                                    "selection_cache_key": "newer"
                                },
                            },
                        }
                    }
                }
            }
        },
    )
    original = (root / "project.json").read_text(encoding="utf-8")

    assert load_active_selection_fingerprint(root) == "legacy-cache:newer"
    assert (root / "project.json").read_text(encoding="utf-8") == original


def test_load_active_fingerprint_prefers_processing_owned_selection(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path,
        {
            "tools": {
                "processing": {
                    "harmonic_selection": {
                        "active": {
                            "selection_fingerprint": "processing-current",
                        }
                    }
                },
                "stats": {
                    "group_significant_harmonics_cache": {
                        "entries": {
                            "legacy": {
                                "saved_at": "2026-08-01T00:00:00Z",
                                "selection_metadata": {
                                    "selection_cache_key": "legacy"
                                },
                            }
                        }
                    }
                },
            }
        },
    )

    assert load_active_selection_fingerprint(root) == "processing-current"


def test_changed_selection_marks_only_summed_bca_derivatives_stale(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    summary = _summary(root)

    first = activate_selection_freshness(
        root,
        {"selection_fingerprint": "first"},
        selection_summary_path=summary,
    )
    assert first.changed is True

    stats_path = root / "3 - Statistical Analysis Results" / "Stats_Ready_Summed_BCA.xlsx"
    stats_path.parent.mkdir(parents=True)
    stats_path.write_text("first stats", encoding="utf-8")
    mark_artifact_current(root, STATS_READY_SUMMED_BCA_ARTIFACT, stats_path, "first")

    second = activate_selection_freshness(
        root,
        {"selection_fingerprint": "second"},
        selection_summary_path=summary,
    )
    registry = load_artifact_freshness_registry(root)

    assert second.changed is True
    assert set(second.stale_artifact_ids) == set(SELECTION_DEPENDENT_ARTIFACTS)
    assert registry.selection_fingerprint == "second"
    assert all(
        registry.artifacts[artifact_id].status == ARTIFACT_STATUS_STALE
        for artifact_id in SELECTION_DEPENDENT_ARTIFACTS
    )
    assert (
        registry.artifacts[STATS_READY_SUMMED_BCA_ARTIFACT].built_from_selection_fingerprint
        == "first"
    )
    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert "preprocessing" not in manifest.get("tools", {}).get("post_processing", {})
    assert "full_fft" not in manifest.get("tools", {}).get("post_processing", {})
    assert stats_path.read_text(encoding="utf-8") == "first stats"


def test_identical_selection_does_not_invalidate_current_derivative(tmp_path: Path) -> None:
    root = _project(tmp_path)
    summary = _summary(root)
    activate_selection_freshness(
        root,
        {"selection_fingerprint": "same"},
        selection_summary_path=summary,
    )
    target = root / "3 - Statistical Analysis Results" / "Stats_Ready_Summed_BCA.xlsx"
    target.parent.mkdir(parents=True)
    target.write_text("current", encoding="utf-8")
    mark_artifact_current(root, STATS_READY_SUMMED_BCA_ARTIFACT, target, "same")

    transition = activate_selection_freshness(
        root,
        {"selection_fingerprint": "same"},
        selection_summary_path=summary,
    )
    record = load_artifact_freshness_registry(root).artifacts[
        STATS_READY_SUMMED_BCA_ARTIFACT
    ]

    assert transition.changed is False
    assert transition.stale_artifact_ids == ()
    assert record.status == ARTIFACT_STATUS_CURRENT
    assert record.built_from_selection_fingerprint == "same"


def test_settings_change_stales_selection_derivatives_but_not_neutral_full_fft(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path,
        {
            "schema_version": "2.1.0",
            "tools": {
                "processing": {
                    "full_fft_provenance": {"status": "current", "token": "keep"}
                }
            },
        },
    )
    summary = _summary(root)
    activate_selection_freshness(
        root,
        {"selection_fingerprint": "old-selection"},
        selection_summary_path=summary,
    )

    stale_ids = mark_selection_derivatives_stale(
        root,
        reason="Harmonic-selection settings changed.",
    )

    registry = load_artifact_freshness_registry(root)
    assert set(stale_ids) == {
        "harmonic_selection_summary",
        *SELECTION_DEPENDENT_ARTIFACTS,
    }
    assert all(
        registry.artifacts[artifact_id].status == ARTIFACT_STATUS_STALE
        for artifact_id in stale_ids
    )
    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert manifest["tools"]["processing"]["full_fft_provenance"] == {
        "status": "current",
        "token": "keep",
    }


def test_current_and_failed_states_are_independent_per_artifact(tmp_path: Path) -> None:
    root = _project(tmp_path)
    summary = _summary(root)
    activate_selection_freshness(
        root,
        {"selection_fingerprint": "active"},
        selection_summary_path=summary,
    )
    stats_path = root / "stats.xlsx"
    stats_path.write_text("new", encoding="utf-8")
    mark_artifact_current(root, STATS_READY_SUMMED_BCA_ARTIFACT, stats_path, "active")
    audit_path = root / "audit.xlsx"
    audit_path.write_text("old", encoding="utf-8")
    mark_artifact_failed(
        root,
        ANALYSIS_READY_FULL_AUDIT_ARTIFACT,
        audit_path,
        "active",
        "writer failed",
    )

    registry = load_artifact_freshness_registry(root)
    assert registry.artifacts[STATS_READY_SUMMED_BCA_ARTIFACT].status == ARTIFACT_STATUS_CURRENT
    failed = registry.artifacts[ANALYSIS_READY_FULL_AUDIT_ARTIFACT]
    assert failed.status == ARTIFACT_STATUS_FAILED
    assert failed.last_error == "writer failed"
    assert selection_dependent_artifacts_are_current(root, "active") is False

    assert require_current_artifact(
        root,
        STATS_READY_SUMMED_BCA_ARTIFACT,
        stats_path,
    ).status == ARTIFACT_STATUS_CURRENT
    with pytest.raises(RuntimeError, match="is failed"):
        require_current_artifact(
            root,
            ANALYSIS_READY_FULL_AUDIT_ARTIFACT,
            audit_path,
        )


def test_current_artifact_validator_rejects_missing_or_mismatched_path(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    summary = _summary(root)
    activate_selection_freshness(
        root,
        {"selection_fingerprint": "active"},
        selection_summary_path=summary,
    )
    target = root / "stats.xlsx"
    target.write_text("current", encoding="utf-8")
    mark_artifact_current(root, STATS_READY_SUMMED_BCA_ARTIFACT, target, "active")

    with pytest.raises(RuntimeError, match="path does not match"):
        require_current_artifact(
            root,
            STATS_READY_SUMMED_BCA_ARTIFACT,
            root / "other.xlsx",
        )
    target.unlink()
    with pytest.raises(RuntimeError, match="recorded as current but is missing"):
        require_current_artifact(root, STATS_READY_SUMMED_BCA_ARTIFACT)


def test_all_selection_dependent_artifacts_must_match_active_fingerprint(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    summary = _summary(root)
    activate_selection_freshness(
        root,
        {"selection_fingerprint": "active"},
        selection_summary_path=summary,
    )
    for artifact_id in SELECTION_DEPENDENT_ARTIFACTS:
        target = root / f"{artifact_id}.artifact"
        target.write_text(artifact_id, encoding="utf-8")
        mark_artifact_current(root, artifact_id, target, "active")

    assert selection_dependent_artifacts_are_current(root, "active") is True
    assert selection_dependent_artifacts_are_current(root, "other") is False


def test_selection_dependents_are_not_current_when_recorded_target_is_missing(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    summary = _summary(root)
    activate_selection_freshness(
        root,
        {"selection_fingerprint": "active"},
        selection_summary_path=summary,
    )
    targets: dict[str, Path] = {}
    for artifact_id in SELECTION_DEPENDENT_ARTIFACTS:
        target = canonical_artifact_path(root, artifact_id)
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("current", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
        targets[artifact_id] = target
        mark_artifact_current(root, artifact_id, target, "active")

    missing = targets[STATS_READY_SUMMED_BCA_ARTIFACT]
    missing.unlink()

    assert selection_dependent_artifacts_are_current(root, "active") is False


def test_successful_rebuild_archives_old_file_inside_project(tmp_path: Path) -> None:
    root = _project(tmp_path)
    target = root / "outputs" / "stats.xlsx"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")

    with preserve_artifact_for_rebuild(
        root,
        STATS_READY_SUMMED_BCA_ARTIFACT,
        target,
        "old-selection",
    ) as archive:
        assert archive is not None
        assert not target.exists()
        target.write_text("new", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "new"
    assert archive is not None
    assert archive.is_relative_to(root)
    assert archive.read_text(encoding="utf-8") == "old"


def test_failed_rebuild_restores_old_directory_and_removes_partial_output(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    target = root / "source maps"
    target.mkdir()
    (target / "old.json").write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="intentional"):
        with preserve_artifact_for_rebuild(
            root,
            STATS_READY_SUMMED_BCA_ARTIFACT,
            target,
            "old-selection",
        ):
            target.mkdir()
            (target / "partial.json").write_text("partial", encoding="utf-8")
            raise RuntimeError("intentional")

    assert (target / "old.json").read_text(encoding="utf-8") == "old"
    assert not (target / "partial.json").exists()


def test_rebuild_that_publishes_no_replacement_restores_old_file(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    target = root / "outputs" / "stats.xlsx"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="without publishing"):
        with preserve_artifact_for_rebuild(
            root,
            STATS_READY_SUMMED_BCA_ARTIFACT,
            target,
            "old-selection",
        ):
            pass

    assert target.read_text(encoding="utf-8") == "old"


def test_rebuild_refuses_artifact_outside_project(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="active project root"):
        with preserve_artifact_for_rebuild(
            root,
            STATS_READY_SUMMED_BCA_ARTIFACT,
            outside,
            "old",
        ):
            pass


def test_registry_write_preserves_unrelated_project_metadata(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {
            "schema_version": "2.1.0",
            "name": "Example",
            "tools": {"frequency_domain_qc": {"accepted": True}},
        },
    )
    summary = _summary(root)

    activate_selection_freshness(
        root,
        {"selection_fingerprint": "active"},
        selection_summary_path=summary,
    )

    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "Example"
    assert manifest["tools"]["frequency_domain_qc"] == {"accepted": True}


def test_failed_atomic_manifest_replace_preserves_previous_project_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, {"schema_version": "2.1.0", "name": "Before"})
    summary = _summary(root)
    manifest_path = root / "project.json"
    original = manifest_path.read_text(encoding="utf-8")

    def _deny_replace(_source: object, _target: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(freshness_module.os, "replace", _deny_replace)
    with pytest.raises(PermissionError, match="locked"):
        activate_selection_freshness(
            root,
            {"selection_fingerprint": "new"},
            selection_summary_path=summary,
        )

    assert manifest_path.read_text(encoding="utf-8") == original
    assert list(root.glob(".project.json.artifact-freshness-*.tmp")) == []
