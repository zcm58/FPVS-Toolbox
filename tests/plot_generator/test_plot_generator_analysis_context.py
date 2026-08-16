"""Pure managed/unmanaged SNR analysis-context tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.processing.full_fft_provenance import (
    FULL_FFT_PROVENANCE_METHOD_VERSION,
    FullFftProvenance,
    FullFftProvenanceError,
    FullFftProvenanceStaleError,
)
from Tools.Plot_Generator import analysis_context


def _record(project_root: Path) -> FullFftProvenance:
    return FullFftProvenance(
        project_root=project_root.resolve(),
        saved_at="2026-08-16T12:00:00+00:00",
        method_version=FULL_FFT_PROVENANCE_METHOD_VERSION,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
        grid_fingerprint="grid-fingerprint",
        frequency_resolution_hz=0.025,
        upper_frequency_hz=40.0,
        frequency_column_count=1601,
        source_workbook_count=1,
        source_paths=("1 - Excel Data Files/Faces/P01_Faces_Results.xlsx",),
        cohort_fingerprint="cohort-fingerprint",
        source_fingerprint="source-identity-fingerprint",
        frequency_qc_fingerprint="qc-fingerprint",
        processing_export_fingerprint="ledger-fingerprint",
    )


def test_managed_context_uses_saved_rates_allowlist_and_exact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    workbook = (
        project_root
        / "1 - Excel Data Files"
        / "Faces"
        / "P01_Faces_Results.xlsx"
    )
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"workbook")
    record = _record(project_root)
    index = SimpleNamespace(
        manifest={},
        project_root=project_root.resolve(),
        scan_root=workbook.parent,
    )
    calls: list[object] = []

    def require_current(root, *, dataset_index=None):
        calls.append((Path(root), dataset_index))
        return record

    monkeypatch.setattr(
        analysis_context,
        "require_current_project_full_fft_provenance",
        require_current,
    )

    context = analysis_context.resolve_snr_analysis_context(
        index,
        legacy_base_frequency_hz=99.0,
        legacy_oddball_frequency_hz=9.9,
    )

    assert calls == [(project_root.resolve(), index)]
    assert context.base_frequency_hz == 6.0
    assert context.oddball_frequency_hz == 1.2
    assert context.allowed_workbook_paths == frozenset({workbook.resolve()})
    provenance = context.provenance
    assert provenance["source_kind"] == "managed_full_fft_provenance"
    assert provenance["method_version"] == FULL_FFT_PROVENANCE_METHOD_VERSION
    full_fft = provenance["full_fft_provenance"]
    assert full_fft["status"] == "current"
    assert full_fft["source_sheet"] == "FullFFT Amplitude (uV)"
    assert full_fft["fingerprints"] == {
        "cohort": "cohort-fingerprint",
        "sources": "source-identity-fingerprint",
        "frequency_qc": "qc-fingerprint",
        "processing_export": "ledger-fingerprint",
    }


def test_unmanaged_context_uses_positive_settings_fallback_without_project_state(
    tmp_path: Path,
) -> None:
    index = SimpleNamespace(
        manifest=None,
        project_root=tmp_path,
        scan_root=tmp_path,
    )

    context = analysis_context.resolve_snr_analysis_context(
        index,
        legacy_base_frequency_hz=-1.0,
        legacy_oddball_frequency_hz=float("nan"),
    )

    assert context.project_root is None
    assert context.allowed_workbook_paths is None
    assert context.base_frequency_hz == 6.0
    assert context.oddball_frequency_hz == 1.2
    assert context.provenance == {
        "source_kind": "legacy_application_settings",
        "schema_version": 1,
        "method_version": "legacy_application_settings",
        "resolved_rates_hz": {"base": 6.0, "oddball": 1.2},
        "full_fft_provenance": None,
    }
    assert context.warnings[0]["code"] == "legacy_application_settings"


def test_managed_context_rejects_saved_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    index = SimpleNamespace(
        manifest={},
        project_root=project_root.resolve(),
        scan_root=project_root,
    )
    record = replace(
        _record(project_root),
        source_paths=("../outside.xlsx",),
    )
    monkeypatch.setattr(
        analysis_context,
        "require_current_project_full_fft_provenance",
        lambda *_args, **_kwargs: record,
    )

    with pytest.raises(FullFftProvenanceError, match="outside its project root"):
        analysis_context.resolve_snr_analysis_context(
            index,
            legacy_base_frequency_hz=6.0,
            legacy_oddball_frequency_hz=1.2,
        )


def test_managed_context_revalidation_blocks_figure_output_after_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    workbook = (
        project_root
        / "1 - Excel Data Files"
        / "Faces"
        / "P01_Faces_Results.xlsx"
    )
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"workbook")
    captured = _record(project_root)
    changed = replace(
        captured,
        saved_at="2026-08-16T12:30:00+00:00",
        frequency_qc_fingerprint="changed-qc-fingerprint",
    )
    index = SimpleNamespace(
        manifest={},
        project_root=project_root.resolve(),
        scan_root=workbook.parent,
    )
    records = iter((captured, changed))
    calls: list[tuple[Path, dict[str, object]]] = []

    def require_current(root, **kwargs):
        calls.append((Path(root), dict(kwargs)))
        return next(records)

    monkeypatch.setattr(
        analysis_context,
        "require_current_project_full_fft_provenance",
        require_current,
    )
    context = analysis_context.resolve_snr_analysis_context(
        index,
        legacy_base_frequency_hz=6.0,
        legacy_oddball_frequency_hz=1.2,
    )
    with pytest.raises(
        FullFftProvenanceStaleError,
        match="changed during SNR plot generation",
    ):
        analysis_context.revalidate_snr_analysis_context(context)

    assert calls == [
        (project_root.resolve(), {"dataset_index": index}),
        (project_root.resolve(), {}),
    ]


def test_unmanaged_context_revalidation_does_not_read_project_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = analysis_context.resolve_snr_analysis_context(
        SimpleNamespace(
            manifest=None,
            project_root=tmp_path,
            scan_root=tmp_path,
        ),
        legacy_base_frequency_hz=6.0,
        legacy_oddball_frequency_hz=1.2,
    )
    monkeypatch.setattr(
        analysis_context,
        "require_current_project_full_fft_provenance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unmanaged publication must not read managed provenance")
        ),
    )

    analysis_context.revalidate_snr_analysis_context(context)
