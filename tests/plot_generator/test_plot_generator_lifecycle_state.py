from Tools.Plot_Generator.generation_lifecycle import PlotGeneratorLifecycleMixin


def test_reset_generation_run_state_clears_every_run_owned_field() -> None:
    owner = object.__new__(PlotGeneratorLifecycleMixin)
    owner._generated_paths = ["plot.png"]
    owner._failed_items = [{"item": "P01"}]
    owner._warning_items = [{"item": "P02"}]
    owner._spectral_qc_flags = [{"participant_id": "P03"}]
    owner._spectral_qc_analysis_identities = [("managed", "project")]
    owner._batch_dataset_index = object()
    owner._post_processing_required_request = ("stale", "project")
    owner._gen_params = ("stale",)
    owner._cancel_requested = True
    owner._worker_reported_cancelled = True
    owner._worker_outcome_received = True
    owner._late_cancel_after_commit = True

    owner._reset_generation_run_state()

    assert owner._generated_paths == []
    assert owner._failed_items == []
    assert owner._warning_items == []
    assert owner._spectral_qc_flags == []
    assert owner._spectral_qc_analysis_identities == []
    assert owner._batch_dataset_index is None
    assert owner._post_processing_required_request is None
    assert owner._gen_params is None
    assert owner._cancel_requested is False
    assert owner._worker_reported_cancelled is False
    assert owner._worker_outcome_received is False
    assert owner._late_cancel_after_commit is False
