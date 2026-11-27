"""Qt-free Individual Detectability batch export."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

from .core import (
    ConditionInfo,
    DetectabilitySettings,
    generate_condition_figure,
    parse_participant_id,
    prevalidate_managed_conditions,
    sanitize_filename_stem,
)
from .project_coverage import (
    ManagedWorkbookCoverage,
    load_managed_project_coverage,
    select_managed_conditions,
)
from Main_App.processing.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CUSTOM_HARMONIC_SOURCE,
    CanonicalHarmonicSelectionError,
    custom_harmonic_selection,
    load_project_processing_harmonics,
)
from Main_App.projects import resolve_group_output_directory


@dataclass(frozen=True)
class RunRequest:
    input_root: Path
    output_root: Path
    project_root: Path | None
    conditions: list[ConditionInfo]
    output_stems: dict[str, str]
    excluded_participants: set[str]
    settings: DetectabilitySettings


def run_detectability_export(
    req: RunRequest,
    *,
    log: Callable[[str], None],
    status: Callable[[str], None],
    progress: Callable[[int], None],
) -> Path | None:
    """Return the output directory if this run produced a figure, otherwise None."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    req, managed_coverage = _require_current_project_inputs(req)
    total_conditions = len(req.conditions)
    if not total_conditions or (
        managed_coverage is None and req.excluded_participants and all(
            parse_participant_id(path.stem) in req.excluded_participants
            for condition in req.conditions for path in condition.files
        )
    ):
        log("No figures were generated. No selected inputs remain after participant and project QC exclusions.")
        return None

    preflight_log: list[str] = []
    effective_settings = _resolve_effective_settings(
        preflight_log.append,
        req,
    )
    if managed_coverage is not None:
        prevalidate_managed_conditions(
            req.conditions,
            effective_settings,
            managed_coverage,
        )

    log_path = req.output_root / _log_filename(req.settings)
    req.output_root.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:

        def write_log(message: str) -> None:
            log_file.write(message + "\n")
            log_file.flush()
            log(message)

        for message in preflight_log:
            write_log(message)
        _write_run_metadata(
            req.output_root,
            req,
            effective_settings,
            managed_coverage,
        )
        _log_header(
            write_log,
            req,
            effective_settings,
            managed_coverage,
        )

        produced_figures = False
        for idx, condition in enumerate(req.conditions, start=1):
            write_log(f"Processing condition: {condition.display_name}")
            condition_out = req.output_root / sanitize_filename_stem(condition.name)
            if condition.group is not None:
                condition_out = resolve_group_output_directory(condition_out, condition.group.folder_name)
            stem = req.output_stems.get(condition.name) or sanitize_filename_stem(
                f"{condition.name}_individual_detectability_grid"
            )
            if effective_settings.harmonic_source == CUSTOM_HARMONIC_SOURCE:
                stem = _custom_output_stem(stem)
            processed, total = generate_condition_figure(
                condition=condition,
                output_dir=condition_out,
                output_stem=stem,
                excluded=req.excluded_participants,
                settings=effective_settings,
                export_png=True,
                log=write_log,
                managed_coverage_by_workbook=managed_coverage,
            )
            write_log(
                f"Condition {condition.display_name}: processed {processed} of {total} files."
            )
            produced_figures = produced_figures or processed > 0
            pct = int(idx / total_conditions * 100)
            progress(pct)
        if not produced_figures:
            write_log("No figures were generated. The generation log lists the skipped inputs.")
            return None

    status("Individual detectability export complete.")
    progress(100)
    return req.output_root


def _require_current_project_inputs(
    req: RunRequest,
) -> tuple[RunRequest, dict[Path, ManagedWorkbookCoverage] | None]:
    """Bind managed runs to the current canonical FullFFT source family."""

    if req.project_root is None:
        return req, None
    from Main_App.processing.full_fft_provenance import (
        FullFftProvenanceError,
        require_current_project_full_fft_provenance,
    )
    from Main_App.projects import DatasetIndexError, load_project_dataset_index
    from Main_App.processing.roi_coverage import RoiCoverageGateError

    try:
        dataset_index = load_project_dataset_index(req.project_root)
        provenance = require_current_project_full_fft_provenance(
            req.project_root,
            dataset_index=dataset_index,
        )
        coverage = load_managed_project_coverage(req.project_root)
        conditions = select_managed_conditions(
            req.conditions,
            dataset_index=dataset_index,
            provenance=provenance,
            coverage=coverage,
            excluded_participants=req.excluded_participants,
        )
    except (
        DatasetIndexError,
        FullFftProvenanceError,
        RoiCoverageGateError,
    ) as exc:
        raise CanonicalHarmonicSelectionError(
            str(exc),
            reason="stale_project_qc_release",
        ) from exc
    return replace(req, conditions=conditions), dict(coverage.by_workbook)


def _log_filename(settings: DetectabilitySettings) -> str:
    if settings.harmonic_source == CUSTOM_HARMONIC_SOURCE:
        return "individual_detectability_custom_harmonics_log.txt"
    return "individual_detectability_log.txt"


def _custom_output_stem(stem: str) -> str:
    safe = sanitize_filename_stem(stem)
    if safe.endswith("_custom_harmonics"):
        return safe
    return f"{safe}_custom_harmonics"


def _resolve_effective_settings(
    log: Callable[[str], None],
    req: RunRequest,
) -> DetectabilitySettings:
    if req.settings.harmonic_source == CUSTOM_HARMONIC_SOURCE:
        selection = custom_harmonic_selection(req.settings.oddball_harmonics_hz)
        log(
            "Using custom/exploratory fixed harmonics. These outputs do not "
            "replace the FPVS Toolbox significant-harmonic selection."
        )
        log(selection.fingerprint_text)
        return replace(
            req.settings,
            harmonic_fingerprint=selection.fingerprint_text,
        )

    selection = load_project_processing_harmonics(
        project_root=req.project_root,
        log_func=log,
    )
    log(selection.fingerprint_text)
    return replace(
        req.settings,
        oddball_harmonics_hz=list(selection.selected_harmonics_hz),
        harmonic_source=CANONICAL_HARMONIC_SOURCE,
        harmonic_fingerprint=selection.fingerprint_text,
    )


def _write_run_metadata(
    output_root: Path,
    req: RunRequest,
    settings: DetectabilitySettings,
    managed_coverage: dict[Path, ManagedWorkbookCoverage] | None,
) -> None:
    suffix = "_custom_harmonics" if settings.harmonic_source == CUSTOM_HARMONIC_SOURCE else ""
    metadata_path = output_root / f"individual_detectability{suffix}_metadata.json"
    selected_workbooks = {
        path.expanduser().resolve(strict=False)
        for condition in req.conditions
        for path in condition.files
    }
    payload = {
        "input_root": str(req.input_root),
        "output_root": str(req.output_root),
        "project_root": str(req.project_root) if req.project_root else "",
        "selected_conditions": [condition.name for condition in req.conditions],
        "selected_condition_groups": [
            {"condition": condition.name, "group_id": condition.group.group_id}
            for condition in req.conditions if condition.group is not None
        ],
        "excluded_participants": sorted(req.excluded_participants, key=_participant_sort_key),
        "harmonic_source": settings.harmonic_source,
        "exploratory": settings.harmonic_source == CUSTOM_HARMONIC_SOURCE,
        "selected_harmonics_hz": list(settings.oddball_harmonics_hz),
        "harmonic_selection_fingerprint": settings.harmonic_fingerprint,
        "final_release_receipt_fingerprint": (
            _managed_release_fingerprint(managed_coverage)
        ),
        "managed_source_coverage_fingerprints": {
            str(path): coverage.source_evidence_fingerprint
            for path, coverage in sorted(
                (managed_coverage or {}).items(),
                key=lambda item: str(item[0]).casefold(),
            )
            if path in selected_workbooks
        },
        "settings": asdict(settings),
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _log_header(
    log: Callable[[str], None],
    req: RunRequest,
    settings: DetectabilitySettings,
    managed_coverage: dict[Path, ManagedWorkbookCoverage] | None,
) -> None:
    log("Individual Detectability run")
    log(f"Input root: {req.input_root}")
    log(f"Output root: {req.output_root}")
    log(f"Project root: {req.project_root or ''}")
    release_fingerprint = _managed_release_fingerprint(managed_coverage)
    if release_fingerprint:
        log(f"QC-20/QC-21 final release: {release_fingerprint}")
    log("Selected conditions:")
    for cond in req.conditions:
        log(f" - {cond.display_name} ({len(cond.files)} files)")
    log(f"Harmonic source: {settings.harmonic_source}")
    if settings.harmonic_fingerprint:
        log(f"Harmonic fingerprint: {settings.harmonic_fingerprint}")
    log(f"Harmonics: {', '.join([str(h) for h in settings.oddball_harmonics_hz])}")
    log(f"Z threshold: {settings.z_threshold}")
    log(f"BH-FDR enabled: {settings.use_bh_fdr}")
    log(f"FDR alpha: {settings.fdr_alpha}")
    log(f"SNR half window: {settings.half_window_hz}")
    log(
        "SNR y-limits: "
        f"{settings.snr_ymin_fixed} to {settings.snr_ymax_fixed}"
    )
    log(f"SNR mid xtick: {settings.snr_show_mid_xtick}")
    log(f"Grid columns: {settings.grid_ncols}")
    log(f"Letter portrait: {settings.use_letter_portrait}")
    log("Export PDF: True")
    log("Export PNG: True")


def _participant_sort_key(participant_id: str) -> tuple[int, str]:
    text = str(participant_id)
    digits = text[1:] if text.upper().startswith("P") else text
    try:
        return (int(digits), text)
    except ValueError:
        return (10**9, text)


def _managed_release_fingerprint(
    managed_coverage: dict[Path, ManagedWorkbookCoverage] | None,
) -> str:
    fingerprints = {
        coverage.final_release_receipt_fingerprint
        for coverage in (managed_coverage or {}).values()
    }
    if len(fingerprints) > 1:
        raise RuntimeError(
            "Individual Detectability received workbooks from multiple final releases."
        )
    return next(iter(fingerprints), "")
