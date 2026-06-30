from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .core import (
    ConditionInfo,
    DetectabilitySettings,
    generate_condition_figure,
    parse_participant_id,
    sanitize_filename_stem,
)
from Tools.Stats.analysis.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CUSTOM_HARMONIC_SOURCE,
    CanonicalHarmonicSelectionError,
    analysis_base_frequency_hz,
    analysis_bca_upper_limit_hz,
    custom_harmonic_selection,
    select_canonical_group_harmonics,
)
from Tools.Stats.data.shared_rois import load_rois_from_settings


@dataclass(frozen=True)
class RunRequest:
    input_root: Path
    output_root: Path
    project_root: Path | None
    conditions: list[ConditionInfo]
    output_stems: dict[str, str]
    excluded_participants: set[str]
    settings: DetectabilitySettings


class IndividualDetectabilityWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    log = Signal(str)
    error = Signal(str)
    finished = Signal(str)

    def __init__(self, request: RunRequest) -> None:
        super().__init__()
        self._request = request

    def _emit_log(self, message: str) -> None:
        self.log.emit(message)
        self.status.emit(message)

    def run(self) -> None:
        try:
            import matplotlib

            matplotlib.use("Agg", force=True)
            self._run()
        except CanonicalHarmonicSelectionError as exc:
            self.error.emit(str(exc))
        except Exception:
            self.error.emit(traceback.format_exc())

    def _run(self) -> None:
        req = self._request
        total_conditions = len(req.conditions)
        if total_conditions == 0:
            self._emit_log("No conditions selected.")
            self.finished.emit(str(req.output_root))
            return

        log_path = req.output_root / self._log_filename(req.settings)
        req.output_root.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log_file:

            def write_log(message: str) -> None:
                log_file.write(message + "\n")
                log_file.flush()
                self._emit_log(message)

            effective_settings = self._resolve_effective_settings(write_log, req)
            self._write_run_metadata(req.output_root, req, effective_settings)
            self._log_header(write_log, req, effective_settings)

            for idx, condition in enumerate(req.conditions, start=1):
                write_log(f"Processing condition: {condition.name}")
                condition_out = req.output_root / sanitize_filename_stem(condition.name)
                stem = req.output_stems.get(condition.name) or sanitize_filename_stem(
                    f"{condition.name}_individual_detectability_grid"
                )
                if effective_settings.harmonic_source == CUSTOM_HARMONIC_SOURCE:
                    stem = self._custom_output_stem(stem)
                processed, total = generate_condition_figure(
                    condition=condition,
                    output_dir=condition_out,
                    output_stem=stem,
                    excluded=req.excluded_participants,
                    settings=effective_settings,
                    export_png=True,
                    log=write_log,
                )
                write_log(
                    f"Condition {condition.name}: processed {processed} of {total} files."
                )
                pct = int(idx / total_conditions * 100)
                self.progress.emit(pct)

        self.status.emit("Individual detectability export complete.")
        self.progress.emit(100)
        self.finished.emit(str(req.output_root))

    @staticmethod
    def _log_filename(settings: DetectabilitySettings) -> str:
        if settings.harmonic_source == CUSTOM_HARMONIC_SOURCE:
            return "individual_detectability_custom_harmonics_log.txt"
        return "individual_detectability_log.txt"

    @staticmethod
    def _custom_output_stem(stem: str) -> str:
        safe = sanitize_filename_stem(stem)
        if safe.endswith("_custom_harmonics"):
            return safe
        return f"{safe}_custom_harmonics"

    @staticmethod
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

        subjects, subject_data = IndividualDetectabilityWorker._stats_inputs_from_conditions(
            req.conditions,
            req.excluded_participants,
        )
        if not subjects:
            raise CanonicalHarmonicSelectionError(
                "No included participants were found for harmonic selection.",
                reason="no_subjects",
            )
        rois = load_rois_from_settings() or {}
        selection = select_canonical_group_harmonics(
            subjects=subjects,
            conditions=[condition.name for condition in req.conditions],
            subject_data=subject_data,
            base_frequency_hz=analysis_base_frequency_hz(),
            rois=rois,
            log_func=log,
            max_freq=analysis_bca_upper_limit_hz(),
            project_root=req.project_root,
        )
        log(selection.fingerprint_text)
        return replace(
            req.settings,
            oddball_harmonics_hz=list(selection.selected_harmonics_hz),
            harmonic_source=CANONICAL_HARMONIC_SOURCE,
            harmonic_fingerprint=selection.fingerprint_text,
        )

    @staticmethod
    def _stats_inputs_from_conditions(
        conditions: list[ConditionInfo],
        excluded_participants: set[str],
    ) -> tuple[list[str], dict[str, dict[str, str]]]:
        subject_data: dict[str, dict[str, str]] = {}
        for condition in conditions:
            for file_path in condition.files:
                participant = parse_participant_id(file_path.stem)
                if not participant or participant in excluded_participants:
                    continue
                subject_data.setdefault(participant, {})[condition.name] = str(file_path)
        subjects = sorted(subject_data.keys(), key=_participant_sort_key)
        return subjects, subject_data

    @staticmethod
    def _write_run_metadata(
        output_root: Path,
        req: RunRequest,
        settings: DetectabilitySettings,
    ) -> None:
        suffix = "_custom_harmonics" if settings.harmonic_source == CUSTOM_HARMONIC_SOURCE else ""
        metadata_path = output_root / f"individual_detectability{suffix}_metadata.json"
        payload = {
            "input_root": str(req.input_root),
            "output_root": str(req.output_root),
            "project_root": str(req.project_root) if req.project_root else "",
            "selected_conditions": [condition.name for condition in req.conditions],
            "excluded_participants": sorted(req.excluded_participants, key=_participant_sort_key),
            "harmonic_source": settings.harmonic_source,
            "exploratory": settings.harmonic_source == CUSTOM_HARMONIC_SOURCE,
            "selected_harmonics_hz": list(settings.oddball_harmonics_hz),
            "harmonic_selection_fingerprint": settings.harmonic_fingerprint,
            "settings": asdict(settings),
        }
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _log_header(
        log: Callable[[str], None],
        req: RunRequest,
        settings: DetectabilitySettings,
    ) -> None:
        log("Individual Detectability run")
        log(f"Input root: {req.input_root}")
        log(f"Output root: {req.output_root}")
        log(f"Project root: {req.project_root or ''}")
        log("Selected conditions:")
        for cond in req.conditions:
            log(f" - {cond.name} ({len(cond.files)} files)")
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
