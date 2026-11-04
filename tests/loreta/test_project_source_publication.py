from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from Main_App.processing.artifact_freshness import activate_selection_freshness, canonical_artifact_path
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
)
from Tools.LORETA_Visualizer.source_producers.contracts import ProducedPayload, SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers import project_source_publication as publication


@dataclass(frozen=True)
class _Result:
    producer_result: SourceProducerRunResult
    participant_sidecar_path: Path

    @property
    def manifest_path(self):
        return self.producer_result.manifest_path


def _project(tmp_path):
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    activate_selection_freshness(tmp_path, {"selection_fingerprint": "selection-a"})
    return tmp_path


def _write_bundle(stage, artifact_id, value=1.0):
    path = stage / "condition_mean.json"
    path.write_text(json.dumps({
        "format": "fpvs-loreta-source-payload-v1", "coordinate_space": "mni",
        "kind": "surface_points", "points": [[0, 0, 0]], "values": [value],
    }), encoding="utf-8")
    manifest = stage / publication.SOURCE_ARTIFACT_MANIFESTS[artifact_id]
    manifest.write_text(json.dumps({
        "format": "fpvs-loreta-source-manifest-v1",
        "metadata": {"producer_method": artifact_id},
        "conditions": [{"id": "condition", "label": "Condition", "file": path.name}],
    }), encoding="utf-8")
    sidecar = stage / "participants.json"
    sidecar.write_text("{}", encoding="utf-8")
    (stage / "validation.json").write_text(json.dumps({"output_dir": str(stage), "manifest_path": str(manifest)}))
    (stage / "validation.md").write_text(f"Output: {stage}\nManifest: {manifest.as_posix()}\n")
    return _Result(SourceProducerRunResult(
        artifact_id, stage, manifest,
        (ProducedPayload("condition", "Condition", path, validate_prepared_source_payload_json(path)),),
        validate_prepared_source_manifest_json(manifest, require_payload_files=True),
    ), sidecar)


def _identity(root, artifact_id, *, batch="batch-a", created=1, common="same-cohort", inputs=()):
    return {"run_id": f"{artifact_id}-{created}", "batch_id": batch, "created_ns": created,
            "method_id": artifact_id, "selection_fingerprint": "selection-a",
            "common_input_fingerprint": common, "common_inputs": {
                "inputs": list(inputs),
                "cohort_snapshot": publication.source_project_cohort_snapshot(root, include_flagged_subjects=False),
            }}


def _publish(root, artifact_id="l2_mne_source_psd", *, value=1.0, **identity_kwargs):
    target = canonical_artifact_path(root, artifact_id)
    with publication.stage_source_bundle(root, target, artifact_id) as staged:
        result = _write_bundle(staged.output_dir, artifact_id, value)
        return staged.publish(result, identity=_identity(root, artifact_id, **identity_kwargs))


def _contents(folder):
    return {path.relative_to(folder): path.read_bytes() for path in folder.rglob("*") if path.is_file()}


def test_publish_rebases_all_paths_and_validates_complete_receipt(tmp_path):
    root = _project(tmp_path)
    result = _publish(root)
    target = canonical_artifact_path(root, "l2_mne_source_psd")
    assert result.manifest_path.parent == target
    assert result.participant_sidecar_path.is_file()
    assert result.producer_result.payloads[0].payload_path.parent == target
    assert result.producer_result.manifest_validation.conditions[0].payload_path.parent == target
    receipt = publication.validate_source_bundle(result.manifest_path)
    assert len(receipt["files"]) == 5
    assert json.loads((target / "validation.json").read_text()) == {
        "output_dir": str(target), "manifest_path": str(result.manifest_path)
    }
    assert all(b".staging-" not in content for content in _contents(target).values())
    assert publication.current_source_manifest_paths(root) == (result.manifest_path,)
    assert not tuple(target.parent.glob("*.staging-*"))


@pytest.mark.parametrize("failure", ["serialize", "cancel", "rename", "freshness"])
def test_failed_replacement_preserves_previous_bundle(tmp_path, monkeypatch, failure):
    root = _project(tmp_path)
    previous = _publish(root)
    target = previous.manifest_path.parent
    before = _contents(target)
    with pytest.raises((RuntimeError, OSError), match="injected"):
        with publication.stage_source_bundle(root, target, "l2_mne_source_psd") as staged:
            result = _write_bundle(staged.output_dir, "l2_mne_source_psd", 2.0)
            def fail(*_args, **_kwargs):
                raise RuntimeError("injected failure")
            if failure == "serialize":
                fail()
            if failure == "freshness":
                monkeypatch.setattr(publication, "mark_artifact_current", fail)
            if failure == "rename":
                original = Path.replace
                def fail_stage(path, destination):
                    if path == staged.output_dir:
                        raise OSError("injected rename failure")
                    return original(path, destination)
                monkeypatch.setattr(Path, "replace", fail_stage)
            staged.publish(result, identity=_identity(root, "l2_mne_source_psd", created=2),
                           cancellation_callback=fail if failure == "cancel" else None)
    assert _contents(target) == before
    assert publication.current_source_manifest_paths(root) == (previous.manifest_path,)
    assert not tuple(target.parent.glob("*.staging-*"))


def test_failed_first_publication_leaves_no_canonical_directory(tmp_path, monkeypatch):
    root = _project(tmp_path)
    def fail(*_args, **_kwargs):
        raise OSError("injected freshness failure")
    monkeypatch.setattr(publication, "mark_artifact_current", fail)
    with pytest.raises(OSError, match="injected"):
        _publish(root)
    assert not canonical_artifact_path(root, "l2_mne_source_psd").exists()


@pytest.mark.parametrize("change", ["selection", "payload", "missing", "receipt", "method"])
def test_discovery_rejects_stale_or_inconsistent_bundle(tmp_path, change):
    root = _project(tmp_path)
    result = _publish(root)
    if change == "selection":
        activate_selection_freshness(root, {"selection_fingerprint": "selection-b"})
    elif change == "receipt":
        (result.manifest_path.parent / publication.SOURCE_BUNDLE_RECEIPT).unlink()
    elif change == "missing":
        result.producer_result.payloads[0].payload_path.unlink()
    elif change == "method":
        result.manifest_path.write_text(result.manifest_path.read_text().replace('l2_mne_source_psd', 'other-method'))
    else:
        result.producer_result.payloads[0].payload_path.write_text("{}")
    assert publication.current_source_manifest_paths(root) == ()


def test_latest_partial_batch_does_not_attach_previous_sibling(tmp_path):
    root = _project(tmp_path)
    first = _publish(root)
    second = _publish(root, "eloreta_volume_source_psd")
    assert publication.current_source_manifest_paths(root) == (first.manifest_path, second.manifest_path)
    newest = _publish(root, batch="batch-b", created=2, value=2.0)
    assert second.manifest_path.is_file()
    assert publication.current_source_manifest_paths(root) == (newest.manifest_path,)


def test_common_cohort_mismatch_is_not_loaded_as_comparable_siblings(tmp_path):
    root = _project(tmp_path)
    _publish(root)
    second = _publish(root, "eloreta_volume_source_psd", created=2, common="different-cohort")
    assert publication.current_source_manifest_paths(root) == (second.manifest_path,)


@pytest.mark.parametrize("change", ["group", "condition_exclusion", "ledger", "qc_flag"])
def test_discovery_rejects_changed_canonical_cohort_without_selection_change(tmp_path, change):
    root = _project(tmp_path)
    result = _publish(root)
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text())
    if change == "group":
        manifest["groups"] = {"control": {"label": "Control", "folder_name": "Control"}}
        manifest["participants"] = {"p01": {"group_id": "control"}}
    elif change == "condition_exclusion":
        manifest["preprocessing"] = {"manual_excluded_participant_conditions": {"p01": ["Condition A"]}}
    elif change == "ledger":
        ledger = root / ".fpvs_processing" / "processing_ledger.json"
        ledger.parent.mkdir(exist_ok=True)
        ledger.write_text(json.dumps({"entries": {"p01": {"status": "excluded"}}}))
    else:
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(["participant_id"])
        workbook.active.append(["p01"])
        stats = root / "3 - Statistical Analysis Results"
        stats.mkdir()
        workbook.save(stats / "Flagged Participants.xlsx")
        workbook.close()
    manifest_path.write_text(json.dumps(manifest))
    assert publication.current_source_manifest_paths(root) == ()
    assert result.manifest_path.is_file()


def test_unrelated_project_metadata_does_not_invalidate_source_bundle(tmp_path):
    root = _project(tmp_path)
    result = _publish(root)
    path = root / "project.json"
    manifest = json.loads(path.read_text())
    manifest.update({"name": "Renamed project", "last_opened_at": "later"})
    manifest.setdefault("tools", {})["other"] = {"zoom": 2}
    path.write_text(json.dumps(manifest))
    assert publication.current_source_manifest_paths(root) == (result.manifest_path,)


@pytest.mark.parametrize("late_change", [False, True])
def test_cohort_change_during_build_preserves_previous_bundle(tmp_path, late_change):
    root = _project(tmp_path)
    previous = _publish(root)
    before = _contents(previous.manifest_path.parent)
    identity = _identity(root, "l2_mne_source_psd")
    with publication.stage_source_bundle(root, previous.manifest_path.parent, "l2_mne_source_psd") as staged:
        result = _write_bundle(staged.output_dir, "l2_mne_source_psd", 2.0)
        def change_cohort():
            path = root / "project.json"
            manifest = json.loads(path.read_text())
            manifest["preprocessing"] = {"manual_excluded_participants": ["p01"]}
            path.write_text(json.dumps(manifest))
        if not late_change:
            change_cohort()
        with pytest.raises(ValueError, match="QC exclusions changed"):
            staged.publish(result, identity=identity, cancellation_callback=change_cohort if late_change else None)
    assert _contents(previous.manifest_path.parent) == before


def test_selection_change_during_build_leaves_previous_directory(tmp_path):
    root = _project(tmp_path)
    previous = _publish(root)
    target = previous.manifest_path.parent
    before = _contents(target)
    with publication.stage_source_bundle(root, target, "l2_mne_source_psd") as staged:
        result = _write_bundle(staged.output_dir, "l2_mne_source_psd", 2.0)
        activate_selection_freshness(root, {"selection_fingerprint": "selection-b"})
        with pytest.raises(RuntimeError, match="selection changed"):
            staged.publish(result, identity=_identity(root, "l2_mne_source_psd"))
    assert _contents(target) == before


def test_output_cannot_escape_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(ValueError, match="active project root"):
        with publication.stage_source_bundle(root, tmp_path / "outside", "l2_mne_source_psd"):
            pytest.fail("escaped project")


@pytest.mark.parametrize("change_before_publish", [False, True])
def test_changed_input_bytes_cannot_be_published_or_discovered_as_current(tmp_path, change_before_publish):
    root = _project(tmp_path)
    row = {}
    for name in ("fif", "sidecar", "participant_manifest"):
        path = root / f"input.{name}"
        path.write_bytes(b"original input")
        row[name] = path.name
        row[f"{name}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if change_before_publish:
        (root / row["fif"]).write_bytes(b"changed input")
        with pytest.raises(ValueError, match="input changed"):
            _publish(root, inputs=[row])
        assert not canonical_artifact_path(root, "l2_mne_source_psd").exists()
    else:
        _publish(root, inputs=[row])
        (root / row["fif"]).write_bytes(b"changed input")
        assert publication.current_source_manifest_paths(root) == ()
