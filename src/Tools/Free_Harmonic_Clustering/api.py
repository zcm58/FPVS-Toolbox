"""Stable headless orchestration API for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from .exports import export_free_harmonic_run
from .models import (
    ClusterPermutationResult,
    ExportReceipt,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    PreparedContrast,
    ProjectAnalysisOptions,
    ProjectContrastRequest,
    ProjectGroupOption,
)


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]

_RATE_TOLERANCE_HZ = 1e-9


def _positive_frequency(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise FreeHarmonicInputError(f"{label} must be finite and positive.")
    try:
        frequency = float(value)
    except (TypeError, ValueError) as exc:
        raise FreeHarmonicInputError(
            f"{label} must be finite and positive."
        ) from exc
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise FreeHarmonicInputError(f"{label} must be finite and positive.")
    return frequency


def _manifest_relative_path(value: object) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
    ):
        return None
    return posix.as_posix()


def _cached_rate(
    values: Mapping[str, object],
    key: str,
) -> float | None:
    if key not in values or isinstance(values[key], bool):
        return None
    try:
        rate = float(values[key])
    except (TypeError, ValueError):
        return None
    return rate if math.isfinite(rate) and rate > 0.0 else None


def _same_rate(left: float, right: float) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=0.0,
        abs_tol=_RATE_TOLERANCE_HZ,
    )


def _entry_frequency_rates(
    entry: Mapping[str, object],
) -> tuple[tuple[float, float] | None, str | None]:
    fingerprint = entry.get("fingerprint")
    if not isinstance(fingerprint, Mapping):
        return None, "matching cache entry has no fingerprint"
    settings = fingerprint.get("stats_settings")
    if not isinstance(settings, Mapping):
        return None, "matching fingerprint has no stats_settings"
    base_hz = _cached_rate(settings, "base_frequency_hz")
    oddball_hz = _cached_rate(settings, "oddball_frequency_hz")
    if base_hz is None or oddball_hz is None:
        return None, "matching fingerprint has missing or invalid frequency rates"

    selection = entry.get("selection_metadata")
    if selection is not None and not isinstance(selection, Mapping):
        return None, "matching selection_metadata is not a mapping"
    if isinstance(selection, Mapping):
        for key, fingerprint_rate in (
            ("base_frequency_hz", base_hz),
            ("oddball_frequency_hz", oddball_hz),
        ):
            if key not in selection:
                continue
            selection_rate = _cached_rate(selection, key)
            if selection_rate is None:
                return None, f"selection_metadata contains an invalid {key}"
            if not _same_rate(selection_rate, fingerprint_rate):
                return None, (
                    f"selection_metadata {key}={selection_rate:g} conflicts "
                    f"with fingerprint stats_settings {key}={fingerprint_rate:g}"
                )
    return (base_hz, oddball_hz), None


def _verify_processed_frequency_provenance(
    *,
    manifest: object,
    representative_relative_path: str,
    representative_path: Path,
    supplied_base_hz: float,
    supplied_oddball_hz: float,
) -> tuple[float, float]:
    """Verify current rates against cached processed-workbook provenance only."""

    actionable = (
        "Restore the rates used for this project in Project Settings, or "
        "regenerate the post-processing/Stats frequency provenance with the "
        "intended rates before running Free Harmonic Clustering Analysis."
    )
    if not isinstance(manifest, Mapping):
        raise FreeHarmonicInputError(
            "No managed project frequency provenance is available. " + actionable
        )
    tools = manifest.get("tools")
    stats = tools.get("stats") if isinstance(tools, Mapping) else None
    cache = (
        stats.get("group_significant_harmonics_cache")
        if isinstance(stats, Mapping)
        else None
    )
    entries = cache.get("entries") if isinstance(cache, Mapping) else None
    if not isinstance(entries, Mapping) or not entries:
        raise FreeHarmonicInputError(
            "No matching processed-project base/oddball frequency provenance "
            "exists in project.json. "
            + actionable
        )

    normalized_representative = _manifest_relative_path(
        representative_relative_path
    )
    if normalized_representative is None:  # pragma: no cover - internal guard
        raise FreeHarmonicInputError(
            "Representative workbook provenance is not project-relative."
        )
    representative_stat = representative_path.stat()
    matching_rates: list[tuple[float, float]] = []
    matching_problems: list[str] = []
    stale_path_match = False
    for entry in entries.values():
        if not isinstance(entry, Mapping):
            continue
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, Mapping):
            continue
        source_rows = fingerprint.get("source_workbooks")
        if not isinstance(source_rows, Sequence) or isinstance(
            source_rows,
            (str, bytes),
        ):
            continue
        exact_workbook_match = False
        for source_row in source_rows:
            if not isinstance(source_row, Mapping):
                continue
            cached_path = _manifest_relative_path(source_row.get("path"))
            if (
                cached_path is None
                or cached_path.casefold()
                != normalized_representative.casefold()
            ):
                continue
            try:
                cached_size = int(source_row.get("size_bytes"))
                cached_mtime = int(source_row.get("mtime_ns"))
            except (TypeError, ValueError):
                stale_path_match = True
                continue
            if (
                cached_size == int(representative_stat.st_size)
                and cached_mtime == int(representative_stat.st_mtime_ns)
            ):
                exact_workbook_match = True
            else:
                stale_path_match = True
        if not exact_workbook_match:
            continue
        rates, problem = _entry_frequency_rates(entry)
        if problem is not None:
            matching_problems.append(problem)
        elif rates is not None:
            matching_rates.append(rates)

    if matching_problems:
        raise FreeHarmonicInputError(
            "Conflicting or invalid processed-project frequency provenance was "
            "found for the representative workbook: "
            + "; ".join(sorted(set(matching_problems)))
            + ". "
            + actionable
        )
    if not matching_rates:
        if stale_path_match:
            detail = (
                "The saved workbook path matched, but its recorded size or "
                "modification time is stale. "
            )
        else:
            detail = (
                "No cache entry contains the representative workbook with a "
                "matching project-relative path, size, and modification time. "
            )
        raise FreeHarmonicInputError(detail + actionable)

    distinct_rates: list[tuple[float, float]] = []
    for rates in matching_rates:
        if not any(
            _same_rate(rates[0], known[0])
            and _same_rate(rates[1], known[1])
            for known in distinct_rates
        ):
            distinct_rates.append(rates)
    if len(distinct_rates) != 1:
        formatted = ", ".join(
            f"base={base:g} Hz / oddball={oddball:g} Hz"
            for base, oddball in distinct_rates
        )
        raise FreeHarmonicInputError(
            "Conflicting processed-project frequency rates were found for the "
            f"representative workbook ({formatted}). "
            + actionable
        )
    expected_base_hz, expected_oddball_hz = distinct_rates[0]
    if not (
        _same_rate(supplied_base_hz, expected_base_hz)
        and _same_rate(supplied_oddball_hz, expected_oddball_hz)
    ):
        raise FreeHarmonicInputError(
            "Current Project Settings rates do not match the processed-project "
            "provenance for the representative workbook: current "
            f"base={supplied_base_hz:g} Hz / oddball={supplied_oddball_hz:g} Hz; "
            f"processed base={expected_base_hz:g} Hz / "
            f"oddball={expected_oddball_hz:g} Hz. "
            + actionable
        )
    return expected_base_hz, expected_oddball_hz


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
    remains part of :func:`prepare_project_contrast`.  V1 conservatively blocks
    when the representative workbook has no matching project.json frequency
    provenance; app-global settings are never silently treated as project data.
    """

    from Main_App.projects import load_project_dataset_index
    from Tools.Stats.io.xlsx_selected_reader import read_xlsx_sheet_header

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
        raise FreeHarmonicInputError(
            "project_root must be an existing managed project containing "
            "project.json."
        )
    try:
        dataset = load_project_dataset_index(root)
    except Exception as exc:
        raise FreeHarmonicInputError(
            f"Could not build the managed-project dataset index: {exc}"
        ) from exc
    if dataset.project_root.resolve(strict=False) != root:
        raise FreeHarmonicInputError(
            "The dataset index resolved to a different active project root."
        )
    records = tuple(dataset.workbooks)
    if not records:
        raise FreeHarmonicInputError(
            "No indexed processed workbooks are available for inspection."
        )

    record = records[0]
    source = Path(record.path).resolve(strict=False)
    try:
        representative_relative = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise FreeHarmonicInputError(
            f"Indexed workbook escapes the active project root: {source}"
        ) from exc
    if not source.is_file():
        raise FreeHarmonicInputError(
            f"Representative indexed workbook is missing: {representative_relative}"
        )
    _verify_processed_frequency_provenance(
        manifest=getattr(dataset, "manifest", None),
        representative_relative_path=representative_relative,
        representative_path=source,
        supplied_base_hz=supplied_base_hz,
        supplied_oddball_hz=supplied_oddball_hz,
    )
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
            "Could not inspect the representative FullFFT header in "
            f"{representative_relative}: {exc}"
        ) from exc

    compatibility_message = (
        "Processed-project base/oddball frequency provenance matched and the "
        "representative FullFFT header was inspected successfully. Exact grid "
        "compatibility for the selected cohort is validated during Prepare Analysis."
    )
    diagnostics = tuple(
        f"{diagnostic.code}: {diagnostic.message}"
        for diagnostic in dataset.diagnostics
    )
    groups = tuple(
        ProjectGroupOption(group_id=group.group_id, label=group.label)
        for group in dataset.ordered_groups
    )
    return ProjectAnalysisOptions(
        project_root=root,
        conditions=dataset.conditions,
        groups=groups,
        workbook_count=len(records),
        representative_workbook_relative_path=representative_relative,
        grid_compatible=True,
        grid_compatibility_verified=False,
        compatibility_message=compatibility_message,
        grid_fingerprint=representative_plan.grid_fingerprint,
        frequency_resolution_hz=representative_plan.frequency_resolution_hz,
        fft_upper_frequency_hz=float(
            representative_plan.full_frequencies_hz[-1]
        ),
        effective_harmonic_upper_frequency_hz=float(
            representative_plan.candidate_harmonics_hz[-1]
        ),
        eligible_orders=tuple(
            int(value) for value in representative_plan.candidate_orders
        ),
        eligible_harmonics_hz=tuple(
            float(value)
            for value in representative_plan.candidate_harmonics_hz
        ),
        excluded_base_orders=tuple(
            int(value) for value in representative_plan.excluded_base_orders
        ),
        excluded_base_harmonics_hz=tuple(
            float(value)
            for value in representative_plan.excluded_base_harmonics_hz
        ),
        incompatible_workbooks=(),
        diagnostics=diagnostics,
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


__all__ = [
    "FreeHarmonicRun",
    "analyze_prepared_contrast",
    "inspect_project_analysis_options",
    "prepare_project_contrast",
    "run_free_harmonic_clustering",
]
