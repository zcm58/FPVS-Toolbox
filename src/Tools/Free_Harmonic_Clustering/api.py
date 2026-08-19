"""Stable headless orchestration API for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Callable

from .exports import export_free_harmonic_run
from .models import (
    ClusterPermutationResult,
    ExportReceipt,
    FreeHarmonicCancelledError,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    PreparedContrast,
    PreparedRepeatedSessionBatch,
    PreparedRepeatedSessionContrast,
    ProjectAnalysisOptions,
    ProjectContrastRequest,
    ProjectGroupOption,
    ProjectRecordingOption,
    ProjectSessionOption,
    RepeatedSessionBatchRequest,
)


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


def _positive_frequency(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise FreeHarmonicInputError(f"{label} must be finite and positive.")
    try:
        frequency = float(value)
    except (TypeError, ValueError) as exc:
        raise FreeHarmonicInputError(f"{label} must be finite and positive.") from exc
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise FreeHarmonicInputError(f"{label} must be finite and positive.")
    return frequency


def inspect_project_analysis_options(
    project_root: str | Path,
    *,
    oddball_frequency_hz: float,
    base_frequency_hz: float,
    noise_half_width_hz: float = 0.1,
) -> ProjectAnalysisOptions:
    """Inspect canonical metadata and FullFFT headers without amplitudes/writes.

    The returned harmonic choices are derived from exactly one deterministic
    representative actual grid and its complete physical noise windows.  This
    keeps page-open discovery cheap; exact selected-cohort grid compatibility
    remains part of :func:`prepare_project_contrast`. Inspection conservatively
    blocks when the project has no current neutral FullFFT provenance;
    app-global settings are never silently treated as processed-project data.
    """

    from Main_App.io import read_xlsx_sheet_header
    from Main_App.processing.full_fft_provenance import (
        FullFftProvenanceError,
        validate_project_full_fft_provenance,
    )
    from Main_App.projects import load_project_dataset_index

    from .preparation import build_available_frequency_window_plan

    supplied_oddball_hz = _positive_frequency(
        oddball_frequency_hz,
        label="oddball_frequency_hz",
    )
    supplied_base_hz = _positive_frequency(
        base_frequency_hz,
        label="base_frequency_hz",
    )
    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FreeHarmonicInputError("project_root must be an existing managed project containing project.json.")
    try:
        dataset = load_project_dataset_index(root)
    except Exception as exc:
        raise FreeHarmonicInputError(f"Could not build the managed-project dataset index: {exc}") from exc
    if dataset.project_root.resolve(strict=False) != root:
        raise FreeHarmonicInputError("The dataset index resolved to a different active project root.")
    try:
        full_fft_provenance = validate_project_full_fft_provenance(
            root,
            base_frequency_hz=supplied_base_hz,
            oddball_frequency_hz=supplied_oddball_hz,
            dataset_index=dataset,
        )
    except FullFftProvenanceError as exc:
        raise FreeHarmonicInputError(str(exc)) from exc
    active_source_paths = tuple(full_fft_provenance.source_paths)
    if not active_source_paths:
        raise FreeHarmonicInputError(
            "Neutral FullFFT provenance has no active source workbook. Rerun "
            "post-processing; EEG preprocessing is not required."
        )
    representative_relative = str(active_source_paths[0])
    source = (root / representative_relative).resolve(strict=False)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise FreeHarmonicInputError(
            f"Neutral FullFFT provenance references a workbook outside the active project root: {source}"
        ) from exc
    if not source.is_file():
        raise FreeHarmonicInputError(f"Representative active workbook is missing: {representative_relative}")
    try:
        header = read_xlsx_sheet_header(
            source,
            sheet_name="FullFFT Amplitude (uV)",
        )
        representative_plan = build_available_frequency_window_plan(
            header,
            oddball_frequency_hz=supplied_oddball_hz,
            base_frequency_hz=supplied_base_hz,
            noise_half_width_hz=noise_half_width_hz,
        )
    except Exception as exc:
        raise FreeHarmonicInputError(
            f"Could not inspect the representative FullFFT header in {representative_relative}: {exc}"
        ) from exc

    if representative_plan.grid_fingerprint != full_fft_provenance.grid_fingerprint:
        raise FreeHarmonicInputError(
            "The representative FullFFT header does not match the saved neutral "
            "FullFFT grid provenance. Rerun post-processing; EEG preprocessing "
            "is not required."
        )

    compatibility_message = (
        "Neutral processed-project FullFFT provenance matched and the "
        "representative FullFFT header was inspected successfully. Exact grid "
        "compatibility for the selected cohort is validated during Run Analysis."
    )
    diagnostics = tuple(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in dataset.diagnostics)
    groups = tuple(ProjectGroupOption(group_id=group.group_id, label=group.label) for group in dataset.ordered_groups)
    sessions = tuple(
        ProjectSessionOption(
            session_id=session.session_id,
            label=session.label,
            visit_index=session.visit_index,
        )
        for session in getattr(dataset, "ordered_sessions", ())
    )
    recordings: list[ProjectRecordingOption] = []
    for recording in sorted(
        getattr(dataset, "recordings", {}).values(),
        key=lambda row: (
            row.participant_id.casefold(),
            row.visit_index,
            row.recording_id.casefold(),
        ),
    ):
        try:
            source_info = dataset.recording_sources[recording.source_id]
            group_info = dataset.groups[source_info.group_id]
            session_info = dataset.sessions[recording.session_id]
        except KeyError as exc:
            raise FreeHarmonicInputError(
                "Canonical repeated-session recording metadata references an "
                "unknown source, group, or session. Repair project.json before "
                "running Free Harmonic Clustering."
            ) from exc
        participant = dataset.participants.get(recording.participant_id)
        if (
            participant is not None
            and participant.group_id is not None
            and participant.group_id.casefold() != source_info.group_id.casefold()
        ):
            raise FreeHarmonicInputError(
                "Canonical participant and recording-source group identities "
                f"disagree for recording '{recording.recording_id}'."
            )
        recordings.append(
            ProjectRecordingOption(
                recording_id=recording.recording_id,
                participant_id=recording.participant_id,
                group_id=group_info.group_id,
                group_label=group_info.label,
                session_id=session_info.session_id,
                session_label=session_info.label,
                visit_index=session_info.visit_index,
            )
        )
    return ProjectAnalysisOptions(
        project_root=root,
        conditions=dataset.conditions,
        groups=groups,
        workbook_count=int(full_fft_provenance.source_workbook_count),
        representative_workbook_relative_path=representative_relative,
        grid_compatible=True,
        grid_compatibility_verified=False,
        compatibility_message=compatibility_message,
        grid_fingerprint=representative_plan.grid_fingerprint,
        frequency_resolution_hz=representative_plan.frequency_resolution_hz,
        fft_upper_frequency_hz=float(representative_plan.full_frequencies_hz[-1]),
        effective_harmonic_upper_frequency_hz=float(representative_plan.candidate_harmonics_hz[-1]),
        eligible_orders=tuple(int(value) for value in representative_plan.candidate_orders),
        eligible_harmonics_hz=tuple(float(value) for value in representative_plan.candidate_harmonics_hz),
        excluded_base_orders=tuple(int(value) for value in representative_plan.excluded_base_orders),
        excluded_base_harmonics_hz=tuple(float(value) for value in representative_plan.excluded_base_harmonics_hz),
        incompatible_workbooks=(),
        diagnostics=diagnostics,
        sessions=sessions,
        recordings=tuple(recordings),
    )


@dataclass(frozen=True, slots=True)
class FreeHarmonicRun:
    """In-memory preparation, optional inference, and optional export receipt."""

    prepared: PreparedContrast
    result: ClusterPermutationResult | None
    receipt: ExportReceipt | None

    @property
    def prepare_only(self) -> bool:
        return self.result is None


@dataclass(frozen=True, slots=True)
class RepeatedSessionContrastOutcome:
    """Inference plus run-level multiplicity for one batch contrast cell."""

    prepared_run: PreparedRepeatedSessionContrast
    result: ClusterPermutationResult
    derived_seed: int
    global_two_sided_p_value: float
    holm_within_family_p_value: float
    holm_all_batch_p_value: float

    def __post_init__(self) -> None:
        if not isinstance(self.prepared_run, PreparedRepeatedSessionContrast):
            raise TypeError("prepared_run must be a PreparedRepeatedSessionContrast.")
        if not isinstance(self.result, ClusterPermutationResult):
            raise TypeError("result must be a ClusterPermutationResult.")
        derived_seed = int(self.derived_seed)
        if isinstance(self.derived_seed, bool) or derived_seed < 0:
            raise ValueError("derived_seed must be a non-negative integer.")
        if self.result.seed != derived_seed:
            raise ValueError("Result seed does not match the derived batch seed.")
        for field_name in (
            "global_two_sided_p_value",
            "holm_within_family_p_value",
            "holm_all_batch_p_value",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be finite and between zero and one.")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "derived_seed", derived_seed)

    @property
    def family_id(self) -> str:
        return self.prepared_run.family_id

    @property
    def condition(self) -> str:
        return self.prepared_run.condition


@dataclass(frozen=True, slots=True)
class RepeatedSessionBatchResult:
    """All corrected condition/family results in stable preparation order."""

    outcomes: tuple[RepeatedSessionContrastOutcome, ...]
    base_seed: int
    within_family_method: str = "Holm across declared conditions"
    all_batch_method: str = "Holm across all declared batch contrasts"

    def __post_init__(self) -> None:
        outcomes = tuple(self.outcomes)
        if not outcomes or any(not isinstance(row, RepeatedSessionContrastOutcome) for row in outcomes):
            raise TypeError("outcomes must contain RepeatedSessionContrastOutcome values.")
        identities = {(row.family_id.casefold(), row.condition.casefold()) for row in outcomes}
        if len(identities) != len(outcomes):
            raise ValueError("Batch outcomes must be unique by family and condition.")
        base_seed = int(self.base_seed)
        if isinstance(self.base_seed, bool) or base_seed < 0:
            raise ValueError("base_seed must be a non-negative integer.")
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "base_seed", base_seed)


@dataclass(frozen=True, slots=True)
class RepeatedSessionBatchRun:
    """Prepared repeated batch, optional inference, and optional export."""

    prepared: PreparedRepeatedSessionBatch
    result: RepeatedSessionBatchResult | None
    receipt: ExportReceipt | None

    @property
    def prepare_only(self) -> bool:
        return self.result is None


def prepare_project_contrast(
    request: ProjectContrastRequest,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> PreparedContrast:
    """Load and prepare one contrast through the managed-project input adapter."""

    from .inputs import prepare_project_contrast as implementation

    return implementation(
        request,
        spec,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def analyze_prepared_contrast(
    prepared: PreparedContrast,
    *,
    batch_size: int = 256,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> ClusterPermutationResult:
    """Run cluster inference on an already prepared in-memory contrast."""

    from .analysis import analyze_prepared_contrast as implementation

    return implementation(
        prepared,
        batch_size=batch_size,
        progress=progress,
        cancel_check=cancel_check,
    )


def run_free_harmonic_clustering(
    request: ProjectContrastRequest,
    spec: FreeHarmonicMethodSpec | None = None,
    *,
    prepare_only: bool = False,
    run_id: str | None = None,
    destination: str | Path | None = None,
    batch_size: int = 256,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> FreeHarmonicRun:
    """Prepare one contrast, optionally infer, and atomically export one run.

    ``prepare_only=True`` is a strict no-write path. It returns the validated
    prepared tensors without creating the default results parent, a staging
    directory, or any run artifact.
    """

    if not isinstance(request, ProjectContrastRequest):
        raise TypeError("request must be a ProjectContrastRequest.")
    method = FreeHarmonicMethodSpec() if spec is None else spec
    if not isinstance(method, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    if isinstance(batch_size, bool) or int(batch_size) < 1:
        raise ValueError("batch_size must be a positive integer.")

    prepared = prepare_project_contrast(
        request,
        method,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if prepare_only:
        return FreeHarmonicRun(prepared=prepared, result=None, receipt=None)

    result = analyze_prepared_contrast(
        prepared,
        batch_size=int(batch_size),
        progress=progress_callback,
        cancel_check=cancel_check,
    )
    receipt = export_free_harmonic_run(
        prepared,
        result,
        run_id=run_id,
        destination=destination,
    )
    return FreeHarmonicRun(prepared=prepared, result=result, receipt=receipt)


def prepare_repeated_session_batch(
    request: RepeatedSessionBatchRequest,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> PreparedRepeatedSessionBatch:
    """Load one phase-balanced repeated-session batch from the active project."""

    from .inputs import prepare_repeated_session_batch as implementation

    return implementation(
        request,
        spec,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def analyze_prepared_repeated_session_batch(
    prepared: PreparedRepeatedSessionBatch,
    *,
    batch_size: int = 256,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> RepeatedSessionBatchResult:
    """Infer every prespecified batch cell and apply run-level Holm control."""

    from .analysis import (
        adjust_batch_cluster_p_values,
        derive_repeated_session_run_seed,
        run_cluster_permutation,
    )

    if not isinstance(prepared, PreparedRepeatedSessionBatch):
        raise TypeError("prepared must be a PreparedRepeatedSessionBatch.")
    if isinstance(batch_size, bool) or int(batch_size) < 1:
        raise ValueError("batch_size must be a positive integer.")
    if cancel_check is not None and cancel_check():
        raise FreeHarmonicCancelledError("Repeated-session Free Harmonic Clustering was cancelled.")

    runs = prepared.contrast_runs
    per_run = prepared.method.n_permutations
    total = len(runs) * per_run
    if progress is not None:
        progress(0, total)
    raw_results: list[ClusterPermutationResult] = []
    derived_seeds: list[int] = []
    for run_index, prepared_run in enumerate(runs):
        if cancel_check is not None and cancel_check():
            raise FreeHarmonicCancelledError("Repeated-session Free Harmonic Clustering was cancelled.")
        seed = derive_repeated_session_run_seed(
            prepared.method.seed,
            family_id=prepared_run.family_id,
            condition=prepared_run.condition,
        )
        derived_method = replace(prepared.method, seed=seed)

        def run_progress(
            completed: int,
            _run_total: int,
            *,
            completed_before: int = run_index * per_run,
        ) -> None:
            if progress is not None:
                progress(completed_before + int(completed), total)

        contrast = prepared_run.prepared
        result = run_cluster_permutation(
            contrast.values_a,
            contrast.values_b,
            design=contrast.request.design,
            method=derived_method,
            sensor_names=contrast.sensor_names,
            batch_size=int(batch_size),
            progress=run_progress,
            cancel_check=cancel_check,
        )
        raw_results.append(result)
        derived_seeds.append(seed)

    multiplicity = adjust_batch_cluster_p_values(
        tuple((run.family_id, run.condition, result) for run, result in zip(runs, raw_results, strict=True))
    )
    outcomes = tuple(
        RepeatedSessionContrastOutcome(
            prepared_run=run,
            result=result,
            derived_seed=seed,
            global_two_sided_p_value=adjusted.global_two_sided_p_value,
            holm_within_family_p_value=(adjusted.holm_within_family_p_value),
            holm_all_batch_p_value=adjusted.holm_all_batch_p_value,
        )
        for run, result, seed, adjusted in zip(
            runs,
            raw_results,
            derived_seeds,
            multiplicity,
            strict=True,
        )
    )
    return RepeatedSessionBatchResult(
        outcomes=outcomes,
        base_seed=prepared.method.seed,
    )


def run_repeated_session_fhc_batch(
    request: RepeatedSessionBatchRequest,
    spec: FreeHarmonicMethodSpec | None = None,
    *,
    prepare_only: bool = False,
    run_id: str | None = None,
    destination: str | Path | None = None,
    batch_size: int = 256,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> RepeatedSessionBatchRun:
    """Prepare, infer, and atomically export the repeated-session FHC batch."""

    if not isinstance(request, RepeatedSessionBatchRequest):
        raise TypeError("request must be a RepeatedSessionBatchRequest.")
    method = FreeHarmonicMethodSpec() if spec is None else spec
    if not isinstance(method, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    if isinstance(batch_size, bool) or int(batch_size) < 1:
        raise ValueError("batch_size must be a positive integer.")
    prepared = prepare_repeated_session_batch(
        request,
        method,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if prepare_only:
        return RepeatedSessionBatchRun(
            prepared=prepared,
            result=None,
            receipt=None,
        )
    result = analyze_prepared_repeated_session_batch(
        prepared,
        batch_size=int(batch_size),
        progress=progress_callback,
        cancel_check=cancel_check,
    )
    from .exports import export_repeated_session_batch

    receipt = export_repeated_session_batch(
        prepared,
        result,
        run_id=run_id,
        destination=destination,
    )
    return RepeatedSessionBatchRun(
        prepared=prepared,
        result=result,
        receipt=receipt,
    )


__all__ = [
    "FreeHarmonicRun",
    "RepeatedSessionBatchResult",
    "RepeatedSessionBatchRun",
    "RepeatedSessionContrastOutcome",
    "analyze_prepared_contrast",
    "analyze_prepared_repeated_session_batch",
    "inspect_project_analysis_options",
    "prepare_project_contrast",
    "prepare_repeated_session_batch",
    "run_free_harmonic_clustering",
    "run_repeated_session_fhc_batch",
]
