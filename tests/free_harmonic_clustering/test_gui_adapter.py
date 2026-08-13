from __future__ import annotations

from pathlib import Path

from Tools.Free_Harmonic_Clustering import (
    HarmonicSelectionMode,
    ProjectAnalysisOptions as BackendProjectAnalysisOptions,
    ProjectGroupOption,
)
from Tools.Free_Harmonic_Clustering.gui.backend_adapter import (
    FreeHarmonicBackendAdapter,
)
from Tools.Free_Harmonic_Clustering.gui.models import (
    AnalysisSetup,
    GroupChoice,
    GuiAnalysisDesign,
    GuiHarmonicMode,
    ProjectAnalysisOptions,
    ProjectFrequencySnapshot,
)
from Tools.Free_Harmonic_Clustering.gui.operation_registry import (
    cancel_all_active_operations,
    has_active_operations,
    register_active_operation,
    release_active_operation,
)


def _backend_options(project_root: Path) -> BackendProjectAnalysisOptions:
    return BackendProjectAnalysisOptions(
        project_root=project_root,
        conditions=("Neutral Happy", "Neutral Fear"),
        groups=(
            ProjectGroupOption(group_id="anxious", label="Anxious"),
            ProjectGroupOption(group_id="non_anxious", label="Non-Anxious"),
        ),
        workbook_count=40,
        representative_workbook_relative_path="1 - Excel Data Files/P01.xlsx",
        grid_compatible=True,
        grid_compatibility_verified=False,
        compatibility_message="Exact cohort compatibility is checked during Prepare.",
        grid_fingerprint="grid-sha",
        frequency_resolution_hz=0.01,
        fft_upper_frequency_hz=20.0,
        effective_harmonic_upper_frequency_hz=19.2,
        eligible_orders=(1, 2, 3, 4, 6, 7),
        eligible_harmonics_hz=(1.2, 2.4, 3.6, 4.8, 7.2, 8.4),
        excluded_base_orders=(5,),
        excluded_base_harmonics_hz=(6.0,),
        diagnostics=("example diagnostic",),
    )


def _gui_options(project_root: Path) -> ProjectAnalysisOptions:
    return ProjectAnalysisOptions(
        project_root=project_root,
        conditions=("Neutral Happy", "Neutral Fear"),
        groups=(
            GroupChoice("anxious", "Anxious"),
            GroupChoice("non_anxious", "Non-Anxious"),
        ),
        eligible_orders=(1, 2, 3, 4, 6),
        eligible_harmonics_hz=(1.2, 2.4, 3.6, 4.8, 7.2),
        excluded_base_orders=(5,),
        excluded_base_harmonics_hz=(6.0,),
        fft_upper_hz=20.0,
        effective_harmonic_upper_hz=19.2,
    )


def test_adapter_normalizes_real_header_inspection_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw = _backend_options(tmp_path)
    monkeypatch.setattr(
        "Tools.Free_Harmonic_Clustering.inspect_project_analysis_options",
        lambda *_args, **_kwargs: raw,
    )
    progress: list[tuple[int, int, str]] = []

    options = FreeHarmonicBackendAdapter().inspect_project(
        tmp_path,
        ProjectFrequencySnapshot(1.2, 6.0, max_harmonic_hz=7.2),
        progress=lambda current, total, text: progress.append(
            (current, total, text)
        ),
        cancel_check=lambda: False,
    )

    assert options.conditions == raw.conditions
    assert tuple(group.group_id for group in options.groups) == (
        "anxious",
        "non_anxious",
    )
    assert options.fft_upper_hz == 20.0
    assert options.effective_harmonic_upper_hz == 7.2
    assert options.eligible_orders == (1, 2, 3, 4, 6)
    assert options.excluded_base_orders == (5,)
    assert not options.grid_compatibility_verified
    assert progress[-1] == (1, 1, "Project inputs are ready.")


def test_fixed_highest_setup_builds_explicit_backend_spec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_prepare(request, spec, **kwargs):
        captured.update(request=request, spec=spec, kwargs=kwargs)
        return sentinel

    monkeypatch.setattr(
        "Tools.Free_Harmonic_Clustering.prepare_project_contrast",
        fake_prepare,
    )
    setup = AnalysisSetup(
        design=GuiAnalysisDesign.INDEPENDENT_GROUPS,
        condition_a="Neutral Happy",
        condition_b=None,
        group_ids=("anxious", "non_anxious"),
        harmonic_mode=GuiHarmonicMode.FIXED_HIGHEST,
        fixed_highest_harmonic_order=6,
        max_harmonic_hz=7.2,
    )

    prepared = FreeHarmonicBackendAdapter().prepare(
        tmp_path,
        ProjectFrequencySnapshot(1.2, 6.0),
        _gui_options(tmp_path),
        setup,
        progress=lambda *_args: None,
        cancel_check=lambda: False,
    )

    assert prepared is sentinel
    spec = captured["spec"]
    assert spec.harmonic_selection_mode is HarmonicSelectionMode.FIXED_HIGHEST
    assert spec.fixed_highest_harmonic_order == 6
    assert spec.max_harmonic_hz == 7.2
    request = captured["request"]
    assert request.group_ids == ("anxious", "non_anxious")


def test_process_operation_registry_cancels_retired_page_work() -> None:
    class Worker:
        cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

    token = object()
    worker = Worker()
    register_active_operation(token, worker)
    try:
        assert has_active_operations()
        assert cancel_all_active_operations() == 1
        assert worker.cancel_calls == 1
        assert has_active_operations()
    finally:
        release_active_operation(token)

    assert not has_active_operations()
    release_active_operation(token)
