from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from Main_App.projects.fpvs_config_import import read_fpvs_config
from Main_App.projects.studio_cohort import (
    commit_study_review, digest, find_study_project, review_study, selected_recording_ids,
)


def make_source():
    setup = json.loads((Path(__file__).parents[1] / "fixtures/studio_handoff/v2-setup.fpvsconfig").read_text())
    version = str(uuid4())
    setup_id = digest(setup)
    visits = [{"visit_id": f"exec-{n}", "execution_id": f"exec-{n}", "state": "completed",
               "participant_number": f"{n:03}", "participant_session_number": 1,
               "protocol_version_id": version, "setup_id": setup_id, "issues": [],
               "runs": [{"run_id": f"run-{n}", "state": "completed", "condition_id": setup["conditions"][0]["condition_id"],
                         "condition_name": setup["conditions"][0]["name"]}],
               "recording": {"selected_backend": "serial"}} for n in (1, 2, 3)]
    return {"format": "fpvs-study-handoff", "format_version": 1, "study_id": str(uuid4()),
            "project_id": setup["project"]["project_id"], "project_title": "Reviewed cohort",
            "collection_complete": True, "roster_sequence": 1, "visits": visits, "setups": {setup_id: setup}}


def write_source(tmp, source):
    source["roster_revision"] = digest(source["visits"])
    dest = tmp / "cohort.fpvsconfig"
    dest.write_text(json.dumps(source), encoding="utf-8")
    return read_fpvs_config(dest)


def _set_brainvision_cap(source, visit_index, montage):
    visit = source["visits"][visit_index]
    setup = deepcopy(source["setups"][visit["setup_id"]])
    setup.pop("recording", None)
    setup["toolbox"].pop("acquisition_profile", None)
    key = digest(setup)
    source["setups"][key] = setup
    visit.update(setup_id=key, recording={"selected_backend": "brainproducts_triggerbox", "electrode_montage": montage})


def test_study_cap_uses_selected_visits_and_keeps_later_project_edits(tmp_path):
    source = make_source()
    cap64, cap128 = "brainproducts_acticap_gacs_64", "brainproducts_acticap_gacs_128"
    for index, cap in enumerate((cap128, cap64, cap128)):
        _set_brainvision_cap(source, index, cap)
    data = write_source(tmp_path, source)
    assert data.recording_selection is None
    assert data.study_recording_platform == "brain_products"
    raw = tmp_path / "raw"
    raw.mkdir()
    for visit in source["visits"]:
        (raw / f"P{visit['participant_number']}.vhdr").touch()
    review = review_study(data, raw, hardware="brain_products")
    decisions = {r.visit["visit_id"]: ("matched", r.candidates[0]) for r in review.rows}
    options = dict(decisions=decisions, omissions={},
                   versions=[source["visits"][0]["protocol_version_id"]])
    with pytest.raises(ValueError, match="incompatible"):
        commit_study_review(tmp_path / "projects", data, review, **options)
    decisions["exec-2"] = ("awaiting_eeg", None)
    project = commit_study_review(tmp_path / "projects", data, review, **options)
    assert project.preprocessing["electrode_montage"] == cap128
    project.update_preprocessing({**project.preprocessing, "electrode_montage": cap64})
    project.save()
    revised = review_study(data, raw, project)
    assert "conflicts" in revised.rows[0].problem
    with pytest.raises(ValueError, match="compatible evidence"):
        commit_study_review(tmp_path / "projects", data, revised, existing=project, **options)
    assert project.preprocessing["electrode_montage"] == cap64


def test_mixed_recorders_still_require_manual_cohort_review(tmp_path):
    source = make_source()
    for index in range(3):
        _set_brainvision_cap(source, index, "brainproducts_acticap_gacs_64")
    source["visits"][1]["recording"] = {"selected_backend": "biosemi_active_three", "electrode_montage": "biosemi128"}
    data = write_source(tmp_path, source)
    assert data.recording_selection is None and data.study_recording_platform is None
    review = review_study(data, tmp_path, hardware="brain_products")
    assert "differs from project hardware" in review.rows[1].problem
    with pytest.raises(ValueError, match="Select the project recording system"):
        commit_study_review(tmp_path / "projects", data, review, decisions={}, omissions={}, versions=[])


def test_cohort_review_and_revised_import_keep_history_and_filter_processing(tmp_path):
    from Main_App.processing.processing_controller import prepare_batch_files, raw_file_info_for_path
    from Main_App.projects.project import Project

    source = make_source()
    raw = tmp_path / "external"
    raw.mkdir()
    for name in ("P001.bdf", "P002_raw.bdf", "P002_eeg.bdf", "extra.bdf"):
        (raw / name).write_bytes(b"synthetic")
    data = write_source(tmp_path, source)
    review = review_study(data, raw)
    assert [row.status for row in review.rows] == ["clear", "ambiguous", "missing"]
    root = tmp_path / "projects"
    options = dict(decisions={"exec-1": ("matched", "P001.bdf"), "exec-2": ("matched", "P002_raw.bdf"),
                              "exec-3": ("awaiting_eeg", None)}, omissions={},
                   versions=[source["visits"][0]["protocol_version_id"]], hardware="biosemi")
    project = commit_study_review(root, data, review, **options)
    assert project.recordings
    pipeline = prepare_batch_files(project)
    assert set(pipeline) == {raw / "P001.bdf", raw / "P002_raw.bdf"}
    assert find_study_project(root, source["study_id"]).project_root == project.project_root
    with pytest.raises(ValueError):
        raw_file_info_for_path(project, raw / "extra.bdf")
    project.save()
    project = Project.load(project.project_root)
    assert set(prepare_batch_files(project)) == set(pipeline)
    path = project.project_root / "project.json"
    before = path.read_bytes()
    review = review_study(data, raw, project)
    assert [r.status for r in review.rows] == ["matched", "matched", "awaiting_eeg"]
    commit_study_review(root, data, review, existing=project, **options)
    assert path.read_bytes() == before
    updated = deepcopy(source)
    updated["roster_sequence"] += 1
    updated["visits"].pop(1)
    visit = deepcopy(updated["visits"][0])
    visit.update(visit_id="exec-repeat", execution_id="exec-repeat", participant_session_number=2)
    updated["visits"].append(visit)
    (raw / "repeat.bdf").write_bytes(b"synthetic repeat")
    revised = write_source(tmp_path, updated)
    offered = review_study(revised, raw, project)
    assert path.read_bytes() == before
    assert list(offered.omitted) == ["exec-2"]
    del options["decisions"]["exec-2"]
    options["decisions"]["exec-repeat"] = ("matched", "repeat.bdf")
    with pytest.raises(ValueError, match="omitted"):
        commit_study_review(root, revised, offered, existing=project, **options)
    assert path.read_bytes() == before
    options["omissions"] = {"exec-2": "archive"}
    project = commit_study_review(root, revised, offered, existing=project, **options)
    receipt = project.manifest["tools"]["studio_cohort"]
    assert receipt["history"][-1]["roster_revision"] == source["roster_revision"]
    assert receipt["visits"]["exec-2"]["decision"] == "archived"
    assert len(project.recordings) == 3 and len(selected_recording_ids(project.manifest)) == 2
    assert set(prepare_batch_files(project)) == {raw / "P001.bdf", raw / "repeat.bdf"}
    with pytest.raises(ValueError, match="predates"):
        review_study(data, raw, project)


def test_method_gates_and_double_mixed_version_confirmation(tmp_path):
    source = make_source()
    a = source["visits"][0]["protocol_version_id"]
    b = str(uuid4())
    source["visits"][1]["protocol_version_id"] = b
    raw = tmp_path / "raw"
    raw.mkdir()
    for n in range(1, 4):
        (raw / f"P{n:03}.bdf").write_bytes(bytes([n]))
    imported = write_source(tmp_path, source)
    review = review_study(imported, raw)
    options = dict(decisions={r.visit["visit_id"]: ("matched", r.candidates[0]) for r in review.rows},
                   omissions={}, versions=[a, b], hardware="biosemi")
    with pytest.raises(ValueError, match="both comparability"):
        commit_study_review(tmp_path / "projects", imported, review, warnings=(True,), **options)
    project = commit_study_review(tmp_path / "projects", imported, review, warnings=(True, True), **options)
    assert project.manifest["tools"]["studio_cohort"]["mixed_version_confirmations"] == [True, True]
    # The same explicit acknowledgement cannot waive an incompatible EEG/processing method.
    modified = deepcopy(next(iter(source["setups"].values())))
    modified["conditions"][0]["oddball_cycle_repeats_per_sequence"] += 120
    different = digest(modified)
    source["setups"][different] = modified
    source["visits"][1]["setup_id"] = different
    source["roster_sequence"] += 1
    incompatible = write_source(tmp_path, source)
    review = review_study(incompatible, raw, project)
    with pytest.raises(ValueError, match="incompatible"):
        commit_study_review(tmp_path / "projects", incompatible, review, existing=project, warnings=(True, True), **options)


def test_twenty_then_twenty_one_preserves_prior_workbook_and_requires_a_new_release(tmp_path, monkeypatch):
    from Main_App.processing import artifact_freshness, roi_coverage
    from Main_App.projects.manifest_store import project_manifest_transaction
    from Main_App.projects.project import Project
    from Main_App.projects.studio_cohort import record_current_result

    source = make_source()
    template = source["visits"][0]
    source["visits"] = [dict(template, participant_number=f"{n:03}", visit_id=f"exec-{n}", execution_id=f"exec-{n}")
                        for n in range(1, 21)]
    raw = tmp_path / "raw"
    raw.mkdir()
    for n in range(1, 22):
        (raw / f"P{n:03}.bdf").write_bytes(bytes([n]))
    options = {"versions": [template["protocol_version_id"]], "hardware": "biosemi", "omissions": {}}
    def match(review):
        return {r.visit["visit_id"]: ("matched", r.candidates[0]) for r in review.rows}
    data = write_source(tmp_path, source)
    reviewed = review_study(data, raw)
    project = commit_study_review(tmp_path / "projects", data, reviewed, decisions=match(reviewed), **options)
    root = project.project_root
    artifact = artifact_freshness.ANALYSIS_READY_FULL_AUDIT_ARTIFACT
    book = artifact_freshness.canonical_artifact_path(root, artifact)
    book.parent.mkdir(exist_ok=True, parents=True)
    book.write_bytes(b"synthetic released result for first 20")
    def ready():
        with project_manifest_transaction(root / "project.json") as tx:
            manifest = json.loads((root / "project.json").read_bytes())
            manifest["tools"].setdefault("post_processing", {})["artifact_freshness"] = {
                "schema_version": artifact_freshness.ARTIFACT_FRESHNESS_SCHEMA_VERSION,
                "selection_fingerprint": "selection", "artifacts": {artifact: {
                    "status": "current", "path": book.relative_to(root).as_posix(),
                    "built_from_selection_fingerprint": "selection", "required_selection_fingerprint": "selection",
                }},
            }
            tx.write(manifest)
    run = SimpleNamespace(expected_plan_run_id="batch-20")
    coverage = SimpleNamespace(cells=[])
    def release(project):
        coverage.cells = [SimpleNamespace(recording_id=k, source_evidence=True, downstream_cell_excluded=False)
                          for k in selected_recording_ids(project.manifest)]
    monkeypatch.setattr(roi_coverage, "require_project_final_release", lambda root: (
        run, coverage, SimpleNamespace(fingerprint="release")))
    ready()
    release(project)
    record_current_result(root, book)
    project = Project.load(root)
    assert len(project.manifest["tools"]["studio_cohort"]["current_result"]["included"]) == 20
    source["visits"].append(dict(template, participant_number="021", execution_id="exec-21", visit_id="exec-21"))
    source["roster_sequence"] += 1
    data = write_source(tmp_path, source)
    offered = review_study(data, raw, project)
    assert len(project.recordings) == 20
    project = commit_study_review(root.parent, data, offered, existing=project, decisions=match(offered), **options)
    state = project.manifest["tools"]["studio_cohort"]
    prior = state["history"][-1]
    assert len(project.recordings) == 21 and "current_result" not in state
    assert (root / prior["previous_result"]).read_bytes() == book.read_bytes()
    assert len(prior["current_result"]["included"]) == 20
    ready()
    release(project)
    with pytest.raises(ValueError, match="Run Processing"):
        record_current_result(root, book)
    run.expected_plan_run_id = "batch-21"
    book.write_bytes(b"synthetic revised result")
    record_current_result(root, book)
    before = (root / "project.json").read_bytes()
    record_current_result(root, book)
    assert (root / "project.json").read_bytes() == before
    assert len(Project.load(root).manifest["tools"]["studio_cohort"]["current_result"]["included"]) == 21
    from Main_App.projects.studio_cohort import require_current_study_result
    manifest = Project.load(root).manifest
    require_current_study_result(root, book, manifest)
    book.write_bytes(b"replaced after release")
    with pytest.raises(ValueError, match="Run Processing"):
        require_current_study_result(root, book, manifest)


def test_revised_study_preserves_canonical_groups_sources_and_recording_metadata(tmp_path):
    from Main_App.processing.processing_controller import prepare_batch_files
    from Main_App.projects.project import Project

    study = make_source()
    raw = tmp_path / "external"
    raw.mkdir()
    (raw / "P001.bdf").write_bytes(b"one")
    imported = write_source(tmp_path, study)
    review = review_study(imported, raw)
    decisions = {row.visit["visit_id"]: ("awaiting_eeg", None) for row in review.rows}
    options = dict(versions=[study["visits"][0]["protocol_version_id"]], hardware="biosemi", omissions={})
    project = commit_study_review(tmp_path / "projects", imported, review, decisions=decisions, **options)
    assert prepare_batch_files(project) == []
    decisions["exec-1"] = ("matched", "P001.bdf")
    project = commit_study_review(project.project_root.parent, imported, review_study(imported, raw, project),
                                  existing=project, decisions=decisions, **options)
    manifest_path = project.project_root / "project.json"
    saved = json.loads(manifest_path.read_bytes())
    saved["groups"]["patients"] = dict(saved["groups"].pop("cohort"), label="Patients", folder_name="Patients")
    saved["groups"]["controls"] = {"label": "Controls", "folder_name": "Controls", "raw_input_folder": str(raw / "controls")}
    saved["sessions"]["baseline"] = dict(saved["sessions"].pop("visit1"), label="Baseline")
    saved["recording_sources"]["baseline_patients"] = dict(saved["recording_sources"].pop("visit1"),
                                                           group_id="patients", session_id="baseline")
    saved["source_studies"] = {"acquisition": {"label": "Original study"}}
    saved["participants"]["001"].update(group_id="patients", source_study_id="acquisition", source_participant_id="001")
    original = next(iter(saved["recordings"].values()))
    original.update(session_id="baseline", source_id="baseline_patients", days_from_baseline=3)
    saved["groups_locked"] = True
    manifest_path.write_text(json.dumps(saved), encoding="utf-8")
    project = Project.load(project.project_root)
    project.save()
    (raw / "P002.bdf").write_bytes(b"two")
    review = review_study(imported, raw, project)
    decisions["exec-2"] = ("matched", "P002.bdf")
    with pytest.raises(ValueError, match="group for participant 002"):
        commit_study_review(project.project_root.parent, imported, review, existing=project, decisions=decisions, **options)
    project = commit_study_review(project.project_root.parent, imported, review, existing=project, decisions=decisions,
                                  group_assignments={"002": "controls"}, **options)
    assert set(project.groups) == {"patients", "controls"}
    assert project.participants["001"]["source_study_id"] == "acquisition"
    assert project.participants["002"]["group_id"] == "controls"
    kept = next(item for item in project.recordings.values() if item["participant_id"] == "001")
    assert (kept["source_id"], kept["days_from_baseline"]) == ("baseline_patients", 3)
    project.save()
    assert Project.load(project.project_root).groups_locked
