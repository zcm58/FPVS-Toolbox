from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
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


def _write_brainvision_recording(header):
    data = header.with_suffix(".eeg")
    marker = header.with_suffix(".vmrk")
    header.write_text(f"[Common Infos]\nDataFile={data.name}\nMarkerFile={marker.name}\n")
    marker.write_text(f"[Common Infos]\nDataFile={data.name}\n")
    data.write_bytes(bytes(40))


@pytest.mark.parametrize("shared", ["bdf", "brainvision"])
def test_one_physical_signal_cannot_be_selected_twice_even_under_different_names(tmp_path, shared):
    source = make_source()
    source["visits"] = source["visits"][:2]
    raw = tmp_path / "recordings"
    raw.mkdir()
    if shared == "bdf":
        hardware = "biosemi"
        first, second = (raw / name for name in ("P001.bdf", "P002.bdf"))
        first.write_bytes(b"synthetic signal")
        os.link(first, second)
    else:
        hardware = "brain_products"
        first, second = (raw / name for name in ("P001.vhdr", "P002.vhdr"))
        _write_brainvision_recording(first)
        second.write_bytes(first.read_bytes())
        for index in range(2):
            _set_brainvision_cap(source, index, "brainproducts_acticap_gacs_64")
    imported = write_source(tmp_path, source)
    review = review_study(imported, raw)
    assert [r.status for r in review.rows] == ["ambiguous", "ambiguous"]
    projects = tmp_path / "projects"
    versions = [source["visits"][0]["protocol_version_id"]]
    both = {"exec-1": ("matched", first.name), "exec-2": ("matched", second.name)}
    with pytest.raises(ValueError, match="same EEG signal"):
        commit_study_review(projects, imported, review, decisions=both, omissions={}, versions=versions,
                            hardware=hardware)
    assert not projects.exists()
    project = commit_study_review(projects, imported, review, decisions={**both, "exec-2": ("awaiting_eeg", None)},
                                  omissions={}, versions=versions, hardware=hardware)
    manifest = project.project_root / "project.json"
    before = manifest.read_bytes()
    legacy = json.loads(before)
    second_entry = legacy["tools"]["studio_cohort"]["visits"]["exec-2"]
    second_entry.update(decision="matched", raw_file=second.name, **review.files[second.name])
    manifest.write_text(json.dumps(legacy), encoding="utf-8")
    assert [row.status for row in review_study(imported, raw, project).rows] == ["ambiguous", "ambiguous"]
    manifest.write_bytes(before)
    source["visits"].pop(0)
    source["roster_sequence"] += 1
    changed = write_source(tmp_path, source)
    with pytest.raises(ValueError, match="same EEG signal"):
        commit_study_review(projects, changed, review_study(changed, raw, project), existing=project,
                            decisions={"exec-2": both["exec-2"]}, omissions={"exec-1": "retain"}, versions=versions)
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("fault", ["second condition code", "failed send", "missing attempt", "different frame",
                                   "out-of-order send", "missing index", "wrong code map", "truncated run", "clean"])
def test_each_cohort_run_must_agree_with_its_own_condition_and_recorded_sends(tmp_path, fault):
    source = make_source()
    setup = next(iter(source["setups"].values()))
    setup["conditions"][0]["oddball_cycle_repeats_per_sequence"] = 12
    setup["conditions"].append(dict(setup["conditions"][0], name="Faces", condition_id="faces", trigger_code=2))
    setup["toolbox"]["event_map"]["Faces"] = 2
    key = digest(setup)
    source["setups"] = {key: setup}
    for visit in source["visits"]:
        visit["setup_id"] = key
    runs = source["visits"][0]["runs"]
    runs.append(dict(runs[0], run_id="run-2", condition_name="Faces", condition_id="faces"))
    for code, run in enumerate(runs, start=1):
        markers = [[0, code, "condition_start"], *[[10 * n, 55, "oddball_onset"] for n in range(1, 13)]]
        # Studio keeps session-wide trigger indices and permits missing callback times.
        offset = 0 if code == 1 else 13
        run.update(planned_markers=markers, attempted_markers=[[offset + n, *m, n * 0.2 if n else None, "sent"]
                                                               for n, m in enumerate(markers)],
                   code_map=[{"code": code, "label": "condition_start"}, {"code": 55, "label": "oddball"}],
                   planned_event_count=len(markers), sent_events=len(markers), error_events=0)
    if fault == "second condition code":
        runs[1]["planned_markers"][0][1] = 1
        runs[1]["attempted_markers"][0][2] = 1
    elif fault == "failed send":
        runs[1]["attempted_markers"][1][-1] = "error"
    elif fault == "missing attempt":
        runs[1]["attempted_markers"].pop()
    elif fault == "different frame":
        runs[1]["attempted_markers"][1][1] += 1
    elif fault == "out-of-order send":
        runs[1]["attempted_markers"][2][4] = 0
    elif fault == "missing index":
        runs[1]["attempted_markers"][1][0] += 1
    elif fault == "wrong code map":
        runs[1]["code_map"][0]["code"] = 1
    elif fault == "truncated run":
        for field in ("planned_markers", "attempted_markers"):
            runs[1][field].pop()
        runs[1].update(planned_event_count=12, sent_events=12)
    imported = write_source(tmp_path, source)
    (tmp_path / "P001.bdf").write_bytes(b"synthetic")
    review = review_study(imported, tmp_path)
    decisions = {r.visit["visit_id"]: ("awaiting_eeg", None) for r in review.rows}
    decisions["exec-1"] = ("matched", "P001.bdf")
    options = dict(decisions=decisions, omissions={}, versions=[source["visits"][0]["protocol_version_id"]], hardware="biosemi")
    if fault == "clean":
        assert review.rows[0].status == "clear"
        assert len(commit_study_review(tmp_path / "projects", imported, review, **options).recordings) == 1
    else:
        assert review.rows[0].status == "exception" and "Faces (run-2)" in review.rows[0].problem
        with pytest.raises(ValueError, match="compatible evidence"):
            commit_study_review(tmp_path / "projects", imported, review, **options)
        assert not (tmp_path / "projects").exists()


@pytest.mark.parametrize("historical", [True, False])
def test_same_roster_reexport_preserves_release_and_revisions_cannot_reassign_identity(tmp_path, historical):
    source = make_source()
    source["visits"] = source["visits"][:1]
    imported = write_source(tmp_path, source)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "P001.bdf").write_bytes(b"synthetic")
    options = dict(decisions={"exec-1": ("matched", "P001.bdf")}, omissions={},
                   versions=[source["visits"][0]["protocol_version_id"]], hardware="biosemi")
    root = tmp_path / "projects"
    project = commit_study_review(root, imported, review_study(imported, raw), **options)
    path = project.project_root / "project.json"
    manifest = json.loads(path.read_bytes())
    receipt = manifest["tools"]["studio_cohort"]
    if historical:
        del receipt["project_id"]
    receipt["current_result"] = {"processing_run_id": "keep-this-result"}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    source["producer"] = {"application": "FPVS Studio", "version": "2.8.3"}
    reexported = write_source(tmp_path, source)
    assert reexported.source_sha256 != imported.source_sha256
    commit_study_review(root, reexported, review_study(reexported, raw, project), existing=project, **options)
    assert path.read_bytes() == before
    source["roster_sequence"] += 1
    visit = source["visits"][0]
    for field, other in (("participant_number", "009"), ("participant_session_number", 2)):
        prior = visit[field]
        visit[field] = other
        with pytest.raises(ValueError, match="execution exec-1 changed participant or visit number"):
            review_study(write_source(tmp_path, source), raw, project)
        visit[field] = prior
    source["project_id"] = "other-study"
    setup = source["setups"].pop(visit["setup_id"])
    setup["project"]["project_id"] = source["project_id"]
    visit["setup_id"] = digest(setup)
    source["setups"][visit["setup_id"]] = setup
    with pytest.raises(ValueError, match="different Studio project"):
        review_study(write_source(tmp_path, source), raw, project)
    assert path.read_bytes() == before


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
        _write_brainvision_recording(raw / f"P{visit['participant_number']}.vhdr")
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


def test_review_compares_complete_brainvision_sources_and_legacy_matches(tmp_path, monkeypatch):
    from Main_App.projects import studio_cohort
    source = make_source()
    source["visits"] = source["visits"][:1]
    _set_brainvision_cap(source, 0, "brainproducts_acticap_gacs_64")
    imported = write_source(tmp_path, source)
    raw = tmp_path / "raw"
    raw.mkdir()
    header = raw / "P001.vhdr"
    _write_brainvision_recording(header)
    _write_brainvision_recording(raw / "extra.vhdr")
    (raw / "P002.vhdr").touch()  # Incomplete extra recording can be deferred.
    content_reads = []
    original_identity = studio_cohort.recording_content_identity
    def checked_identity(path):
        content_reads.append(path.name)
        return original_identity(path)
    monkeypatch.setattr(studio_cohort, "recording_content_identity", checked_identity)
    review = review_study(imported, raw)
    assert set(review.unreadable) == {"P002.vhdr"}
    assert "extra.vhdr" in content_reads
    options = dict(decisions={"exec-1": ("matched", header.name)}, omissions={},
                   versions=[source["visits"][0]["protocol_version_id"]])
    root = tmp_path / "projects"
    content_reads.clear()
    project = commit_study_review(root, imported, review, **options)
    assert content_reads == [header.name]
    reviewed = review_study(imported, raw, project)
    assert reviewed.rows[0].status == "matched"
    original = (project.project_root / "project.json").read_bytes()
    signal = header.with_suffix(".eeg")
    original_stat = signal.stat()
    actual_stat = Path.stat
    # Model the same size, modification time and Windows creation time on every CI host.
    monkeypatch.setattr(Path, "stat", lambda self, *a, **kw: original_stat if self == signal else actual_stat(self, *a, **kw))
    signal.write_bytes(b"\x01" * original_stat.st_size)
    changed = review_study(imported, raw, project)
    assert changed.files[header.name]["recording_sources"] == reviewed.files[header.name]["recording_sources"]
    assert changed.files[header.name]["source_sha256_by_file"] != reviewed.files[header.name]["source_sha256_by_file"]
    assert changed.rows[0].status == "reconfirm_recording"
    with pytest.raises(ValueError, match="changed after review"):
        commit_study_review(root, imported, reviewed, existing=project, **options)
    assert (project.project_root / "project.json").read_bytes() == original
    signal.write_bytes(bytes(original_stat.st_size))
    legacy = json.loads(original)
    del legacy["tools"]["studio_cohort"]["visits"]["exec-1"]["source_sha256_by_file"]
    (project.project_root / "project.json").write_text(json.dumps(legacy))
    assert review_study(imported, raw, project).rows[0].status == "reconfirm_recording"


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


@pytest.mark.parametrize("value", [{}, {"condition_id": "missing"}, {"condition_name": "Faces"}])
def test_study_does_not_accept_incomplete_condition_identity(tmp_path, value):
    source = make_source()
    source["visits"][0]["runs"] = [dict(value, state="completed", run_id="run-1")]
    with pytest.raises(ValueError, match="consistent recorded condition"):
        write_source(tmp_path, source)


@pytest.mark.parametrize(("selected", "effective", "problem"), [
    ("serial", "null", "effective"),
    ("biosemi_active_three", "unicorn_udp", "effective"),
    ("brainproducts_triggerbox", "brainproducts_parallel", "effective"),
    ("unicorn_udp", "unicorn_udp", "conflicts between"),  # captured setup declares BioSemi
    ("egi_din", "egi_din", "verify_egi_din"),
    ("ant_mylab_ttl", "ant_mylab_ttl", "verify_ant_ttl"),
])
def test_bad_study_snapshot_is_a_review_exception_before_registration(tmp_path, selected, effective, problem):
    source = make_source()
    source["visits"][0]["recording"].update(selected_backend=selected, effective_backend=effective)
    data = write_source(tmp_path, source)
    (tmp_path / "P001.bdf").write_bytes(b"review only")
    review = review_study(data, tmp_path, hardware="biosemi")
    assert review.rows[0].status == "exception" and problem in review.rows[0].problem
    decisions = {row.visit["visit_id"]: ("awaiting_eeg", None) for row in review.rows}
    decisions["exec-1"] = ("matched", "P001.bdf")
    with pytest.raises(ValueError, match="compatible evidence"):
        commit_study_review(tmp_path / "projects", data, review, decisions=decisions,
                            omissions={}, versions=[source["visits"][0]["protocol_version_id"]], hardware="biosemi")
    assert not (tmp_path / "projects").exists()


def test_versioned_study_snapshot_requires_its_effective_output(tmp_path):
    source = make_source()
    source["visits"][0]["recording"]["schema_version"] = 1
    imported = write_source(tmp_path, source)
    review = review_study(imported, tmp_path)
    assert review.rows[0].status == "exception" and "effective" in review.rows[0].problem
    assert review.rows[1].status == "missing"  # older unversioned, sparse recording declaration


@pytest.mark.parametrize("backends", [("egi_din",), ("ant_mylab_ttl",), ("egi_din", "ant_mylab_ttl")])
def test_exclusively_marker_only_study_directs_to_the_source_diagnostics(tmp_path, backends):
    source = make_source()
    source["visits"] = source["visits"][:len(backends)]
    for visit, backend in zip(source["visits"], backends, strict=True):
        visit["recording"].update(selected_backend=backend, effective_backend=backend)
    with pytest.raises(ValueError) as error:
        write_source(tmp_path, source)
    for backend in backends:
        diagnostic = "verify_egi_din" if backend == "egi_din" else "verify_ant_ttl"
        assert diagnostic in str(error.value)


def test_recording_proposals_and_out_of_version_matches_respect_hardware_format(tmp_path):
    source = make_source()
    _set_brainvision_cap(source, 0, "brainproducts_acticap_gacs_64")
    source["visits"][0]["protocol_version_id"] = str(uuid4())
    imported = write_source(tmp_path, source)
    for n in (1, 2):
        (tmp_path / f"P{n:03}.bdf").write_bytes(b"review only")
        _write_brainvision_recording(tmp_path / f"P{n:03}.vhdr")
    review = review_study(imported, tmp_path)
    assert [row.candidates for row in review.rows] == [("P001.vhdr",), ("P002.bdf",), ()]
    assert [row.status for row in review.rows] == ["clear", "clear", "missing"]
    with pytest.raises(ValueError, match="EEG file format"):
        commit_study_review(tmp_path / "projects", imported, review, versions=[source["visits"][1]["protocol_version_id"]],
                            hardware="biosemi", omissions={}, decisions={"exec-1": ("matched", "P001.bdf"),
                            "exec-2": ("matched", "P002.bdf"), "exec-3": ("awaiting_eeg", None)})


def test_study_with_all_eeg_deferred_cannot_seed_conflicting_scientific_methods(tmp_path):
    source = make_source()
    different = deepcopy(next(iter(source["setups"].values())))
    different["conditions"][0]["oddball_cycle_repeats_per_sequence"] += 10
    source["visits"][1]["setup_id"] = digest(different)
    source["setups"][digest(different)] = different
    imported = write_source(tmp_path, source)
    review = review_study(imported, tmp_path)
    with pytest.raises(ValueError, match="incompatible"):
        commit_study_review(tmp_path / "projects", imported, review, hardware="biosemi", omissions={},
                            decisions={r.visit["visit_id"]: ("awaiting_eeg", None) for r in review.rows},
                            versions=[source["visits"][0]["protocol_version_id"]])
    assert not (tmp_path / "projects").exists()


def test_cannot_apply_review_to_another_export_or_unreviewed_project(tmp_path):
    source = make_source()
    imported = write_source(tmp_path, source)
    review = review_study(imported, tmp_path)
    options = dict(versions=[source["visits"][0]["protocol_version_id"]], hardware="biosemi", omissions={},
                   decisions={r.visit["visit_id"]: ("awaiting_eeg", None) for r in review.rows})
    root = tmp_path / "projects"
    other = dict(source, study_id=str(uuid4()))
    with pytest.raises(ValueError, match="different Studio export"):
        commit_study_review(root, write_source(tmp_path, other), review, **options)
    assert not root.exists()
    project = commit_study_review(root, imported, review, **options)
    before = (project.project_root / "project.json").read_bytes()
    with pytest.raises(ValueError, match="different Studio export or Toolbox project"):
        commit_study_review(root, imported, review, existing=project, **options)
    assert (project.project_root / "project.json").read_bytes() == before


def test_changed_omitted_bdf_and_relocated_raw_folder_require_fresh_matches(tmp_path):
    from Main_App.processing.processing_controller import prepare_batch_files

    source = make_source()
    source["visits"] = source["visits"][:2]
    folder = tmp_path / "original"
    folder.mkdir()
    root = tmp_path / "projects"
    for n in (1, 2):
        (folder / f"P{n:03}.bdf").write_bytes(bytes([n]))
    imported = write_source(tmp_path, source)
    decisions = {"exec-1": ("matched", "P001.bdf"), "exec-2": ("matched", "P002.bdf")}
    options = dict(versions=[source["visits"][0]["protocol_version_id"]], hardware="biosemi")
    project = commit_study_review(root, imported, review_study(imported, folder), decisions=decisions,
                                  omissions={}, **options)
    moved = folder.rename(tmp_path / "relocated")
    review = review_study(imported, moved, project)
    assert [r.status for r in review.rows] == ["reconfirm_recording"] * 2
    project = commit_study_review(root, imported, review, existing=project, decisions=decisions, omissions={}, **options)
    assert set(prepare_batch_files(project)) == {moved / "P001.bdf", moved / "P002.bdf"}
    assert [r.status for r in review_study(imported, moved, project).rows] == ["matched"] * 2
    source["visits"].pop()
    source["roster_sequence"] += 1
    changed = write_source(tmp_path, source)
    (moved / "P002.bdf").write_bytes(b"replacement")
    revised = review_study(changed, moved, project)
    before = (project.project_root / "project.json").read_bytes()
    del decisions["exec-2"]
    with pytest.raises(ValueError, match="differs from its approval"):
        commit_study_review(root, changed, revised, existing=project, decisions=decisions,
                            omissions={"exec-2": "retain"}, **options)
    assert (project.project_root / "project.json").read_bytes() == before
    updated = commit_study_review(root, changed, revised, existing=project, decisions=decisions,
                                  omissions={"exec-2": "archive"}, **options)
    assert set(prepare_batch_files(updated)) == {moved / "P001.bdf"}


def test_bdf_copy_with_preserved_size_and_mtime_invalidates_approval_and_stale_preview(tmp_path):
    from Main_App.processing.processing_controller import prepare_batch_files, raw_file_info_for_path

    source = make_source()
    source["visits"] = source["visits"][:1]
    imported = write_source(tmp_path, source)
    raw = tmp_path / "raw"
    raw.mkdir()
    path = raw / "P001.bdf"
    path.write_bytes(b"old")
    stat = path.stat()
    root = tmp_path / "projects"
    options = dict(decisions={"exec-1": ("matched", path.name)}, hardware="biosemi", omissions={},
                   versions=[source["visits"][0]["protocol_version_id"]])
    project = commit_study_review(root, imported, review_study(imported, raw), **options)
    manifest_path = project.project_root / "project.json"
    approved_bytes = manifest_path.read_bytes()
    reviewed = review_study(imported, raw, project)
    assert reviewed.rows[0].status == "matched"
    replacement = tmp_path / "new.bdf"
    replacement.write_bytes(b"new")
    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    # Windows exposes ChangeTime at millisecond precision through pywin32.
    time.sleep(0.02)
    shutil.copy2(replacement, path)
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)
    assert review_study(imported, raw, project).rows[0].status == "reconfirm_recording"
    with pytest.raises(ValueError, match="Confirm the current BDF"):
        raw_file_info_for_path(project, path)
    with pytest.raises(ValueError, match="Confirm the current BDF"):
        prepare_batch_files(project)
    with pytest.raises(ValueError, match="changed after review"):
        commit_study_review(root, imported, reviewed, existing=project, **options)
    assert manifest_path.read_bytes() == approved_bytes
    historical = json.loads(approved_bytes)
    del historical["tools"]["studio_cohort"]["visits"]["exec-1"]["bdf_change_identity"]
    manifest_path.write_text(json.dumps(historical), encoding="utf-8")
    fresh = review_study(imported, raw, project)
    assert fresh.rows[0].status == "reconfirm_recording"
    project = commit_study_review(root, imported, fresh, existing=project, **options)
    assert review_study(imported, raw, project).rows[0].status == "matched"
    assert set(prepare_batch_files(project)) == {path}


def test_retained_brainvision_visit_with_changed_bytes_can_be_archived(tmp_path):
    source = make_source()
    source["visits"] = source["visits"][:2]
    raw = tmp_path / "raw"
    raw.mkdir()
    root = tmp_path / "projects"
    for index, visit in enumerate(source["visits"]):
        _set_brainvision_cap(source, index, "brainproducts_acticap_gacs_64")
        _write_brainvision_recording(raw / f"P{visit['participant_number']}.vhdr")
    imported = write_source(tmp_path, source)
    versions = [source["visits"][0]["protocol_version_id"]]
    decisions = {"exec-1": ("matched", "P001.vhdr"), "exec-2": ("matched", "P002.vhdr")}
    project = commit_study_review(root, imported, review_study(imported, raw), decisions=decisions,
                                  versions=versions, omissions={})
    source["visits"].pop(0)
    source["roster_sequence"] += 1
    del decisions["exec-1"]
    revised = write_source(tmp_path, source)
    project = commit_study_review(root, revised, review_study(revised, raw, project), existing=project,
                                  decisions=decisions, versions=versions, omissions={"exec-1": "retain"})
    assert review_study(revised, raw, project).omitted == {}
    (raw / "P001.eeg").write_bytes(b"updated signal")
    review = review_study(revised, raw, project)
    assert set(review.omitted) == {"exec-1"}
    with pytest.raises(ValueError, match="omitted visit exec-1 differs"):
        commit_study_review(root, revised, review, existing=project, decisions=decisions,
                            versions=versions, omissions={"exec-1": "retain"})
    saved = commit_study_review(root, revised, review, existing=project, decisions=decisions,
                                versions=versions, omissions={"exec-1": "archive"})
    assert saved.manifest["tools"]["studio_cohort"]["visits"]["exec-1"]["decision"] == "archived"


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
    damaged = root / "Unrelated project" / "project.json"
    damaged.parent.mkdir()
    for malformed in ("[", "[]", '{"tools": []}'):
        damaged.write_text(malformed)
        warnings = []
        assert find_study_project(root, source["study_id"], warnings=warnings).project_root == project.project_root
        assert str(damaged) in warnings[0]
        assert find_study_project(root, str(uuid4())) is None
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
    from openpyxl import Workbook
    initial = Workbook()
    initial.active.append(["Synthetic released result for first 20"])
    initial.save(book)
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
    from Main_App.projects.studio_archive import verified_archived_workbook
    assert verified_archived_workbook(root, prior) == root / prior["previous_result"]
    legacy = dict(prior)
    del legacy["previous_result_sha256"]
    assert verified_archived_workbook(root, legacy) == root / prior["previous_result"]
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


def test_new_study_only_accepts_the_reviewed_unreadable_siblings(tmp_path):
    source = make_source()
    imported = write_source(tmp_path, source)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "P001.bdf").write_bytes(b"synthetic")
    review = review_study(imported, raw)
    options = dict(decisions={"exec-1": ("matched", "P001.bdf"), "exec-2": ("awaiting_eeg", None),
                              "exec-3": ("awaiting_eeg", None)}, hardware="biosemi", omissions={},
                   versions=[source["visits"][0]["protocol_version_id"]])
    projects = tmp_path / "projects"
    first = projects / "Incomplete" / "project.json"
    first.parent.mkdir(parents=True)
    first.write_text("[")
    accepted = []
    assert find_study_project(projects, source["study_id"], warnings=accepted) is None
    assert len(accepted) == 1 and str(first) in accepted[0]
    with pytest.raises(ValueError, match="Reopen the Studio import"):
        commit_study_review(projects, imported, review, **options)
    second = projects / "Unreadable" / "project.json"
    second.parent.mkdir()
    second.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="Unreadable"):
        commit_study_review(projects, imported, review, accepted_unreadable=accepted, **options)
    accepted = []
    assert find_study_project(projects, source["study_id"], warnings=accepted) is None
    assert len(accepted) == 2
    project = commit_study_review(projects, imported, review, accepted_unreadable=accepted, **options)
    assert find_study_project(projects, source["study_id"]).project_root == project.project_root
    with pytest.raises(ValueError, match="already|was imported"):
        commit_study_review(projects, imported, review, accepted_unreadable=accepted, **options)


def test_archive_requires_a_regular_canonical_workbook_and_matching_digest(tmp_path):
    from Main_App.projects.studio_archive import verified_archived_workbook

    archives = tmp_path / ".fpvs_imports/studio/prior-results"
    archives.mkdir(parents=True)
    document = archives / ("a" * 64 + ".xlsx")
    document.write_bytes(b"not a workbook")
    receipt = {"previous_result": document.relative_to(tmp_path).as_posix(),
               "previous_result_sha256": hashlib.sha256(document.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match="readable XLSX"):
        verified_archived_workbook(tmp_path, receipt)
    with pytest.raises(ValueError, match="differs from its recorded checksum"):
        verified_archived_workbook(tmp_path, {**receipt, "previous_result_sha256": "0" * 64})
    with pytest.raises(ValueError, match="invalid workbook path"):
        verified_archived_workbook(tmp_path, {**receipt, "previous_result": ".fpvs_imports/studio/prior-results/note.txt"})
    with pytest.raises(ValueError, match="no verifiable release checksum"):
        verified_archived_workbook(tmp_path, {"previous_result": receipt["previous_result"]})


@pytest.mark.parametrize("parent", [".fpvs_imports", ".fpvs_imports/studio", ".fpvs_imports/studio/prior-results"])
def test_studio_managed_files_reject_linked_parents(tmp_path, parent):
    from Main_App.projects.studio_archive import archive_reviewed_result, studio_evidence_path

    root = tmp_path / "project"
    linked = root / parent
    linked.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        linked.symlink_to(elsewhere, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt" or exc.winerror != 1314:
            raise
        import _winapi
        _winapi.CreateJunction(str(elsewhere), str(linked))
    if linked.name != "prior-results":
        with pytest.raises(ValueError, match="must stay inside"):
            studio_evidence_path(root, "b" * 64)
    with pytest.raises(ValueError, match="must stay inside"):
        archive_reviewed_result(root, root / "not-needed.xlsx", "a" * 64, None)
    assert not list(elsewhere.iterdir())
