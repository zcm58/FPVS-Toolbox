"""Thin GUI-to-backend adapter for Free Harmonic Clustering Analysis.

The page depends on this small surface so project discovery and scientific
backend changes do not leak into widget code. All methods are widget-free and
safe to invoke from a Qt worker thread.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import logging

from .models import (
    AnalysisSetup,
    GroupChoice,
    GuiAnalysisDesign,
    GuiHarmonicMode,
    ProjectAnalysisOptions,
    ProjectFrequencySnapshot,
    RunOutcome,
)


logger = logging.getLogger(__name__)

ProgressSink = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]


class BackendCapabilityError(RuntimeError):
    """Raised when the installed headless backend lacks a required v1 API."""


class FreeHarmonicBackend(Protocol):
    """Worker-facing operations consumed by the embedded page."""

    def inspect_project(
        self,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
        *,
        progress: ProgressSink,
        cancel_check: CancelCheck,
    ) -> ProjectAnalysisOptions: ...

    def prepare(
        self,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
        options: ProjectAnalysisOptions,
        setup: AnalysisSetup,
        *,
        progress: ProgressSink,
        cancel_check: CancelCheck,
    ) -> object: ...

    def run(
        self,
        prepared: object,
        *,
        progress: ProgressSink,
        cancel_check: CancelCheck,
    ) -> RunOutcome: ...

    def results_parent(self, project_root: Path) -> Path: ...


def _attribute(value: object, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _as_tuple(value: object) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return (value,)


def _normalized_options(raw: object, project_root: Path) -> ProjectAnalysisOptions:
    groups = tuple(
        GroupChoice(
            group_id=str(_attribute(group, "group_id", "id", default="")),
            label=str(_attribute(group, "label", "name", default="")),
        )
        for group in _as_tuple(_attribute(raw, "groups", "ordered_groups"))
    )
    conditions = tuple(
        str(value)
        for value in _as_tuple(_attribute(raw, "conditions", "condition_names"))
    )
    eligible_orders = tuple(
        int(value)
        for value in _as_tuple(
            _attribute(raw, "eligible_orders", "candidate_orders")
        )
    )
    eligible_hz = tuple(
        float(value)
        for value in _as_tuple(
            _attribute(
                raw,
                "eligible_harmonics_hz",
                "candidate_harmonics_hz",
                "eligible_frequencies_hz",
            )
        )
    )
    excluded_orders = tuple(
        int(value)
        for value in _as_tuple(_attribute(raw, "excluded_base_orders"))
    )
    excluded_hz = tuple(
        float(value)
        for value in _as_tuple(_attribute(raw, "excluded_base_harmonics_hz"))
    )
    fft_upper = _attribute(
        raw,
        "fft_upper_hz",
        "fft_upper_frequency_hz",
        "common_fft_upper_hz",
        "available_upper_hz",
        "upper_frequency_hz",
    )
    effective_upper = _attribute(
        raw,
        "effective_harmonic_upper_hz",
        "effective_harmonic_upper_frequency_hz",
    )
    resolution = _attribute(raw, "frequency_resolution_hz", "common_resolution_hz")
    fingerprint = _attribute(
        raw,
        "grid_fingerprint",
        "common_grid_fingerprint",
    )
    diagnostics = tuple(
        str(_attribute(item, "message", default=item))
        for item in _as_tuple(_attribute(raw, "diagnostics", "warnings"))
    )
    return ProjectAnalysisOptions(
        project_root=project_root,
        conditions=conditions,
        groups=groups,
        eligible_orders=eligible_orders,
        eligible_harmonics_hz=eligible_hz,
        excluded_base_orders=excluded_orders,
        excluded_base_harmonics_hz=excluded_hz,
        fft_upper_hz=None if fft_upper is None else float(fft_upper),
        effective_harmonic_upper_hz=(
            None if effective_upper is None else float(effective_upper)
        ),
        frequency_resolution_hz=None if resolution is None else float(resolution),
        grid_fingerprint=None if fingerprint in (None, "") else str(fingerprint),
        grid_compatible=bool(_attribute(raw, "grid_compatible", default=True)),
        grid_compatibility_verified=bool(
            _attribute(raw, "grid_compatibility_verified", default=False)
        ),
        compatibility_message=str(
            _attribute(raw, "compatibility_message", default="")
        ),
        workbook_count=int(_attribute(raw, "workbook_count", default=0)),
        representative_workbook_relative_path=str(
            _attribute(raw, "representative_workbook_relative_path", default="")
        ),
        diagnostics=diagnostics,
    )


class FreeHarmonicBackendAdapter:
    """Production adapter around the GUI-neutral package APIs."""

    def inspect_project(
        self,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
        *,
        progress: ProgressSink,
        cancel_check: CancelCheck,
    ) -> ProjectAnalysisOptions:
        started_at = perf_counter()
        root = Path(project_root)
        logger.info(
            "free_harmonic_gui_inspection_started",
            extra={
                "project_root": str(root),
                "oddball_frequency_hz": frequencies.oddball_frequency_hz,
                "base_frequency_hz": frequencies.base_frequency_hz,
            },
        )
        if cancel_check():
            self._raise_cancelled()
        progress(0, 1, "Reading project conditions and FullFFT headers...")
        try:
            from Tools.Free_Harmonic_Clustering import (
                inspect_project_analysis_options,
            )
        except ImportError as exc:
            raise BackendCapabilityError(
                "This build does not include the project-analysis inspection "
                "API required by Free Harmonic Clustering Analysis."
            ) from exc

        raw = inspect_project_analysis_options(
            root,
            oddball_frequency_hz=frequencies.oddball_frequency_hz,
            base_frequency_hz=frequencies.base_frequency_hz,
        )
        if cancel_check():
            self._raise_cancelled()
        options = _normalized_options(raw, root)
        if frequencies.max_harmonic_hz is not None:
            keep = tuple(
                index
                for index, value in enumerate(options.eligible_harmonics_hz)
                if value <= frequencies.max_harmonic_hz
            )
            excluded_keep = tuple(
                index
                for index, value in enumerate(options.excluded_base_harmonics_hz)
                if value <= frequencies.max_harmonic_hz
            )
            options = ProjectAnalysisOptions(
                project_root=options.project_root,
                conditions=options.conditions,
                groups=options.groups,
                eligible_orders=tuple(options.eligible_orders[index] for index in keep),
                eligible_harmonics_hz=tuple(
                    options.eligible_harmonics_hz[index] for index in keep
                ),
                excluded_base_orders=tuple(
                    options.excluded_base_orders[index] for index in excluded_keep
                ),
                excluded_base_harmonics_hz=tuple(
                    options.excluded_base_harmonics_hz[index]
                    for index in excluded_keep
                ),
                fft_upper_hz=options.fft_upper_hz,
                effective_harmonic_upper_hz=(
                    None
                    if not keep
                    else options.eligible_harmonics_hz[keep[-1]]
                ),
                frequency_resolution_hz=options.frequency_resolution_hz,
                grid_fingerprint=options.grid_fingerprint,
                grid_compatible=options.grid_compatible,
                grid_compatibility_verified=options.grid_compatibility_verified,
                compatibility_message=options.compatibility_message,
                workbook_count=options.workbook_count,
                representative_workbook_relative_path=(
                    options.representative_workbook_relative_path
                ),
                diagnostics=options.diagnostics,
            )
        logger.info(
            "free_harmonic_gui_inspection_completed",
            extra={
                "project_root": str(root),
                "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 3),
                "condition_count": len(options.conditions),
                "group_count": len(options.groups),
                "eligible_harmonic_count": len(options.eligible_orders),
                "workbook_count": options.workbook_count,
                "diagnostic_count": len(options.diagnostics),
            },
        )
        progress(1, 1, "Project inputs are ready.")
        return options

    def prepare(
        self,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
        options: ProjectAnalysisOptions,
        setup: AnalysisSetup,
        *,
        progress: ProgressSink,
        cancel_check: CancelCheck,
    ) -> object:
        from Tools.Free_Harmonic_Clustering import (
            AnalysisDesign,
            FreeHarmonicMethodSpec,
            ProjectContrastRequest,
            prepare_project_contrast,
        )

        design = (
            AnalysisDesign.PAIRED_CONDITIONS
            if setup.design is GuiAnalysisDesign.PAIRED_CONDITIONS
            else AnalysisDesign.INDEPENDENT_GROUPS
        )
        request = ProjectContrastRequest(
            project_root=Path(project_root),
            design=design,
            condition_a=setup.condition_a,
            condition_b=setup.condition_b,
            group_ids=setup.group_ids,
        )
        spec_fields = getattr(FreeHarmonicMethodSpec, "__dataclass_fields__", {})
        kwargs: dict[str, object] = {
            "oddball_frequency_hz": frequencies.oddball_frequency_hz,
            "base_frequency_hz": frequencies.base_frequency_hz,
            "max_harmonic_hz": setup.max_harmonic_hz,
        }
        if "harmonic_selection_mode" in spec_fields:
            try:
                from Tools.Free_Harmonic_Clustering import HarmonicSelectionMode

                mode = (
                    HarmonicSelectionMode.AUTOMATIC
                    if setup.harmonic_mode is GuiHarmonicMode.AUTOMATIC
                    else HarmonicSelectionMode.FIXED_HIGHEST
                )
            except (ImportError, AttributeError):
                mode = setup.harmonic_mode.value
            kwargs["harmonic_selection_mode"] = mode
            kwargs["fixed_highest_harmonic_order"] = (
                setup.fixed_highest_harmonic_order
            )
        elif setup.harmonic_mode is GuiHarmonicMode.FIXED_HIGHEST:
            raise BackendCapabilityError(
                "This build cannot prepare a fixed highest-harmonic domain."
            )
        spec = FreeHarmonicMethodSpec(**kwargs)

        def report(completed: int, total: int) -> None:
            progress(completed, total, "Reading and vectorizing FullFFT workbooks...")

        logger.info(
            "free_harmonic_gui_prepare_started",
            extra={
                "project_root": str(project_root),
                "design": setup.design.value,
                "harmonic_mode": setup.harmonic_mode.value,
            },
        )
        return prepare_project_contrast(
            request,
            spec,
            progress_callback=report,
            cancel_check=cancel_check,
        )

    def run(
        self,
        prepared: object,
        *,
        progress: ProgressSink,
        cancel_check: CancelCheck,
    ) -> RunOutcome:
        from Tools.Free_Harmonic_Clustering import (
            analyze_prepared_contrast,
            export_free_harmonic_run,
        )

        def report(completed: int, total: int) -> None:
            progress(completed, total, "Evaluating cluster permutations...")

        logger.info(
            "free_harmonic_gui_permutations_started",
            extra={"project_root": str(getattr(prepared, "project_root", ""))},
        )
        result = analyze_prepared_contrast(
            prepared,  # type: ignore[arg-type]
            progress=report,
            cancel_check=cancel_check,
        )
        if cancel_check():
            self._raise_cancelled()
        progress(1, 1, "Publishing the completed result bundle...")
        receipt = export_free_harmonic_run(prepared, result)  # type: ignore[arg-type]
        return RunOutcome(result=result, receipt=receipt)

    def results_parent(self, project_root: Path) -> Path:
        from Tools.Free_Harmonic_Clustering.exports import DEFAULT_RESULTS_SUBFOLDER

        return Path(project_root).expanduser().resolve(strict=False) / DEFAULT_RESULTS_SUBFOLDER

    @staticmethod
    def _raise_cancelled() -> None:
        from Tools.Free_Harmonic_Clustering import FreeHarmonicCancelledError

        raise FreeHarmonicCancelledError("Operation cancelled.")


__all__ = [
    "BackendCapabilityError",
    "CancelCheck",
    "FreeHarmonicBackend",
    "FreeHarmonicBackendAdapter",
    "ProgressSink",
]
