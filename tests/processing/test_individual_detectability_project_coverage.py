from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Main_App.processing.roi_coverage import RoiCoverageGateError
from Tools.Individual_Detectability.core import (
    ConditionInfo,
    DetectabilitySettings,
    ManagedDetectabilityInputError,
    _cache_path_for,
    _load_cache_npz,
    _process_one_participant,
    _save_cache_npz,
    _settings_fingerprint,
    _managed_workbook_coverage_or_input_error,
    build_fullfft_harmonic_plan,
    generate_condition_figure,
    prevalidate_managed_conditions,
    require_complete_harmonic_noise_support,
)
from Tools.Individual_Detectability.project_coverage import (
    ManagedWorkbookCoverage,
    load_managed_workbook_coverage,
    require_selected_workbooks_released,
    validate_managed_fullfft_rows,
)


def _coverage(
    workbook_path: Path,
    *,
    channels: tuple[str, ...] = ("O1", "O2"),
    source_fingerprint: str = "source-fingerprint",
) -> ManagedWorkbookCoverage:
    return ManagedWorkbookCoverage(
        workbook_path=workbook_path.resolve(strict=False),
        retained_scalp_channels=channels,
        allowed_auxiliary_rows=(),
        source_evidence_fingerprint=source_fingerprint,
        final_release_receipt_fingerprint="release-fingerprint",
    )


def test_managed_workbook_coverage_comes_from_current_final_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Main_App.processing import roi_coverage

    workbook = tmp_path / "P1_Faces_Results.xlsx"
    source = SimpleNamespace(
        retained_scalp_identity=SimpleNamespace(channels=("O1", "O2")),
        allowed_auxiliary_rows=(),
        fingerprint="source-fingerprint",
    )
    final_coverage = SimpleNamespace(
        cells=(SimpleNamespace(
            source_evidence=source,
            workbook_path=str(workbook),
            downstream_cell_excluded=False,
            participant_id="P1",
        ),)
    )
    receipt = SimpleNamespace(fingerprint="release-fingerprint")
    calls: list[Path] = []

    def fake_require(project_root: str | Path):
        calls.append(Path(project_root))
        return object(), final_coverage, receipt

    monkeypatch.setattr(roi_coverage, "require_project_final_release", fake_require)

    result = load_managed_workbook_coverage(tmp_path)

    assert calls == [tmp_path]
    assert result[workbook.resolve(strict=False)] == replace(
        _coverage(workbook), participant_id="P1"
    )


def test_selected_managed_workbook_must_belong_to_final_release(
    tmp_path: Path,
) -> None:
    released = tmp_path / "P1_Faces_Results.xlsx"
    unreviewed = tmp_path / "P2_Faces_Results.xlsx"

    with pytest.raises(RoiCoverageGateError, match="not a current QC-20/QC-21"):
        require_selected_workbooks_released(
            [released, unreviewed],
            {released.resolve(strict=False): _coverage(released)},
        )


def test_condition_lookup_reports_concise_managed_input_error(tmp_path: Path) -> None:
    workbook = tmp_path / "P1_Faces_Results.xlsx"

    with pytest.raises(
        ManagedDetectabilityInputError,
        match="not a current QC-20/QC-21 released output",
    ):
        _managed_workbook_coverage_or_input_error(workbook, {})


def test_managed_fullfft_rejects_missing_frozen_scalp_row(tmp_path: Path) -> None:
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    frame = pd.DataFrame(
        [
            {"Electrode": "O1", "1.2000_Hz": 2.0},
        ]
    )

    with pytest.raises(
        RoiCoverageGateError,
        match="missing retained scalp channel.*O2",
    ):
        validate_managed_fullfft_rows(
            frame,
            coverage=_coverage(workbook),
            required_columns=("1.2000_Hz",),
            electrode_column="Electrode",
        )


def test_managed_fullfft_accepts_each_frozen_scalp_row_once(tmp_path: Path) -> None:
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    frame = pd.DataFrame(
        [
            {"Electrode": "O2", "1.2000_Hz": 3.0},
            {"Electrode": "O1", "1.2000_Hz": 2.0},
        ]
    )

    validate_managed_fullfft_rows(
        frame,
        coverage=_coverage(workbook),
        required_columns=("1.2000_Hz",),
        electrode_column="Electrode",
    )


def test_detectability_cache_identity_includes_final_coverage(tmp_path: Path) -> None:
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    settings = DetectabilitySettings(oddball_harmonics_hz=[1.2])

    first = _settings_fingerprint(
        settings,
        _coverage(workbook, source_fingerprint="first"),
    )
    second = _settings_fingerprint(
        settings,
        _coverage(workbook, source_fingerprint="second"),
    )

    assert first != second


def test_managed_noise_support_rejects_target_at_fft_boundary() -> None:
    columns = ["Electrode", *[f"{index / 10:.4f}_Hz" for index in range(21)]]
    boundary_plan = build_fullfft_harmonic_plan(columns, [0.9])

    with pytest.raises(ValueError, match=r"0\.9 Hz: -10"):
        require_complete_harmonic_noise_support(boundary_plan)


def test_managed_noise_support_rejects_one_missing_neighbor_bin() -> None:
    columns = ["Electrode", *[f"{index / 10:.4f}_Hz" for index in range(21)]]
    complete_plan = build_fullfft_harmonic_plan(columns, [1.0])
    missing_neighbor_plan = replace(
        complete_plan,
        column_bin_pairs=tuple(
            pair for pair in complete_plan.column_bin_pairs if pair[1] != 3
        ),
    )

    with pytest.raises(ValueError, match=r"1 Hz: -7"):
        require_complete_harmonic_noise_support(missing_neighbor_plan)


def test_managed_noise_support_rejects_missing_physical_frequency_column() -> None:
    columns = [
        "Electrode",
        *[
            f"{index / 10:.4f}_Hz"
            for index in range(41)
            if index != 13
        ],
    ]
    compressed_plan = build_fullfft_harmonic_plan(columns, [2.0])

    with pytest.raises(ValueError, match=r"2 Hz: -7"):
        require_complete_harmonic_noise_support(compressed_plan)


def test_projectless_plan_preserves_partial_boundary_neighbors() -> None:
    columns = ["Electrode", *[f"{index / 10:.4f}_Hz" for index in range(21)]]

    plan = build_fullfft_harmonic_plan(columns, [0.9])

    assert plan.harmonic_list == (0.9,)


def test_managed_boundary_check_runs_before_existing_cache(
    tmp_path: Path,
) -> None:
    np = pytest.importorskip("numpy")
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    columns = [f"{index / 10:.4f}_Hz" for index in range(21)]
    frame = pd.DataFrame(
        [{"Electrode": "O1", **{column: 1.0 for column in columns}}]
    )
    with pd.ExcelWriter(workbook) as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)

    settings = DetectabilitySettings(oddball_harmonics_hz=[0.9])
    coverage = _coverage(workbook, channels=("O1",))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_path = _cache_path_for(workbook, settings, cache_dir, coverage)
    np.savez_compressed(
        cache_path,
        pid=np.asarray("P1"),
        n_sig=np.asarray(0),
        z_topo=np.asarray([1.64]),
        has_snr=np.asarray(0),
        snr_x=np.asarray([]),
        snr_y=np.asarray([]),
    )

    result = _process_one_participant(
        str(workbook),
        "P1",
        settings,
        str(cache_dir),
        coverage,
    )

    assert result.ok is False
    assert result.fatal_integrity_error is True
    assert "0.9 Hz: -10" in str(result.err)


def test_managed_condition_outer_cache_cannot_bypass_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import concurrent.futures

    np = pytest.importorskip("numpy")
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    columns = [f"{index / 10:.4f}_Hz" for index in range(21)]
    frame = pd.DataFrame(
        [{"Electrode": "O1", **{column: 1.0 for column in columns}}]
    )
    with pd.ExcelWriter(workbook) as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)

    settings = DetectabilitySettings(oddball_harmonics_hz=[0.9])
    coverage = _coverage(workbook, channels=("O1",))
    cache_dir = tmp_path / ".individual_detectability_cache"
    cache_path = _cache_path_for(workbook, settings, cache_dir, coverage)
    cache_path.parent.mkdir()
    np.savez_compressed(
        cache_path,
        pid=np.asarray("P1"),
        n_sig=np.asarray(0),
        z_topo=np.asarray([1.64]),
        has_snr=np.asarray(0),
        snr_x=np.asarray([]),
        snr_y=np.asarray([]),
    )

    class ImmediateFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class InlineExecutor:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, function, *args):
            return ImmediateFuture(function(*args))

    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(concurrent.futures, "as_completed", lambda futures: futures)

    with pytest.raises(ManagedDetectabilityInputError, match=r"0\.9 Hz: -10"):
        generate_condition_figure(
            condition=ConditionInfo("Faces", tmp_path, [workbook]),
            output_dir=tmp_path / "figures",
            output_stem="detectability",
            excluded=set(),
            settings=settings,
            export_png=False,
            log=lambda _message: None,
            managed_coverage_by_workbook={workbook.resolve(strict=False): coverage},
        )


def test_cache_save_load_round_trip_uses_requested_path(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    cache_path = tmp_path / "participant.npz"

    _save_cache_npz(
        cache_path,
        pid="P1",
        n_sig=2,
        z_topo=np.asarray([1.64, 2.5]),
        snr_x=np.asarray([-0.1, 0.0, 0.1]),
        snr_y=np.asarray([1.0, 1.5, 1.0]),
    )
    loaded = _load_cache_npz(cache_path)

    assert cache_path.is_file()
    assert not cache_path.with_suffix(".npz.tmp.npz").exists()
    assert loaded.pid == "P1"
    assert loaded.n_sig == 2
    np.testing.assert_allclose(loaded.z_topo, [1.64, 2.5])
    np.testing.assert_allclose(loaded.snr_x, [-0.1, 0.0, 0.1])
    np.testing.assert_allclose(loaded.snr_y, [1.0, 1.5, 1.0])


def test_two_condition_managed_prevalidation_fails_before_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Tools.Individual_Detectability import core

    first = tmp_path / "P1_Faces_Results.xlsx"
    second = tmp_path / "P1_Objects_Results.xlsx"
    output_root = tmp_path / "individual_detectability"
    calls: list[Path] = []

    def validate(path, _settings, _coverage):
        calls.append(path)
        if path == second:
            raise ValueError("late workbook is invalid")

    monkeypatch.setattr(core, "_require_managed_fullfft_noise_support", validate)

    with pytest.raises(
        ManagedDetectabilityInputError,
        match="P1_Objects_Results.xlsx: late workbook is invalid",
    ):
        prevalidate_managed_conditions(
            (
                ConditionInfo("Faces", tmp_path, [first]),
                ConditionInfo("Objects", tmp_path, [second]),
            ),
            DetectabilitySettings(oddball_harmonics_hz=[1.2]),
            {
                first.resolve(strict=False): _coverage(first),
                second.resolve(strict=False): _coverage(second),
            },
        )

    assert calls == [first, second]
    assert not output_root.exists()
    assert not (output_root / "individual_detectability_metadata.json").exists()


def test_managed_participant_read_error_is_fatal_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Tools.Individual_Detectability import core

    workbook = tmp_path / "P1_Faces_Results.xlsx"
    pd.DataFrame({"Electrode": ["Oz"]}).to_excel(workbook, index=False)
    monkeypatch.setattr(
        core,
        "_excel_minimal_read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("FullFFT source is incomplete")
        ),
    )
    monkeypatch.setattr(
        core,
        "_require_managed_fullfft_noise_support",
        lambda *_args, **_kwargs: None,
    )

    result = _process_one_participant(
        str(workbook),
        "P1",
        DetectabilitySettings(oddball_harmonics_hz=[1.2]),
        str(tmp_path / "cache"),
        _coverage(workbook),
    )

    assert result.ok is False
    assert result.fatal_integrity_error is True
    assert result.err == "FullFFT source is incomplete"


def test_projectless_participant_read_error_preserves_legacy_skip_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Tools.Individual_Detectability import core

    workbook = tmp_path / "P1_Faces_Results.xlsx"
    workbook.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        core,
        "_excel_minimal_read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("Unreadable")),
    )

    result = _process_one_participant(
        str(workbook),
        "P1",
        DetectabilitySettings(oddball_harmonics_hz=[1.2]),
        str(tmp_path / "cache"),
    )

    assert result.ok is False
    assert result.fatal_integrity_error is False


def test_individual_detectability_reads_companions_and_rejects_stale_cache(tmp_path):
    import numpy as np

    from Main_App.Shared.post_process_excel import write_results_workbook
    from Main_App.io.spectral_data import SpectralDataError
    from Tools.Individual_Detectability import core

    frequencies = np.arange(0, 3.01, 0.05)
    columns = [f"{value:.4f}_Hz" for value in frequencies]
    frame = pd.DataFrame(np.arange(2 * len(columns)).reshape(2, -1) / 16, columns=columns)
    frame.insert(0, "Electrode", ["Oz", "POz"])
    legacy = tmp_path / "legacy.xlsx"
    with pd.ExcelWriter(legacy) as writer:
        frame.to_excel(writer, sheet_name=core.SHEET_FULLFFT, index=False)
        frame.to_excel(writer, sheet_name=core.SHEET_FULLSNR, index=False)
    companion_workbook = tmp_path / "companion.xlsx"
    receipt = write_results_workbook(str(companion_workbook), {
        core.SHEET_FULLFFT: frame, core.SHEET_FULLSNR: frame,
    })
    settings = DetectabilitySettings(oddball_harmonics_hz=[1.2])
    legacy_fft, legacy_snr, legacy_plan = core._excel_minimal_read(legacy, settings)
    fft, snr, plan = core._excel_minimal_read(companion_workbook, settings)
    pd.testing.assert_frame_equal(fft, legacy_fft)
    pd.testing.assert_frame_equal(snr, legacy_snr)
    assert plan == legacy_plan
    before = core._source_fingerprint(companion_workbook)
    assert before
    companion_workbook.with_name(receipt["spectral_companion"]["path"]).unlink()
    with pytest.raises(SpectralDataError):
        core._source_fingerprint(companion_workbook)


def test_worker_gates_managed_inputs_before_harmonic_mode_selection() -> None:
    source_path = (
        Path(__file__).parents[2]
        / "src"
        / "Tools"
        / "Individual_Detectability"
        / "worker.py"
    )
    source = source_path.read_text(encoding="utf-8")
    run_body = source[source.index("    def _run(self)") : source.index("    @staticmethod")]

    assert run_body.index("_require_current_project_inputs(req)") < run_body.index(
        "_resolve_effective_settings"
    )
    assert run_body.index("prevalidate_managed_conditions") < run_body.index(
        "req.output_root.mkdir"
    )
    assert run_body.index("prevalidate_managed_conditions") < run_body.index(
        "self._write_run_metadata"
    )
    assert run_body.index("prevalidate_managed_conditions") < run_body.index(
        "generate_condition_figure"
    )


def test_managed_noise_support_is_checked_before_cache_reuse() -> None:
    source_path = (
        Path(__file__).parents[2]
        / "src"
        / "Tools"
        / "Individual_Detectability"
        / "core.py"
    )
    source = source_path.read_text(encoding="utf-8")
    participant_body = source[
        source.index("def _process_one_participant(") : source.index(
            "def generate_condition_figure("
        )
    ]

    assert participant_body.index(
        "_require_managed_fullfft_noise_support"
    ) < participant_body.index("if cache_path.exists()")
