"""Ledger-only reuse must retain the uncached QC evidence and failure behavior."""

from __future__ import annotations

import json
import os
import pickle
from pathlib import Path

import pytest

from Main_App.io import biosemi64_geometry_identity
from Main_App.processing import frequency_domain_qc as qc
from Main_App.processing import post_processing_context as context
from Main_App.processing import processing_ledger as ledger_io
from Main_App.processing.interpolation_burden import build_interpolation_burden
from Main_App.processing.roi_coverage import (
    ROI_COVERAGE_LEDGER_KEY,
    ROI_COVERAGE_STAGE_PRE_REVIEW,
    build_pre_review_roi_coverage,
)
from tests.processing.test_roi_final_release import (
    _cell, _outcomes, _processing_ledger, _snapshot, _write_source,
)


@pytest.fixture
def ledger_project(tmp_path):
    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    ledger = _processing_ledger("P01__visit_1")
    entry = ledger["entries"]["P01__visit_1"]
    entry["interpolation_burden"] = build_interpolation_burden(
        entry["preprocessing_outcome"], biosemi64_geometry_identity(),
    ).to_payload()
    coverage = build_pre_review_roi_coverage(
        tmp_path, outcome_ledger=_outcomes(_cell(source)),
        processing_ledger=ledger, roi_snapshot=_snapshot(), persist=False,
    )
    ledger[ROI_COVERAGE_LEDGER_KEY] = {
        ROI_COVERAGE_STAGE_PRE_REVIEW: coverage.to_payload(),
    }
    ledger_io.save_ledger(tmp_path, ledger)
    return tmp_path


def _bytes(root):
    return pickle.dumps(qc._load_independent_qc_context(root), protocol=5)


def _count_normalization(monkeypatch):
    calls = []
    original = qc._normalized_processing_qc_entry

    def counted(entry):
        calls.append(entry)
        return original(entry)

    monkeypatch.setattr(qc, "_normalized_processing_qc_entry", counted)
    return calls


def test_current_context_reuses_exact_detached_evidence_only_in_scope(ledger_project, monkeypatch):
    root = ledger_project
    expected = _bytes(root)
    calls = _count_normalization(monkeypatch)
    with context.post_processing_validation_scope():
        assert _bytes(root) == expected
        with context.post_processing_validation_scope():
            value = qc._load_independent_qc_context(root)
            value.cells.clear()
            value.processing_entries.clear()
            value.source_identity["status"] = "caller mutation"
            assert _bytes(root / ".") == expected
        assert len(calls) == 1
    assert _bytes(root) == expected
    assert len(calls) == 2
    with pytest.raises(RuntimeError, match="cancel"):
        with context.post_processing_validation_scope():
            assert _bytes(root) == expected
            raise RuntimeError("cancel")
    assert not context.validation_scope_active()
    with context.post_processing_validation_scope():
        assert _bytes(root) == expected
    assert len(calls) == 4


def test_ledger_bytes_invalidate_even_when_all_stat_fields_match(ledger_project, monkeypatch):
    root = ledger_project
    path = ledger_io.ledger_path(root)
    expected = _bytes(root)
    calls = _count_normalization(monkeypatch)
    with context.post_processing_validation_scope():
        assert _bytes(root) == expected
        old_stat = path.stat()
        original_stat = Path.stat
        data = path.read_bytes().replace(b"\n", b" ", 1)
        path.write_bytes(data)
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        monkeypatch.setattr(
            Path, "stat", lambda self, *a, **kw: (
                old_stat if self == path else original_stat(self, *a, **kw)
            ),
        )
        assert _bytes(root) == expected
        assert len(calls) == 2


@pytest.mark.parametrize("damage", ["missing", "corrupt", "invalid_coverage", "invalid_entry"])
def test_missing_corrupt_and_invalid_evidence_keeps_original_diagnostics(
    ledger_project, monkeypatch, caplog, damage,
):
    root = ledger_project
    path = ledger_io.ledger_path(root)
    with context.post_processing_validation_scope():
        qc._load_independent_qc_context(root)
        if damage == "missing":
            path.unlink()
        elif damage == "corrupt":
            path.write_bytes(b"{corrupt")
        else:
            data = json.loads(path.read_text())
            if damage == "invalid_coverage":
                data[ROI_COVERAGE_LEDGER_KEY][ROI_COVERAGE_STAGE_PRE_REVIEW] = {}
            else:
                data["entries"]["P01__visit_1"].pop("interpolation_burden")
            path.write_text(json.dumps(data))
        first = qc._load_independent_qc_context(root)
        second = qc._load_independent_qc_context(root)
    expected = qc._load_independent_qc_context(root)
    assert first.source_identity["status"] != "current"
    assert pickle.dumps(first) == pickle.dumps(second) == pickle.dumps(expected)
    if damage == "corrupt":
        assert sum(r.message == "processing_ledger_unreadable" for r in caplog.records) == 3


def test_change_during_validation_does_not_admit_result(ledger_project, monkeypatch):
    root = ledger_project
    path = ledger_io.ledger_path(root)
    original = qc._normalized_processing_qc_entry
    calls = []

    def changing(entry):
        calls.append(1)
        path.write_bytes(path.read_bytes() + b" ")
        return original(entry)

    monkeypatch.setattr(qc, "_normalized_processing_qc_entry", changing)
    with context.post_processing_validation_scope():
        assert _bytes(root) == _bytes(root)
    assert len(calls) == 2


def test_live_ledger_path_retarget_does_not_reuse_old_resolved_dependency(ledger_project, monkeypatch):
    root = ledger_project
    first_path = ledger_io.ledger_path(root)
    second_path = first_path.with_name("replacement.json")
    second_path.write_bytes(first_path.read_bytes())
    target = [first_path]
    monkeypatch.setattr(ledger_io, "ledger_path", lambda _root: target[0])
    calls = _count_normalization(monkeypatch)
    with context.post_processing_validation_scope():
        expected = _bytes(root)
        target[0] = second_path
        assert _bytes(root) == expected
        assert len(calls) == 2


def test_temporary_ledger_retarget_cannot_admit_evidence_under_original_key(
    ledger_project, monkeypatch,
):
    root = ledger_project
    original_path = ledger_io.ledger_path(root)
    alternate_path = original_path.with_name("alternate.json")
    alternate = json.loads(original_path.read_text())
    evidence = {"marker": "alternate ledger"}
    alternate["entries"]["P01__visit_1"]["kurtosis_qc_evidence"] = {
        **evidence, "fingerprint": qc._hash_payload(evidence),
    }
    alternate_path.write_text(json.dumps(alternate))
    original_read = qc._read_independent_qc_context
    expected = pickle.dumps(original_read(root), protocol=5)
    target = [original_path]
    monkeypatch.setattr(ledger_io, "ledger_path", lambda _root: target[0])

    def temporary_retarget(project_root, **kwargs):
        if kwargs.get("ledger_snapshot") is not None:
            return original_read(project_root, **kwargs)
        target[0] = alternate_path
        try:
            return original_read(project_root, **kwargs)
        finally:
            target[0] = original_path

    monkeypatch.setattr(qc, "_read_independent_qc_context", temporary_retarget)
    with context.post_processing_validation_scope():
        assert _bytes(root) == expected
        assert _bytes(root) == expected


def test_oversized_context_falls_back_without_retention(ledger_project, monkeypatch):
    monkeypatch.setattr(qc, "_INDEPENDENT_QC_CACHE_MAX_BYTES", 1)
    calls = _count_normalization(monkeypatch)
    with context.post_processing_validation_scope():
        assert _bytes(ledger_project) == _bytes(ledger_project)
    assert len(calls) == 2


def test_oversized_ledger_falls_back_without_hashing(ledger_project, monkeypatch):
    monkeypatch.setattr(qc, "_INDEPENDENT_QC_LEDGER_MAX_BYTES", 1)

    def unexpected_hash(*args, **kwargs):
        pytest.fail("oversized ledger must not enter cache validation")

    monkeypatch.setattr(context, "capture_validation_files", unexpected_hash)
    calls = _count_normalization(monkeypatch)
    with context.post_processing_validation_scope():
        assert _bytes(ledger_project) == _bytes(ledger_project)
    assert len(calls) == 2


def test_edit_during_cache_hit_falls_back(ledger_project, monkeypatch):
    root = ledger_project
    path = ledger_io.ledger_path(root)
    expected = _bytes(root)
    calls = _count_normalization(monkeypatch)
    original_copy = context.deepcopy

    def editing_copy(value):
        path.write_bytes(path.read_bytes() + b" ")
        return original_copy(value)

    with context.post_processing_validation_scope():
        assert _bytes(root) == expected
        monkeypatch.setattr(context, "deepcopy", editing_copy)
        assert _bytes(root) == expected
        assert len(calls) == 2


def test_only_one_project_context_is_retained(ledger_project, monkeypatch):
    root = ledger_project
    other = root / "other_project"
    ledger_io.save_ledger(other, ledger_io.load_ledger(root))
    calls = _count_normalization(monkeypatch)
    with context.post_processing_validation_scope():
        expected = _bytes(root)
        assert _bytes(other) == expected
        assert _bytes(other) == expected
        assert _bytes(root) == expected
    assert len(calls) == 3


@pytest.mark.parametrize("oversized", [False, True])
def test_uncached_loader_error_is_not_retried_as_cache_failure(
    ledger_project, monkeypatch, oversized,
):
    calls = []

    def failing(_entry):
        calls.append(1)
        raise RuntimeError("original validation failure")

    monkeypatch.setattr(qc, "_normalized_processing_qc_entry", failing)
    if oversized:
        monkeypatch.setattr(qc, "_INDEPENDENT_QC_LEDGER_MAX_BYTES", 1)
    with context.post_processing_validation_scope():
        with pytest.raises(RuntimeError, match="original validation failure"):
            qc._load_independent_qc_context(ledger_project)
    assert len(calls) == 1


def test_cache_allocation_failure_preserves_uncached_result(ledger_project, monkeypatch):
    expected = _bytes(ledger_project)

    def exhausted(*args, **kwargs):
        raise MemoryError("cache only")

    monkeypatch.setattr(context, "remember_validation", exhausted)
    with context.post_processing_validation_scope():
        assert _bytes(ledger_project) == expected


def test_namespace_limit_preserves_other_validation_entries():
    with context.post_processing_validation_scope():
        context.remember_validation("other", "keep", [0], files=())
        for index in range(3):
            context.remember_validation(
                "bounded", index, [index], files=(), max_namespace_entries=1,
            )
        assert context.cached_validation("bounded", 0) is context.CACHE_MISS
        assert context.cached_validation("bounded", 1) is context.CACHE_MISS
        assert context.cached_validation("bounded", 2) == [2]
        assert context.cached_validation("other", "keep") == [0]
