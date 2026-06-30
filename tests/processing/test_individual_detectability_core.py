from __future__ import annotations

from pathlib import Path

from Tools.Individual_Detectability.core import (
    ConditionInfo,
    DetectabilitySettings,
    ELECTRODE_COL,
    build_fullfft_harmonic_plan,
    discover_conditions,
    electrode_summed_z_from_fullfft_frame,
    _plot_topomap_compat,
    parse_participant_id,
    roi_summed_z_from_fullfft_frame,
    sanitize_filename_stem,
    summed_harmonic_z_from_bin_amplitudes,
)
from Tools.Individual_Detectability.worker import (
    IndividualDetectabilityWorker,
    RunRequest,
)
from Tools.Stats.analysis.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CUSTOM_HARMONIC_SOURCE,
    SharedHarmonicSelection,
)


def test_parse_participant_id_scp_variants() -> None:
    assert parse_participant_id("SCP7_condition_Results.xlsx") == "P7"
    assert parse_participant_id("SCP07_condition_Results.xlsx") == "P7"


def test_parse_participant_id_p_variants() -> None:
    assert parse_participant_id("P1_Angry Neutral_Results.xlsx") == "P1"
    assert parse_participant_id("P11_Angry Neutral_Results.xlsx") == "P11"


def test_parse_participant_id_detects_with_underscores() -> None:
    assert parse_participant_id("P1_Angry_Neutral_Results") == "P1"
    assert parse_participant_id("p001_Happy_Neutral_Results") == "P1"


def test_discover_conditions_with_subfolders(tmp_path: Path) -> None:
    cond_a = tmp_path / "CondA"
    cond_b = tmp_path / "CondB"
    cond_a.mkdir()
    cond_b.mkdir()
    (cond_a / "a.xlsx").write_text("data")
    (cond_a / "._sidecar.xlsx").write_text("AppleDouble metadata")
    (cond_b / "b.xlsx").write_text("data")

    conditions = discover_conditions(tmp_path)
    names = [c.name for c in conditions]
    assert names == ["CondA", "CondB"]
    assert all(c.files for c in conditions)
    assert [file.name for file in conditions[0].files] == ["a.xlsx"]


def test_discover_conditions_single_root(tmp_path: Path) -> None:
    (tmp_path / "root.xlsx").write_text("data")
    conditions = discover_conditions(tmp_path)
    assert len(conditions) == 1
    assert conditions[0].path == tmp_path


def test_missingness_across_conditions_keeps_union_of_participants(tmp_path: Path) -> None:
    excel_root = tmp_path / "1 - Excel Data Files"
    cond_a = excel_root / "AngryNeutral"
    cond_b = excel_root / "HappyNeutral"
    cond_a.mkdir(parents=True)
    cond_b.mkdir(parents=True)
    (cond_a / "P1_Angry Neutral_Results.xlsx").write_text("data")
    (cond_a / "P11_Angry Neutral_Results.xlsx").write_text("data")
    (cond_b / "P11_Happy Neutral_Results.xlsx").write_text("data")

    conditions = discover_conditions(excel_root)
    participants = {
        pid
        for condition in conditions
        for file in condition.files
        for pid in [parse_participant_id(file.stem)]
        if pid is not None
    }

    assert participants == {"P1", "P11"}


def test_topomap_wrapper_saves_pdf(tmp_path: Path) -> None:
    import pytest

    np = pytest.importorskip("numpy")
    mne = pytest.importorskip("mne")
    matplotlib = pytest.importorskip("matplotlib")

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    montage = mne.channels.make_standard_montage("biosemi64")
    electrodes = montage.ch_names
    info = mne.create_info(electrodes, sfreq=1.0, ch_types="eeg")
    info.set_montage(montage)
    z_threshold = 1.64
    z_values = np.full(len(electrodes), z_threshold)
    z_values[0] = z_threshold + 0.9
    z_values[10] = z_threshold + 0.4

    fig, ax = plt.subplots(figsize=(2.4, 2.2))
    _plot_topomap_compat(
        z_values,
        info,
        ax,
        "RdBu_r",
        z_threshold,
        float(z_values.max()),
    )
    output = tmp_path / "compat_topomap.pdf"
    fig.savefig(output, format="pdf", dpi=600)
    plt.close(fig)

    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")
    assert output.stat().st_size > 100


def test_worker_forces_png_export_with_pdf(tmp_path: Path, monkeypatch) -> None:
    condition = ConditionInfo(
        name="CondA",
        path=tmp_path / "CondA",
        files=[tmp_path / "CondA" / "P1_CondA_Results.xlsx"],
    )
    request = RunRequest(
        input_root=tmp_path,
        output_root=tmp_path / "out",
        project_root=None,
        conditions=[condition],
        output_stems={"CondA": "cond_a_grid"},
        excluded_participants=set(),
        settings=DetectabilitySettings(
            harmonic_source=CUSTOM_HARMONIC_SOURCE,
            oddball_harmonics_hz=[1.2, 2.4],
        ),
    )
    seen: dict[str, object] = {}

    def fake_generate_condition_figure(**kwargs):
        seen["export_png"] = kwargs["export_png"]
        output_dir = kwargs["output_dir"]
        stem = sanitize_filename_stem(kwargs["output_stem"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{stem}.pdf").write_bytes(b"%PDF-test")
        (output_dir / f"{stem}.png").write_bytes(b"png-test")
        return (1, 1)

    monkeypatch.setattr(
        "Tools.Individual_Detectability.worker.generate_condition_figure",
        fake_generate_condition_figure,
    )

    worker = IndividualDetectabilityWorker(request)
    worker._run()

    assert seen["export_png"] is True
    assert (tmp_path / "out" / "CondA" / "cond_a_grid_custom_harmonics.pdf").exists()
    assert (tmp_path / "out" / "CondA" / "cond_a_grid_custom_harmonics.png").exists()
    assert (tmp_path / "out" / "individual_detectability_custom_harmonics_metadata.json").exists()


def test_worker_resolves_canonical_harmonics_before_generating_figures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from Tools.Individual_Detectability import worker as worker_mod

    cond_dir = tmp_path / "CondA"
    cond_dir.mkdir()
    file_p1 = cond_dir / "P1_CondA_Results.xlsx"
    file_p2 = cond_dir / "P2_CondA_Results.xlsx"
    file_p1.write_text("placeholder")
    file_p2.write_text("placeholder")
    condition = ConditionInfo(name="CondA", path=cond_dir, files=[file_p2, file_p1])
    request = RunRequest(
        input_root=tmp_path,
        output_root=tmp_path / "out",
        project_root=tmp_path,
        conditions=[condition],
        output_stems={"CondA": "cond_a_grid"},
        excluded_participants={"P2"},
        settings=DetectabilitySettings(),
    )
    captured: dict[str, object] = {}

    def fake_select_canonical_group_harmonics(**kwargs):
        captured.update(kwargs)
        return SharedHarmonicSelection(
            source=CANONICAL_HARMONIC_SOURCE,
            selected_harmonics_hz=(1.2, 2.4),
            metadata={},
            fingerprint={},
            fingerprint_text="FPVS Toolbox significant harmonics | selected: 1.2, 2.4 Hz",
            output_label="fpvs_toolbox_significant_harmonics",
        )

    def fake_generate_condition_figure(**kwargs):
        settings = kwargs["settings"]
        seen_settings["source"] = settings.harmonic_source
        seen_settings["harmonics"] = list(settings.oddball_harmonics_hz)
        output_dir = kwargs["output_dir"]
        stem = sanitize_filename_stem(kwargs["output_stem"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{stem}.pdf").write_bytes(b"%PDF-test")
        (output_dir / f"{stem}.png").write_bytes(b"png-test")
        return (1, 1)

    seen_settings: dict[str, object] = {}
    monkeypatch.setattr(
        worker_mod,
        "select_canonical_group_harmonics",
        fake_select_canonical_group_harmonics,
    )
    monkeypatch.setattr(worker_mod, "analysis_base_frequency_hz", lambda: 6.0)
    monkeypatch.setattr(worker_mod, "analysis_bca_upper_limit_hz", lambda: 16.8)
    monkeypatch.setattr(worker_mod, "load_rois_from_settings", lambda: {"LOT": ["P7"]})
    monkeypatch.setattr(
        "Tools.Individual_Detectability.worker.generate_condition_figure",
        fake_generate_condition_figure,
    )

    worker = IndividualDetectabilityWorker(request)
    worker._run()

    assert captured["subjects"] == ["P1"]
    assert captured["conditions"] == ["CondA"]
    assert captured["subject_data"] == {"P1": {"CondA": str(file_p1)}}
    assert captured["rois"] == {"LOT": ["P7"]}
    assert seen_settings["source"] == CANONICAL_HARMONIC_SOURCE
    assert seen_settings["harmonics"] == [1.2, 2.4]
    metadata = tmp_path / "out" / "individual_detectability_metadata.json"
    assert metadata.exists()
    assert "FPVS Toolbox significant harmonics" in metadata.read_text(encoding="utf-8")


def _amplitude_by_bin(harmonic_bins: tuple[int, ...], target_value: float) -> dict[int, float]:
    values: dict[int, float] = {}
    for bin_index in harmonic_bins:
        values[bin_index] = target_value
        for offset in [*range(-10, -1), *range(2, 11)]:
            values[bin_index + offset] = 1.0 + (abs(offset) * 0.02)
    return values


def test_summed_harmonic_z_increases_with_target_amplitude() -> None:
    bins = (20, 40)
    low = summed_harmonic_z_from_bin_amplitudes(_amplitude_by_bin(bins, 1.2), bins)
    high = summed_harmonic_z_from_bin_amplitudes(_amplitude_by_bin(bins, 2.2), bins)

    assert high.z_sum > low.z_sum
    assert high.p_one_tailed < low.p_one_tailed


def test_null_summed_harmonic_z_is_centered_near_zero() -> None:
    bins = (20, 40)
    amplitudes = _amplitude_by_bin(bins, 1.0)
    noise_sums = []
    for offset in [*range(-10, -1), *range(2, 11)]:
        noise_sums.append(sum(amplitudes[b + offset] for b in bins))
    trimmed = sorted(noise_sums)[1:-1]
    target_each = sum(trimmed) / len(trimmed) / len(bins)
    for bin_index in bins:
        amplitudes[bin_index] = target_each

    result = summed_harmonic_z_from_bin_amplitudes(amplitudes, bins)

    assert abs(result.z_sum) < 1e-12


def test_summed_harmonic_z_differs_from_legacy_stouffer_on_same_data() -> None:
    bins = (20, 40)
    amplitudes = _amplitude_by_bin(bins, 1.7)
    amplitudes[20] = 2.4
    amplitudes[40] = 1.4

    summed = summed_harmonic_z_from_bin_amplitudes(amplitudes, bins)
    harmonic_z = []
    for bin_index in bins:
        one_bin = summed_harmonic_z_from_bin_amplitudes(amplitudes, (bin_index,))
        harmonic_z.append(one_bin.z_sum)
    legacy_stouffer = sum(harmonic_z) / (len(harmonic_z) ** 0.5)

    assert summed.z_sum != legacy_stouffer


def test_roi_detectability_uses_roi_averaged_spectrum_not_averaged_z() -> None:
    import pandas as pd

    columns = [ELECTRODE_COL, *[f"{idx / 10:.4f}_Hz" for idx in range(51)]]
    plan = build_fullfft_harmonic_plan(columns, [1.2, 2.4])
    base = {f"{idx / 10:.4f}_Hz": 1.0 + (idx % 5) * 0.03 for idx in range(51)}
    e1 = dict(base)
    e2 = dict(base)
    e1[ELECTRODE_COL] = "P7"
    e2[ELECTRODE_COL] = "PO7"
    e1["1.2000_Hz"] = 4.0
    e1["2.4000_Hz"] = 4.0
    e2["1.2000_Hz"] = 0.2
    e2["2.4000_Hz"] = 0.2
    frame = pd.DataFrame([e1, e2])

    roi_result = roi_summed_z_from_fullfft_frame(frame, plan, ["P7", "PO7"])
    electrode_z = electrode_summed_z_from_fullfft_frame(frame, plan)
    averaged_electrode_z = electrode_z["z_sum"].mean()

    assert roi_result["valid_electrode_count"] == 2
    assert roi_result["z_sum"] != averaged_electrode_z


def test_summed_z_plan_preserves_original_bins_after_minimal_fullfft_read() -> None:
    import pandas as pd

    columns = [ELECTRODE_COL, *[f"{idx / 10:.4f}_Hz" for idx in range(51)]]
    plan = build_fullfft_harmonic_plan(columns, [1.2, 2.4])
    full_row = {
        column: 1.0 + (idx % 7) * 0.02
        for idx, column in enumerate(columns)
        if column != ELECTRODE_COL
    }
    full_row[ELECTRODE_COL] = "P7"
    full_row["1.2000_Hz"] = 3.0
    full_row["2.4000_Hz"] = 3.0
    full_frame = pd.DataFrame([full_row], columns=columns)
    minimal_frame = full_frame.loc[:, list(plan.usecols)]

    full_result = electrode_summed_z_from_fullfft_frame(full_frame, plan)
    minimal_result = electrode_summed_z_from_fullfft_frame(minimal_frame, plan)

    assert minimal_result["z_sum"].iloc[0] == full_result["z_sum"].iloc[0]
