"""Small non-Qt checks of the explicitly exploratory project-local adapter."""

from dataclasses import asdict
import json
import logging
from pathlib import Path

import pytest

from scripts.manual_diagnostics.fhc_exploratory_raw_bca import (
    METHOD_ID,
    SOURCE_SHEET,
    assemble_arm,
    contained,
    csv_read,
    digest,
    load_primary,
    ordered_amplitude_matrix,
    prepare,
    primary_snr,
    read_native_bca,
    run,
    validate_run_id,
    verify_input_snapshots,
)


def _write_native_source(anchor, values, *, transform=None, input_count=1):
    """Write genuine companion transport with native eligibility and QC14 ties."""
    import numpy as np
    import pandas as pd
    from config import DEFAULT_ELECTRODE_NAMES_64
    from Main_App.io import write_condition_companion
    from Main_App.io.result_manifest import write_result_manifest
    from Main_App.projects import FrequencyProtocol
    from Main_App.processing.spectral_eligibility import resolve_spectral_eligibility

    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=120,
        expected_analyzed_oddball_cycles_source="manual",
    )
    eligibility = resolve_spectral_eligibility(
        protocol=protocol,
        sampling_rate_hz=100,
        analyzed_samples=10000,
        requested_high_pass_hz=0.1,
        requested_low_pass_hz=5,
        applied_high_pass_hz=0.1,
        applied_low_pass_hz=5,
    )
    sensors = list(DEFAULT_ELECTRODE_NAMES_64)
    bca_data = {"Electrode": sensors}
    qc_rows = []
    for target in eligibility.targets:
        order = target.target.oddball_harmonic_order
        hz = float(target.target.frequency_hz)
        bca_data[f"{hz:.4f}_Hz"] = (
            values[:, order - 1]
            if order <= values.shape[1]
            else np.zeros(64)
            if target.bca_available
            else np.full(64, np.nan)
        )
        for input_id in range(1, input_count + 1):
            for sensor in sensors:
                # Equal unit noise: native stable trimming drops the first and last distinct occurrences.
                candidates = target.noise_candidate_bin_indices
                qc_rows.append(
                    {
                        "Electrode": sensor,
                        "FFT Input Index": input_id,
                        "Oddball Harmonic Order": order,
                        "Target Frequency Exact (Hz)": str(target.target.frequency_hz),
                        "Target FFT Bin": target.target_bin_index,
                        "Eligibility Fingerprint": eligibility.fingerprint,
                        "BCA Status": "available" if target.bca_available else "unavailable",
                        "SNR Status": "available" if target.bca_available else "unavailable",
                        "Local Z Status": "unavailable",
                        "Noise Population SD (uV)": 0.0,
                        "Reason Codes": "effectively_zero_noise_population_sd",
                        "Noise Candidate FFT Bins": ",".join(map(str, candidates)),
                        "Noise Retained FFT Bins": ",".join(map(str, candidates[1:-1])) if target.bca_available else "",
                        "Noise Mean (uV)": 1.0 if target.bca_available else None,
                    }
                )
    frames = {
        "BCA (uV)": pd.DataFrame(bca_data),
        "Spectral Eligibility": pd.DataFrame(eligibility.to_rows()),
        "Spectral Metric QC": pd.DataFrame(qc_rows),
    }
    if transform is not None:
        transform(frames)
    # Case changes and scrambled source order exercise canonical alignment on real decoded arrays.
    frames["BCA (uV)"]["Electrode"] = frames["BCA (uV)"]["Electrode"].str.swapcase()
    frames["BCA (uV)"] = frames["BCA (uV)"].sample(frac=1, random_state=981).reset_index(drop=True)
    descriptor = write_condition_companion(anchor, frames)
    write_result_manifest(anchor, sheet_names=list(frames), spectral_companion=None, condition_companion=descriptor)
    return anchor, protocol, frames, descriptor


def _mutate_valid_npz_preserving_size_and_mtime(path):
    from io import BytesIO
    import os
    import numpy as np

    old_bytes = path.read_bytes()
    stat = path.stat()
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}
    values = next(value for value in arrays.values() if value.dtype == np.dtype("float64") and value.ndim == 2)
    values.flat[0] = np.nextafter(values.flat[0], np.inf)
    stream = BytesIO()
    np.savez(stream, **arrays)
    changed = stream.getvalue()
    assert len(changed) == len(old_bytes) and changed != old_bytes
    path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    return old_bytes


def test_stored_native_bca_bits_and_tied_noise_availability(tmp_path):
    import numpy as np
    from config import DEFAULT_ELECTRODE_NAMES_64
    from Tools.Stats.analysis.noise_utils import compute_qc14_standard_metrics

    values = np.linspace(-0.9, 0.9, 128).reshape(64, 2)
    values[0] = [-0.0, 0.0]
    anchor, protocol, frames, descriptor = _write_native_source(tmp_path / "source.fpvs", values)
    before = {path: digest(path) for path in (anchor, anchor.parent / descriptor["path"])}
    actual, audit = read_native_bca(
        anchor, list(DEFAULT_ELECTRODE_NAMES_64), [1, 2], [1.2, 2.4], protocol, {"frequency_resolution_hz": 0.01}
    )
    np.testing.assert_array_equal(actual.view(np.uint64), values.view(np.uint64))
    assert audit["native_bca_validated_cell_count"] == 128
    assert (actual < 0).any() and np.signbit(actual[0, 0])
    assert all(digest(path) == checksum for path, checksum in before.items())
    assert set(frames["Spectral Metric QC"]["Local Z Status"]) == {"unavailable"}
    spectrum = np.ones(300)
    spectrum[120] = 0.5
    result = compute_qc14_standard_metrics(
        spectrum, target_idx=120, candidate_bin_indices=[120 + offset for offset in [*range(-10, -1), *range(2, 11)]]
    )
    assert result.bca == -0.5 and result.bca_status == "available" and result.local_z_status == "unavailable"
    assert len(result.retained_bin_indices) == 16


def test_native_per_input_trim_then_average_is_preserved(tmp_path):
    import numpy as np
    from config import DEFAULT_ELECTRODE_NAMES_64
    from Tools.Stats.analysis.noise_utils import compute_qc14_standard_metrics

    candidates = [120 + offset for offset in [*range(-10, -1), *range(2, 11)]]
    first, second = np.ones(300), np.ones(300)
    first[120] = second[120] = 10.0
    first[candidates[0]], second[candidates[-1]] = 100.0, 100.0
    metric_a = compute_qc14_standard_metrics(first, target_idx=120, candidate_bin_indices=candidates)
    metric_b = compute_qc14_standard_metrics(second, target_idx=120, candidate_bin_indices=candidates)
    original_average = (metric_a.bca + metric_b.bca) / 2
    recomputed = compute_qc14_standard_metrics(
        (first + second) / 2, target_idx=120, candidate_bin_indices=candidates
    ).bca
    assert original_average == 9.0 and recomputed != original_average
    values = np.full((64, 1), original_average)

    def correct_native_audit(frames):
        qc = frames["Spectral Metric QC"]
        for input_id, native in ((1, metric_a), (2, metric_b)):
            mask = (qc["FFT Input Index"] == input_id) & (qc["Oddball Harmonic Order"] == 1)
            qc.loc[mask, "Noise Mean (uV)"] = native.noise_mean
            qc.loc[mask, "Noise Retained FFT Bins"] = ",".join(map(str, native.retained_bin_indices))

    anchor, protocol, _frames, _descriptor = _write_native_source(
        tmp_path / "average.fpvs", values, input_count=2, transform=correct_native_audit
    )
    actual, audit = read_native_bca(
        anchor, list(DEFAULT_ELECTRODE_NAMES_64), [1], [1.2], protocol, {"frequency_resolution_hz": 0.01}
    )
    np.testing.assert_array_equal(actual.view(np.uint64), values.view(np.uint64))
    assert audit["native_bca_fft_input_count"] == 2


def test_honest_native_unavailability_blocks_even_finite_stored_value(tmp_path):
    import numpy as np
    from config import DEFAULT_ELECTRODE_NAMES_64

    def finite_unavailable_sentinel(frames):
        frames["BCA (uV)"]["7.2000_Hz"] = -0.5

    anchor, protocol, _frames, _descriptor = _write_native_source(
        tmp_path / "unavailable.fpvs",
        np.full((64, 2), -0.5),
        transform=finite_unavailable_sentinel,
    )
    with pytest.raises(ValueError, match="unavailable at primary H6"):
        read_native_bca(
            anchor, list(DEFAULT_ELECTRODE_NAMES_64), [1, 6], [1.2, 7.2], protocol, {"frequency_resolution_hz": 0.01}
        )


def test_valid_same_size_condition_archive_change_blocks_publication(tmp_path):
    import numpy as np

    anchor, _protocol, _frames, descriptor = _write_native_source(tmp_path / "changed.fpvs", np.full((64, 2), -0.5))
    companion = anchor.parent / descriptor["path"]
    audit = {
        "project_relative_path": anchor.name,
        "source_sha256": digest(anchor),
        "condition_companion_path": companion.name,
        "condition_companion_sha256": digest(companion),
    }
    _mutate_valid_npz_preserving_size_and_mtime(companion)
    with pytest.raises(ValueError, match="Condition companion changed"):
        verify_input_snapshots(tmp_path, tmp_path, {}, [audit])


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "nonfinite",
        "unavailable",
        "missing_qc",
        "duplicate_sensor",
        "duplicate_qc",
        "bad_noise_support",
        "bad_eligibility",
    ],
)
def test_native_bca_required_cells_fail_without_domain_shrinking(tmp_path, defect):
    import numpy as np
    from config import DEFAULT_ELECTRODE_NAMES_64

    def damage(frames):
        if defect == "missing":
            frames["BCA (uV)"].drop(columns=["2.4000_Hz"], inplace=True)
        elif defect == "nonfinite":
            frames["BCA (uV)"].loc[0, "2.4000_Hz"] = np.nan
        elif defect == "duplicate_sensor":
            frames["BCA (uV)"].loc[1, "Electrode"] = frames["BCA (uV)"].loc[0, "Electrode"]
        elif defect == "bad_eligibility":
            frames["Spectral Eligibility"].loc[0, "BCA Available"] = False
        else:
            qc = frames["Spectral Metric QC"]
            mask = (qc["Oddball Harmonic Order"] == 1) & (qc["Electrode"] == DEFAULT_ELECTRODE_NAMES_64[0])
            if defect == "unavailable":
                qc.loc[mask, "BCA Status"] = "unavailable"
            elif defect == "missing_qc":
                frames["Spectral Metric QC"] = qc.loc[~mask].reset_index(drop=True)
            elif defect == "duplicate_qc":
                import pandas as pd

                frames["Spectral Metric QC"] = pd.concat([qc, qc.loc[mask]], ignore_index=True)
            elif defect == "bad_noise_support":
                qc.loc[mask, "Noise Retained FFT Bins"] = "1,2"

    anchor, protocol, _frames, _descriptor = _write_native_source(
        tmp_path / f"{defect}.fpvs", np.full((64, 2), -0.5), transform=damage
    )
    with pytest.raises(ValueError):
        read_native_bca(
            anchor, list(DEFAULT_ELECTRODE_NAMES_64), [1, 2], [1.2, 2.4], protocol, {"frequency_resolution_hz": 0.01}
        )


def test_synthetic_metric_recipes_and_exports(tmp_path) -> None:
    from tempfile import TemporaryDirectory
    import numpy as np
    import pandas as pd
    from config import DEFAULT_ELECTRODE_NAMES_64
    from Tools.Free_Harmonic_Clustering.analysis import biosemi64_adjacency_manifest, run_cluster_permutation
    from Tools.Free_Harmonic_Clustering.models import FreeHarmonicMethodSpec
    from Tools.Free_Harmonic_Clustering.preparation import l2_normalize_snr

    plan = {
        "selected_frequency_columns": ["left", "target", "right", "second"],
        "target_selected_indices": [1, 3],
        "noise_selected_indices": [[0, 2], [0, 2]],
        "candidate_orders": [1, 2],
    }
    matrix = np.tile([2.0, 8.0, 4.0, 9.0], (64, 1))
    canonical_sensors = list(DEFAULT_ELECTRODE_NAMES_64)
    assert any(sensor != sensor.upper() for sensor in canonical_sensors)
    ordered_values = np.arange(128, dtype=np.float64).reshape(64, 2)
    frame = pd.DataFrame(ordered_values, columns=["first", "second"])
    frame.insert(0, "Electrode", [sensor.swapcase() for sensor in canonical_sensors])
    shuffled = frame.sample(frac=1, random_state=123).reset_index(drop=True)
    np.testing.assert_array_equal(
        ordered_amplitude_matrix(shuffled, canonical_sensors, ["first", "second"], "synthetic"), ordered_values
    )
    duplicate = shuffled.copy()
    duplicate.loc[1, "Electrode"] = duplicate.loc[0, "Electrode"].swapcase()
    try:
        ordered_amplitude_matrix(duplicate, canonical_sensors, ["first", "second"], "duplicate")
    except ValueError:
        pass
    else:
        raise AssertionError("Case-colliding duplicate source sensors must fail.")
    try:
        ordered_amplitude_matrix(
            shuffled,
            [canonical_sensors[0], canonical_sensors[0].swapcase(), *canonical_sensors[2:]],
            ["first", "second"],
            "duplicate-primary",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Case-colliding primary sensor identities must fail.")
    bca = np.tile([-0.5, 6.0], (64, 1))
    snr = primary_snr(matrix, plan, [1, 2])
    np.testing.assert_allclose(snr, np.tile([8.0 / 3.0, 3.0], (64, 1)))
    rows = [
        {"arm": "a", "participant_id": "p", "session_id": "first", "project_relative_path": "first"},
        {"arm": "a", "participant_id": "p", "session_id": "second", "project_relative_path": "second"},
    ]
    cache = {"first": (bca, snr), "second": (bca * 2, snr * 3)}
    averaged, check = assemble_arm({"kind": "between_groups"}, ["p"], "a", rows, cache, ["first", "second"])
    np.testing.assert_allclose(averaged, bca[None] * 1.5)
    np.testing.assert_allclose(check, l2_normalize_snr(snr[None] * 2))
    change, check = assemble_arm({"kind": "group_visit_change"}, ["p"], "a", rows, cache, ["first", "second"])
    np.testing.assert_allclose(change, -bca[None])
    np.testing.assert_allclose(check, 0.0, atol=1e-15)
    rng = np.random.default_rng(907)
    arm_a, arm_b = rng.normal(size=(4, 64, 2)), rng.normal(size=(5, 64, 2))
    arm_a[:, :, 0] += 4
    spec = FreeHarmonicMethodSpec(method_version=METHOD_ID, n_permutations=19, seed=99)
    first = run_cluster_permutation(arm_a, arm_b, design="independent_groups", method=spec)
    second = run_cluster_permutation(arm_a * 10, arm_b * 10, design="independent_groups", method=spec)
    assert first.permutation_assignment_hash == second.permutation_assignment_hash
    np.testing.assert_allclose(first.observed_t, second.observed_t)
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS

    with TemporaryDirectory(prefix=".synthetic-raw-bca-", dir=tmp_path) as temporary:
        root = Path(temporary).resolve()
        primary = root / "primary"
        primary.mkdir()
        for name in (
            "analysis_plan.json",
            "cohort_audit.csv",
            "exclusions.csv",
            "harmonic_selection.csv",
            "manifest.json",
        ):
            (primary / name).write_text("{}" if name.endswith(".json") else "status\nsynthetic\n", encoding="utf-8")
        comparison = {
            "comparison_id": "synthetic",
            "family_id": "between_groups",
            "label": "Synthetic A minus B",
            "kind": "between_groups",
            "design": "independent_groups",
            "condition_a": "synthetic",
        }
        identity = {
            "seed": 99,
            "permutation_assignment_hash": first.permutation_assignment_hash,
            "participant_ids_a": [f"A{i}" for i in range(4)],
            "participant_ids_b": [f"B{i}" for i in range(5)],
            "arm_a_label": "Synthetic A",
            "arm_b_label": "Synthetic B",
        }
        manifest = {
            "method": asdict(spec),
            "selected_harmonic_orders": [1, 2],
            "selected_harmonics_hz": [1.2, 2.4],
            "plan_fingerprint": "synthetic",
            "frequency_plan": plan,
            "adjacency": biosemi64_adjacency_manifest(),
            "preparation": {"shared_domain_fingerprint": "synthetic"},
        }
        finished = run(
            root,
            primary,
            manifest,
            [(comparison, identity, BIOSEMI64_CHANNELS, arm_a, arm_b)],
            [],
            [],
            root / "secondary",
            "synthetic",
            False,
        )
        exported = json.loads((finished / "manifest.json").read_text(encoding="utf-8"))
        assert exported["status"] == "complete" and exported["method_id"] == METHOD_ID
        assert exported["results"][0]["family_size"] == 1
        assert exported["methods"]["normalization"] == "none"
        assert exported["methods"]["saved_toolbox_BCA_used"] is True
        assert csv_read(finished / "all_clusters.csv")
        with np.load(finished / "comparisons" / "0001" / "arrays.npz", allow_pickle=False) as arrays:
            np.testing.assert_array_equal(arrays["raw_bca_values_a_uv"], arm_a)
            assert "normalized_values_a" not in arrays
    logging.getLogger(__name__).info(
        "Synthetic checks passed: mixed-case canonical sensors, scrambled row order and collision rejection; primary SNR, unnormalized signed BCA average/change recipes, assignment identity, scalar invariance, all-cluster export, Holm metadata and raw-tensor output labels."
    )


def test_native_plan_schema_and_source_immutability(tmp_path) -> None:
    """Exercise real native export schemas using only temporary synthetic data."""
    from tempfile import TemporaryDirectory
    import numpy as np
    import pytest
    import Main_App.io as io
    import Main_App.processing.full_fft_provenance as provenance
    from Tools.Free_Harmonic_Clustering import inputs
    from Tools.Free_Harmonic_Clustering.analysis_plan import AnalysisFamily, build_analysis_plan
    from Tools.Free_Harmonic_Clustering.models import FreeHarmonicMethodSpec
    from Tools.Free_Harmonic_Clustering.planned_analysis import run_analysis_plan
    from Tools.Free_Harmonic_Clustering.planned_exports import export_analysis_plan_result
    from tests.free_harmonic_clustering.test_inputs import (
        _write_repeated_project,
        _install_frequency_exclusions,
        _install_reader_doubles,
        _header,
    )
    from tests.free_harmonic_clustering.test_exports import _stub_map_figures

    with TemporaryDirectory(prefix=".native-schema-test-", dir=tmp_path) as temporary:
        with pytest.MonkeyPatch.context() as patch:
            root = _write_repeated_project(
                Path(temporary) / "SyntheticProject",
                participants_by_group={"bc_group": ("BC1", "BC2", "BC3"), "control_group": ("C1", "C2", "C3")},
                conditions=("Angry", "Happy"),
                missing_workbooks={("BC3", "follicular_phase", "Happy")},
            )
            _install_frequency_exclusions(patch)
            _stub_map_figures(patch)
            import json as fixture_json
            from config import DEFAULT_ELECTRODE_NAMES_64

            planted_values = {}
            for old_anchor in (root / "1 - Excel Data Files").rglob("*.xlsx"):
                token = sum(old_anchor.name.encode("utf-8"))
                sensors = np.arange(64, dtype=np.float64)[:, None]
                values = -0.5 + sensors * 0.01 + np.arange(3)[None] * 0.08 + (token % 17) * 0.002
                anchor, protocol, _frames, _descriptor = _write_native_source(old_anchor.with_suffix(".fpvs"), values)
                planted_values[anchor.relative_to(root).as_posix()] = values
            project_manifest = fixture_json.loads((root / "project.json").read_text(encoding="utf-8"))
            project_manifest["frequency_protocol"] = protocol.to_manifest()
            (root / "project.json").write_text(fixture_json.dumps(project_manifest), encoding="utf-8")

            def varied_profile(path, frame):
                sensors = np.arange(64, dtype=np.float64)
                participant = path.name.split("__", 1)[0]
                number = int("".join(value for value in participant if value.isdigit()))
                visit = 1.0 if "luteal_phase" in path.name else -0.3
                condition = 0.4 if "Happy" in path.name else -0.2
                group = 0.3 if participant.startswith("BC") else -0.2
                frame["1.200000_Hz"] = 20.0 + sensors * (0.3 + number * 0.02 + (visit + condition + group) * 0.04)
                frame["2.400000_Hz"] = 15.0 + np.sin(sensors / (number + 2)) + sensors[::-1] * (0.15 + visit * 0.03)

            _install_reader_doubles(
                patch, header_for_path=lambda _path: _header(spacing_hz=0.01), mutate_frame=varied_profile
            )
            plan = build_analysis_plan(
                root,
                group_ids=("bc_group", "control_group"),
                conditions=("Angry", "Happy"),
                session_ids=("luteal_phase", "follicular_phase"),
                families=tuple(AnalysisFamily),
            )
            before = (root / "project.json").read_bytes()
            result = run_analysis_plan(plan, FreeHarmonicMethodSpec(max_harmonic_hz=3.6, n_permutations=7, seed=83))
            receipt = export_analysis_plan_result(result, run_id="native-schema-fixture")
            patch.setattr(
                provenance, "validate_project_full_fft_provenance", inputs.validate_project_full_fft_provenance
            )

            def direct_reader(path, *, sheet_name, required_columns, require_all=True):
                assert sheet_name == SOURCE_SHEET
                frame = inputs._read_fullfft_selected_columns(path, tuple(required_columns), {})
                frame["Electrode"] = frame["Electrode"].str.swapcase()
                return frame.sample(frac=1, random_state=813).reset_index(drop=True)

            patch.setattr(io, "read_spectral_sheet_selected_columns", direct_reader)
            patch.setattr(io, "spectral_companion_identity", lambda _path: None)
            primary_dir, manifest = load_primary(root, receipt.output_directory, 0)
            prepared, audits, source_rows = prepare(root, primary_dir, manifest)
            # The missing second Happy visit removes both BC3 Happy recordings
            # from the complete-pair inputs; its Angry pair remains eligible.
            assert len(prepared) == 10 and len(audits) == 22
            assert all(row["condition_companion_sha256"] for row in audits)
            assert all(row["native_bca_validated_cell_count"] == 64 * 3 for row in audits)
            for actual, expected in zip(prepared, result.outcomes, strict=True):
                assert actual[0]["comparison_id"] == expected.comparison.comparison_id
                assert tuple(actual[2]) == expected.contrast.sensor_names
                assert actual[3].shape == expected.contrast.values_a.shape
                assert actual[4].shape == expected.contrast.values_b.shape
                comparison, identity, _sensors, arm_a, arm_b = actual
                frozen_sources = [row for row in source_rows if row["comparison_id"] == comparison["comparison_id"]]
                planted_cache = {key: (value, np.ones_like(value)) for key, value in planted_values.items()}
                for letter, values in (("a", arm_a), ("b", arm_b)):
                    raw, _ignored = assemble_arm(
                        comparison,
                        identity[f"participant_ids_{letter}"],
                        letter,
                        frozen_sources,
                        planted_cache,
                        manifest["plan"]["session_ids"],
                    )
                    np.testing.assert_array_equal(values.view(np.uint64), raw.view(np.uint64))
                assert tuple(_sensors) == tuple(DEFAULT_ELECTRODE_NAMES_64)
            secondary = run(
                root,
                primary_dir,
                manifest,
                prepared,
                audits,
                source_rows,
                root / "Secondary Raw BCA",
                "native-schema-prepare-only",
                True,
            )
            saved = json.loads((secondary / "manifest.json").read_text(encoding="utf-8"))
            assert saved["status"] == "prepared" and len(saved["results"]) == 10
            for number, actual in enumerate(prepared, 1):
                with np.load(secondary / "comparisons" / f"{number:04d}" / "arrays.npz", allow_pickle=False) as arrays:
                    np.testing.assert_array_equal(
                        arrays["raw_bca_values_a_uv"].view(np.uint64), actual[3].view(np.uint64)
                    )
            complete = run(
                root,
                primary_dir,
                manifest,
                prepared,
                audits,
                source_rows,
                root / "Secondary Raw BCA",
                "native-schema-complete",
                False,
            )
            completed = json.loads((complete / "manifest.json").read_text(encoding="utf-8"))
            assert completed["status"] == "complete" and len(completed["results"]) == 10
            sizes = {"between_groups": 2, "within_group_visits": 4, "group_visit_change": 2, "between_conditions": 2}
            for row, original in zip(completed["results"], manifest["comparisons"], strict=True):
                assert row["family_size"] == sizes[row["family_id"]]
                assert row["permutation_assignment_hash"] == original["permutation_assignment_hash"]
                assert row["metric"] == METHOD_ID and row["units"] == "uV"
            assert (root / "project.json").read_bytes() == before
            # The adapter must reject a transposed participant order even after
            # the original primary bundle was parsed and validated.
            arrays_path = primary_dir / manifest["comparisons"][0]["directory"] / "arrays.npz"
            original_arrays = arrays_path.read_bytes()
            with np.load(arrays_path, allow_pickle=False) as archive:
                altered = {key: archive[key].copy() for key in archive.files}
            altered["participant_ids_a"] = altered["participant_ids_a"][::-1].copy()
            np.savez_compressed(arrays_path, **altered)
            with pytest.raises(ValueError, match="participant order differs"):
                prepare(root, primary_dir, manifest)
            arrays_path.write_bytes(original_arrays)

            # A valid, same-size NPZ replacement during the BCA read must not
            # slip through unchanged timestamp or native reader caches.
            selected_source = root / audits[0]["project_relative_path"]
            condition_path = selected_source.parent / audits[0]["condition_companion_path"]
            original_condition = condition_path.read_bytes()
            original_reader = io.read_condition_sheet_selected_columns
            replaced = False

            def replace_after_bca_read(path, **kwargs):
                nonlocal replaced
                frame = original_reader(path, **kwargs)
                if Path(path) == selected_source and kwargs["sheet_name"] == "BCA (uV)" and not replaced:
                    _mutate_valid_npz_preserving_size_and_mtime(condition_path)
                    replaced = True
                return frame

            patch.setattr(io, "read_condition_sheet_selected_columns", replace_after_bca_read)
            with pytest.raises(ValueError):
                prepare(root, primary_dir, manifest)
            assert replaced
            condition_path.write_bytes(original_condition)
            logging.getLogger(__name__).info(
                "Native v2 schema integration passed: 10 comparisons, 22 complete-pair synthetic sources, all four families, narrow missing-pair cohorts, mixed-case scrambled sensor rows, checksum/plan validation, SNR reconstruction and prepare-only exports. No real data or GUI execution."
            )


@pytest.mark.parametrize("run_id", ["", ".", "..", "../escape", "C:/bad", "name space"])
def test_reject_invalid_run_ids(run_id):
    with pytest.raises(ValueError):
        validate_run_id(run_id)


def test_paths_and_input_changes_fail(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    manifest = root / "project.json"
    manifest.write_text("{}", encoding="utf-8")
    primary = root / "primary"
    primary.mkdir()
    (primary / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        contained(tmp_path / "escape", root)
    with pytest.raises(ValueError, match="absolute"):
        load_primary(root, Path("primary"), 0)
    with pytest.raises(ValueError, match="completed native"):
        load_primary(root, primary.resolve(), 0)
    frozen = {"_input_project_manifest_sha256": digest(manifest)}
    manifest.write_text('{"changed": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="manifest changed"):
        verify_input_snapshots(root, primary, frozen, [])


def test_companion_change_is_detected_before_publication(tmp_path):
    root = tmp_path
    primary = root / "primary"
    primary.mkdir()
    source = root / "source.xlsx"
    source.write_bytes(b"workbook")
    companion = root / "source.spectral.npz"
    companion.write_bytes(b"original")
    audit = {
        "project_relative_path": source.name,
        "source_sha256": digest(source),
        "spectral_companion_path": companion.name,
        "spectral_companion_sha256": digest(companion),
    }
    verify_input_snapshots(root, primary, {}, [audit])
    companion.write_bytes(b"modified")
    with pytest.raises(ValueError, match="companion changed"):
        verify_input_snapshots(root, primary, {}, [audit])


def test_manifest_snapshot_uses_parsed_bytes_despite_later_replacement(tmp_path, monkeypatch):
    from hashlib import sha256
    import sys

    from scripts.manual_diagnostics import fhc_exploratory_raw_bca as adapter

    root = tmp_path / "project"
    root.mkdir()
    (root / "project.json").write_text("{}", encoding="utf-8")
    repo = tmp_path / "repo"
    source = repo / "src" / "Tools" / "Free_Harmonic_Clustering"
    source.mkdir(parents=True)
    (source / "analysis.py").write_text("", encoding="utf-8")
    primary = root / "primary"
    primary.mkdir()
    plan = {"version": "fhc_analysis_families_v2", "comparisons": [{"comparison_id": "one"}]}
    fingerprint = sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    plan_path = primary / "analysis_plan.json"
    plan_path.write_text(json.dumps({**plan, "plan_fingerprint": fingerprint}), encoding="utf-8")
    manifest = {
        "status": "complete",
        "plan": plan,
        "plan_fingerprint": fingerprint,
        "comparisons": plan["comparisons"],
        "artifacts": [
            {"path": "primary/analysis_plan.json", "size_bytes": plan_path.stat().st_size, "sha256": digest(plan_path)}
        ],
    }
    manifest_path = primary / "manifest.json"
    original_bytes = json.dumps(manifest).encode("utf-8")
    manifest_path.write_bytes(original_bytes)
    parsed_digest = sha256(original_bytes).hexdigest()
    original_digest = adapter.digest

    def replace_after_parse(path):
        result = original_digest(path)
        if path == plan_path:
            manifest_path.write_text(json.dumps({**manifest, "replaced_after_parse": True}), encoding="utf-8")
        return result

    monkeypatch.setattr(adapter, "digest", replace_after_parse)
    monkeypatch.setattr(adapter, "prepare", lambda *_args: ([], [], []))

    def guarded_publication(project_root, primary_dir, frozen, *_args):
        assert frozen["_input_primary_manifest_sha256"] == parsed_digest
        assert original_digest(manifest_path) != parsed_digest
        adapter.verify_input_snapshots(project_root, primary_dir, frozen, [])
        pytest.fail("A replaced manifest must prevent publication.")

    monkeypatch.setattr(adapter, "run", guarded_publication)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adapter",
            "--repo-root",
            str(repo),
            "--project-root",
            str(root),
            "--primary-run",
            str(primary),
            "--run-id",
            "race-negative-control",
        ],
    )
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(ValueError, match="Primary manifest changed"):
        adapter.main()
    assert not (root / "Secondary Raw BCA").exists()


def test_nonfinite_and_nonpositive_noise_block():
    import numpy as np

    plan = {
        "selected_frequency_columns": ["noise", "target"],
        "target_selected_indices": [1],
        "noise_selected_indices": [[0]],
        "candidate_orders": [1],
    }
    for values in (np.array([[np.nan, 1.0]]), np.array([[0.0, 1.0]]), np.array([[-1.0, 1.0]])):
        with pytest.raises(ValueError):
            primary_snr(values, plan, [1])
