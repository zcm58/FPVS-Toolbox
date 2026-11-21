"""Both project releases with a small signed FIF, measured rank and controlled native numerical leaf."""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers import hauk_source_psd, native_cell_runtime, native_psd_cells


@pytest.mark.parametrize(
    ("method", "builder", "harmonic_resolver", "leaf", "fixture_leaf"),
    [
        (
            "l2_mne",
            "build_mne_fsaverage_source_psd_model",
            "_resolve_selected_harmonics",
            "_default_compute_source_psd",
            "_source_psd_callable",
        ),
        (
            "eloreta_volume",
            "build_mne_fsaverage_eloreta_volume_source_psd_model",
            "resolve_project_hauk_source_psd_harmonics",
            "_default_apply_inverse",
            "_apply_inverse_callable",
        ),
    ],
)
def test_real_producer_release_and_negative_aliases(
    tmp_path, monkeypatch, method, builder, harmonic_resolver, leaf, fixture_leaf
):
    worker_calls = []
    producer = importlib.import_module(
        f"Tools.LORETA_Visualizer.source_producers.project_{method}_hauk_source_psd_export"
    )
    fixtures = importlib.import_module(f"test_project_{method}_hauk_source_psd_export")
    writer = getattr(producer, f"write_project_{method}_hauk_source_psd_payloads")
    project = fixtures._project_with_ledger(tmp_path, participants=("P01",))
    fixtures._write_time_domain_derivative(project.project_root, participant_id="P01")
    model = fixtures._source_psd_model()
    monkeypatch.setattr(producer, builder, lambda **kwargs: model)
    monkeypatch.setattr(hauk_source_psd, leaf, lambda: getattr(fixtures, fixture_leaf)(worker_calls))
    roster = ["P01"]
    selection = {"source": "saved_processing_harmonics", "selected_harmonics_hz": [20.0], "selection_subjects": roster}
    monkeypatch.setattr(producer, harmonic_resolver, lambda *args, **kwargs: ((20.0,), dict(selection)))

    def release():
        published = writer(project=project, aggregations=("mean",), cluster_mask_enabled=False)
        docs = json.loads(published.manifest_path.read_bytes())
        advertised = docs["metadata"]["source_psd_method"]["custom_metadata"]["harmonic_selection"]
        assert advertised["selection_subjects"] == roster
        report = json.loads(published.validation_report_path.read_bytes())
        rank = report["input_model_provenance"][0]["source_ready_data_rank"]
        payload = json.loads((published.output_dir / docs["conditions"][0]["file"]).read_bytes())
        return published, rank, np.asarray(payload["values"]).tobytes()

    first, rank, values = release()
    assert first.cache_miss_count == 1 and first.cache_hit_count == 0 and worker_calls
    primary = project.project_root / ".fpvs_processing/source_psd_cache/v2"
    aliases = project.project_root / ".fpvs_processing/source_psd_cache/native_cells_v1"
    (alias,) = aliases.glob("*.json")
    first_alias = alias.read_bytes()
    first_key = json.loads(first_alias)["primary"]

    roster.append("P02")
    worker_calls.clear()
    reused, warm_rank, warm_vals = release()
    assert reused.cache_hit_count == 1 and reused.cache_miss_count == 0 and not worker_calls
    assert warm_rank == rank and warm_vals == values and len(list(primary.glob("*.json"))) == 2

    # The materialized current-cohort v2 entry must work on its own, including
    # when secondary qualification is unavailable for a later ordinary warm run.
    alias.unlink()
    with monkeypatch.context() as same_cohort:
        def unexpected_qualification(*_args, **_kwargs):
            pytest.fail("An ordinary v2 hit attempted to qualify a secondary cache entry")

        same_cohort.setattr(native_psd_cells.MethodContext, "from_settings", unexpected_qualification)
        unchanged, primary_rank, primary_values = release()
        assert unchanged.cache_hit_count == 1 and unchanged.cache_miss_count == 0 and not worker_calls
        assert primary_rank == rank and primary_values == values and not alias.exists()

    # A complete v2 store has no authority for secondary reuse without a genuine worker receipt.
    roster.append("P03")
    missed, got_rank, got_values = release()
    assert worker_calls and missed.cache_hit_count == 0 and got_rank == rank and got_values == values

    # An origin archived under the wrong content/metadata must miss, including rank-only corruption.
    roster.append("P04")
    worker_calls.clear()
    alias.write_bytes(first_alias)
    origin = primary / (first_key + ".json")
    altered = json.loads(origin.read_bytes())
    altered["result_metadata"]["source_ready_data_rank"]["unprojected"]["rank"] += 1
    origin.write_text(json.dumps(altered), encoding="utf-8")
    assert release()[0].cache_miss_count == 1 and worker_calls

    # A new kernel setting or foreign runtime can never use the preceding native receipt.
    roster.append("P05")
    worker_calls.clear()
    selection["unknown_future_input"] = 1
    assert release()[0].cache_miss_count == 1 and worker_calls
    roster.append("P06")
    worker_calls.clear()
    original = native_psd_cells.executing_runtime
    monkeypatch.setattr(native_psd_cells, "executing_runtime", lambda m: original(m) + "-other")
    assert release()[0].cache_miss_count == 1 and worker_calls

    # Some frozen installations expose only synthetic paths for PYZ modules.
    # A missing physical implementation may never disable the actual producer.
    roster.append("P07")
    worker_calls.clear()
    def inaccessible_module():
        raise FileNotFoundError("No filesystem representation for this implementation")

    monkeypatch.setattr(native_psd_cells, "collect_implementation_files", inaccessible_module)
    packed, packaged_rank, packaged_values = release()
    assert packed.cache_hit_count == 0 and packed.cache_miss_count == 1 and worker_calls
    assert packaged_rank == rank and packaged_values == values


def test_model_structure_and_arrays_are_bound():
    info = {"names": ["Cz", "Oz"]}
    inverse = {"weights": np.arange(9, dtype=np.float64).reshape(3, 3)}
    identity = native_cell_runtime.model_digest(info, inverse)
    assert identity != native_cell_runtime.model_digest({"names": ["Oz", "Cz"]}, inverse)
    alternate = inverse["weights"].copy()
    alternate[0, 0] = np.nextafter(0.0, 1.0)
    assert identity != native_cell_runtime.model_digest(info, {"weights": alternate})


def test_sidecar_requires_current_science_and_keeps_unknown_fields():
    document = {
        "format": "fpvs-source-ready-time-domain-v1",
        "complete": True,
        "fif_sha256": "a" * 64,
        "processing": {
            "fingerprint": "old",
            "fingerprint_version": "processing_fingerprint_v13_v3_trigger_alignment",
            "provenance": {"processing_fingerprint": "old", "unknown_calibration": 0.25},
        },
        "source_signature": {"raw_file": "old/P1.bdf", "raw_mtime_ns": 2, "raw_size": 450},
    }

    def digest(doc):
        return native_psd_cells.source_sidecar_digest(
            SimpleNamespace(sidecar=doc, fif_sha256="a" * 64, processing_fingerprint=doc["processing"]["fingerprint"])
        )

    changed = deepcopy(document)
    changed["processing"]["fingerprint"] = changed["processing"]["provenance"]["processing_fingerprint"] = "new"
    changed["source_signature"].update(raw_file="new/P1.bdf", raw_mtime_ns=12)
    assert digest(document) == digest(changed)
    for nested, key, edit in (
        ("source_signature", "raw_size", 451),
        ("processing", "fingerprint_version", "future"),
        ("processing", "future_science", "unknown"),
    ):
        guarded = deepcopy(changed)
        guarded[nested][key] = edit
        assert digest(guarded) != digest(document)
    altered = deepcopy(changed)
    altered["processing"]["provenance"]["unknown_calibration"] = 0.5
    assert digest(altered) != digest(document)


def test_numerical_thread_count_is_checked_in_executing_process():
    from threadpoolctl import threadpool_limits

    manifest = native_cell_runtime.collect_implementation_files()
    with threadpool_limits(limits=1):
        one = native_cell_runtime.executing_runtime(manifest)
    with threadpool_limits(limits=2):
        two = native_cell_runtime.executing_runtime(manifest)
    assert one != two
    signature = next(iter(manifest))
    path, identity, sha = manifest[signature]
    manifest[signature] = (path, (-1, *identity[1:]), sha)
    with pytest.raises(ValueError, match="Executing implementation"):
        native_cell_runtime.executing_runtime(manifest)


def test_first_native_model_mutation_revokes_secondary_certification(monkeypatch, tmp_path):
    current = {"weight": np.array([1.0])}
    info = {"channels": ["Cz"]}
    context = SimpleNamespace(configuration="exact", frequencies={}, manifest={}, root=tmp_path)
    monkeypatch.setattr(native_psd_cells, "projected_method", lambda *a: "m")
    real_digest = native_psd_cells.canonical_digest
    context.configuration = real_digest("m")
    cfg = SimpleNamespace(to_metadata=lambda: {})
    state = native_psd_cells.WorkerContext(context, info, current, cfg)
    monkeypatch.setattr(state, "proof", lambda rec, rt: "certifiable" if state.model else "")
    monkeypatch.setattr(native_psd_cells, "executing_runtime", lambda m: "matched")

    def changed_model():
        current["weight"][0] = 2.0
        return "native-result"

    result = state.run(object(), False, changed_model)
    assert result.computed == "native-result" and not result.native_key and state.model is None


def test_only_executing_native_libraries_affect_the_runtime(monkeypatch, tmp_path):
    import threadpoolctl

    dot = tmp_path / "coordinator-only-openmp.dll"
    dot.write_bytes(b"coordinator openmp")
    blas = tmp_path / "native-blas.dll"
    blas.write_bytes(b"executing blas")
    omp = {"prefix":"vcomp","user_api":"openmp","internal_api":"openmp","version":None,"num_threads":4,"filepath":str(dot)}
    worker = {"prefix":"openblas","user_api":"blas","internal_api":"openblas","version":"1","num_threads":2,"filepath":str(blas)}
    monkeypatch.setattr(native_cell_runtime, "IMPLEMENTATIONS", ())
    pools = [worker, omp]
    monkeypatch.setattr(threadpoolctl, "threadpool_info", lambda: list(pools))
    parent = native_cell_runtime.collect_implementation_files()
    pools.remove(omp)
    active = native_cell_runtime.executing_runtime(parent)
    assert active == native_cell_runtime.executing_runtime(native_cell_runtime.collect_implementation_files())
    pools.append(omp)
    assert native_cell_runtime.executing_runtime(parent) != active
    assert native_cell_runtime.executing_runtime({k:v for k,v in parent.items() if k != "native:"+str(dot)}) != active
    omp["num_threads"] = 0
    with pytest.raises(ValueError, match="Incomplete native library identity"):
        native_cell_runtime.executing_runtime(parent)
