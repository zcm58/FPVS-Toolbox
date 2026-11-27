from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from Main_App.processing.roi_coverage import RoiCoverageGateError
from Main_App.processing.canonical_harmonics import CanonicalHarmonicSelectionError
from Tools.Individual_Detectability import core, export_run
from Tools.Individual_Detectability.core import ConditionInfo, DetectabilitySettings, ManagedDetectabilityInputError
from Tools.Individual_Detectability.project_coverage import (
    load_managed_project_coverage,
    load_managed_workbook_coverage,
    select_managed_conditions,
)
from Tools.Stats.analysis.canonical_harmonics import CUSTOM_HARMONIC_SOURCE
from Main_App.projects import GroupInfo


def _managed_fixture(tmp_path, monkeypatch, *, omitted=(), index_excluded=()):
    """Two visits and conditions let tests distinguish every exclusion scope."""

    from Main_App.processing import roi_coverage

    records = tuple(
        SimpleNamespace(
            participant_id=participant,
            group_id=None,
            recording_id=f"{participant}__{session}",
            condition=condition,
            path=tmp_path / f"{participant}__{session}_{condition}_Results.xlsx",
        )
        for participant in ("P1", "P2")
        for session in ("first", "second")
        for condition in ("Faces", "Objects")
    )
    cells = tuple(
        SimpleNamespace(
            participant_id=record.participant_id,
            recording_id=record.recording_id,
            condition_label=record.condition,
            workbook_path=str(record.path),
            downstream_cell_excluded=index in omitted,
            source_evidence=SimpleNamespace(
                retained_scalp_identity=SimpleNamespace(channels=("O1", "O2")),
                allowed_auxiliary_rows=(),
                fingerprint=f"source-{index}",
            ),
        )
        for index, record in enumerate(records)
    )
    receipt = SimpleNamespace(fingerprint="release-one")
    monkeypatch.setattr(
        roi_coverage,
        "require_project_final_release",
        lambda root: (object(), SimpleNamespace(cells=cells), receipt),
    )
    index = SimpleNamespace(
        manifest={},
        workbooks=tuple(row for idx, row in enumerate(records) if idx not in index_excluded),
        excluded_workbooks=tuple(records[idx] for idx in index_excluded),
    )
    provenance = SimpleNamespace(
        project_root=tmp_path,
        source_paths=tuple(
            row.path.name for idx, row in enumerate(records)
            if idx not in set(omitted) | set(index_excluded)
        ),
    )
    conditions = [
        ConditionInfo(condition, tmp_path, [row.path for row in records if row.condition == condition])
        for condition in ("Faces", "Objects")
    ]
    return records, cells, receipt, index, provenance, conditions


def _select(tmp_path, fixture, *, checkbox_exclusions=()):
    _records, _cells, _receipt, index, provenance, conditions = fixture
    coverage = load_managed_project_coverage(tmp_path)
    return select_managed_conditions(
        conditions,
        dataset_index=index,
        provenance=provenance,
        coverage=coverage,
        excluded_participants=set(checkbox_exclusions),
    )


def test_same_condition_exports_one_grid_per_group_and_rejects_regrouped_selection(tmp_path, monkeypatch):
    fixture = _managed_fixture(tmp_path, monkeypatch)
    records, _cells, _receipt, index, _provenance, _conditions = fixture
    groups = {
        key: GroupInfo(key, key.title(), key.title(), tmp_path / "Input" / key)
        for key in ("simulated", "comparison")
    }
    index.groups = groups
    for record in records:
        record.group_id = "simulated" if record.participant_id == "P1" else "comparison"
    request = _export_request(tmp_path, monkeypatch, fixture)
    request.conditions[:] = [
        ConditionInfo("Faces", tmp_path, [
            record.path for record in records if record.group_id == group.group_id and record.condition == "Faces"
        ], group=group)
        for group in groups.values()
    ]
    monkeypatch.setattr(export_run, "prevalidate_managed_conditions", lambda *_: None)
    rendered = {}

    def record_generation(*, condition, output_dir, **_):
        rendered[output_dir.relative_to(request.output_root).as_posix()] = list(condition.files)
        return len(condition.files), len(condition.files)

    monkeypatch.setattr(export_run, "generate_condition_figure", record_generation)
    export_run.run_detectability_export(request, log=lambda _: None, status=lambda _: None, progress=lambda _: None)
    assert rendered == {f"Faces/{cond.group.folder_name}": cond.files for cond in request.conditions}
    assert set(rendered) == {"Faces/Simulated", "Faces/Comparison"}
    records[0].group_id = "comparison"
    with pytest.raises(CanonicalHarmonicSelectionError, match="project condition or group changed"):
        export_run.run_detectability_export(request, log=lambda _: None, status=lambda _: None, progress=lambda _: None)


def _export_request(tmp_path, monkeypatch, fixture, *, excluded=()):
    _records, _cells, _receipt, index, provenance, conditions = fixture
    monkeypatch.setattr("Main_App.projects.load_project_dataset_index", lambda root: index)
    monkeypatch.setattr(
        "Main_App.processing.full_fft_provenance.require_current_project_full_fft_provenance",
        lambda root, *, dataset_index: provenance,
    )
    return export_run.RunRequest(
        input_root=tmp_path,
        output_root=tmp_path / "out",
        project_root=tmp_path,
        conditions=conditions,
        output_stems={},
        excluded_participants=set(excluded),
        settings=DetectabilitySettings(
            harmonic_source=CUSTOM_HARMONIC_SOURCE, oddball_harmonics_hz=[1.2],
        ),
    )


@pytest.mark.parametrize(
    "omitted",
    [(0, 1, 2, 3), (0, 1), (0, 2), (0,)],
    ids=["participant", "recording", "participant-condition", "recording-condition"],
)
def test_final_coverage_exclusions_keep_exact_sibling_visits_and_conditions(
    tmp_path, monkeypatch, omitted
):
    fixture = _managed_fixture(tmp_path, monkeypatch, omitted=omitted)
    records, cells, *_ = fixture
    assert all(cells[idx].source_evidence is not None for idx in omitted)

    coverage = load_managed_workbook_coverage(tmp_path)
    selected = _select(tmp_path, fixture)

    expected = {row.path for idx, row in enumerate(records) if idx not in omitted}
    assert set(coverage) == expected
    assert {path for condition in selected for path in condition.files} == expected


def test_index_exclusion_is_authorized_without_widening_recording_condition(
    tmp_path, monkeypatch
):
    fixture = _managed_fixture(tmp_path, monkeypatch, index_excluded=(0,))
    records = fixture[0]
    assert {path for cond in _select(tmp_path, fixture) for path in cond.files} == {
        row.path for row in records[1:]
    }


@pytest.mark.parametrize("kind", ["checkbox", "saved-manual"])
def test_explicit_participant_exclusions_precede_retained_coverage_validation(
    tmp_path, monkeypatch, kind
):
    fixture = _managed_fixture(tmp_path, monkeypatch)
    records, cells, _receipt, index, provenance, _conditions = fixture
    for cell in cells[:4]:
        cell.source_evidence = None
    provenance.source_paths = tuple(row.path.name for row in records[4:])
    checkbox = {" p1 "} if kind == "checkbox" else set()
    if kind == "saved-manual":
        index.manifest = {"preprocessing": {"manual_excluded_participants": ["P1"]}}

    selected = _select(tmp_path, fixture, checkbox_exclusions=checkbox)

    assert {path for condition in selected for path in condition.files} == {
        row.path for row in records[4:]
    }


@pytest.mark.parametrize("missing", ["coverage", "provenance", "identity"])
def test_unexpected_missing_source_is_fatal_instead_of_silent_intersection(
    tmp_path, monkeypatch, missing
):
    fixture = _managed_fixture(tmp_path, monkeypatch)
    records, cells, _receipt, index, provenance, _conditions = fixture
    if missing == "coverage":
        cells[0].source_evidence = None
        expected = "not a current QC-20/QC-21"
    elif missing == "provenance":
        provenance.source_paths = tuple(row.path.name for row in records[1:])
        expected = "outside the current FullFFT source release"
    else:
        index.workbooks = records[1:]
        expected = "without canonical project identity"

    with pytest.raises(RoiCoverageGateError, match=expected):
        _select(tmp_path, fixture)


def test_unknown_filename_cannot_be_hidden_by_checkbox_participant(tmp_path, monkeypatch):
    fixture = _managed_fixture(tmp_path, monkeypatch)
    fixture[3].workbooks = fixture[0][1:]
    with pytest.raises(RoiCoverageGateError, match="without canonical project identity"):
        _select(tmp_path, fixture, checkbox_exclusions={"P1"})


def test_excluded_cells_cannot_mask_duplicate_final_coverage(tmp_path, monkeypatch):
    fixture = _managed_fixture(tmp_path, monkeypatch, omitted=(0,))
    fixture[1][1].workbook_path = fixture[1][0].workbook_path
    with pytest.raises(RoiCoverageGateError, match="duplicate final QC-21"):
        load_managed_project_coverage(tmp_path)


def test_export_uses_filtered_sources_before_read_cache_metadata_and_render(
    tmp_path, monkeypatch
):
    fixture = _managed_fixture(tmp_path, monkeypatch, omitted=(0,))
    records, cells, receipt, _index, provenance, conditions = fixture
    # An unreadable/stale excluded input with an old cache must never be touched.
    excluded_path = records[0].path
    excluded_path.write_bytes(b"not a readable workbook")
    cache_path = tmp_path / core._CACHE_DIRNAME / "old-excluded.npz"
    cache_path.parent.mkdir()
    cache_path.write_bytes(b"old cache")
    reads = []
    monkeypatch.setattr(core, "_require_managed_fullfft_noise_support", lambda path, *_: reads.append(path))
    rendered = []
    rendered_coverage = {}

    def generate(**kwargs):
        paths = kwargs["condition"].files
        rendered.extend(paths)
        rendered_coverage.update(kwargs["managed_coverage_by_workbook"])
        return len(paths), len(paths)

    monkeypatch.setattr(export_run, "generate_condition_figure", generate)
    request = _export_request(tmp_path, monkeypatch, fixture, excluded={"P2"})
    events = []
    export_run.run_detectability_export(request, log=events.append, status=events.append, progress=events.append)

    expected = {row.path for row in records[1:4]}
    assert set(reads) == expected == set(rendered)
    assert conditions[0].files == [row.path for row in records if row.condition == "Faces"]
    metadata = json.loads((request.output_root / "individual_detectability_custom_harmonics_metadata.json").read_text())
    assert set(metadata["managed_source_coverage_fingerprints"]) == {str(path) for path in expected}
    assert metadata["excluded_participants"] == ["P2"]
    assert cache_path.read_bytes() == b"old cache"

    # A later accepted release must refresh exclusions and the retained cache key.
    old_coverage = rendered_coverage[records[1].path]
    cells[0].downstream_cell_excluded = False
    provenance.source_paths = tuple(row.path.name for row in records)
    receipt.fingerprint = "release-two"
    rendered.clear()
    export_run.run_detectability_export(request, log=events.append, status=events.append, progress=events.append)
    assert excluded_path in rendered
    assert core._settings_fingerprint(request.settings, old_coverage) != core._settings_fingerprint(
        request.settings, rendered_coverage[records[1].path]
    )


@pytest.mark.parametrize("qc_only", [False, True])
def test_all_explicitly_excluded_conditions_are_omitted(tmp_path, monkeypatch, qc_only):
    fixture = _managed_fixture(tmp_path, monkeypatch, omitted=range(8) if qc_only else ())
    excluded = set() if qc_only else {"P1", "P2"}
    assert _select(tmp_path, fixture, checkbox_exclusions=excluded) == []
    request = _export_request(tmp_path, monkeypatch, fixture, excluded=excluded)
    log, status, progress = [], [], []
    assert export_run.run_detectability_export(
        request, log=log.append, status=status.append, progress=progress.append,
    ) is None
    assert log == ["No figures were generated. No selected inputs remain after participant and project QC exclusions."]
    assert status == [] and progress == []
    assert not request.output_root.exists()


def test_stale_second_condition_blocks_entire_export_before_writes(tmp_path, monkeypatch):
    fixture = _managed_fixture(tmp_path, monkeypatch)
    request = _export_request(tmp_path, monkeypatch, fixture)
    stale = request.conditions[1].files[0]
    validated = []

    def validate(path, *_args):
        validated.append(path)
        if path == stale:
            raise ValueError("stale source")

    def unexpected_render(**_kwargs):
        pytest.fail("Rendered before all conditions passed prevalidation")

    monkeypatch.setattr(core, "_require_managed_fullfft_noise_support", validate)
    monkeypatch.setattr(export_run, "generate_condition_figure", unexpected_render)
    events = []
    with pytest.raises(ManagedDetectabilityInputError, match="stale source"):
        export_run.run_detectability_export(request, log=events.append, status=events.append, progress=events.append)
    assert validated == [*request.conditions[0].files, stale]
    assert not request.output_root.exists()


def test_managed_canonical_participant_identity_changes_legacy_cache_key(tmp_path, monkeypatch):
    from dataclasses import replace

    fixture = _managed_fixture(tmp_path, monkeypatch)
    coverage = load_managed_workbook_coverage(tmp_path)[fixture[0][0].path]
    settings = DetectabilitySettings(oddball_harmonics_hz=[1.2])

    assert coverage.participant_id == "P1"
    assert core._settings_fingerprint(settings, coverage) != core._settings_fingerprint(
        settings, replace(coverage, participant_id="")
    )
