from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .core import (
    ConditionInfo,
    DetectabilitySettings,
    generate_condition_figure,
    sanitize_filename_stem,
)


@dataclass(frozen=True)
class RunRequest:
    input_root: Path
    output_root: Path
    conditions: list[ConditionInfo]
    output_stems: dict[str, str]
    excluded_participants: set[str]
    settings: DetectabilitySettings
    export_png: bool


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
        except Exception:
            self.error.emit(traceback.format_exc())

    def _run(self) -> None:
        req = self._request
        total_conditions = len(req.conditions)
        if total_conditions == 0:
            self._emit_log("No conditions selected.")
            self.finished.emit(str(req.output_root))
            return

        log_path = req.output_root / "individual_detectability_log.txt"
        req.output_root.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log_file:

            def write_log(message: str) -> None:
                log_file.write(message + "\n")
                log_file.flush()
                self._emit_log(message)

            self._log_header(write_log, req)

            for idx, condition in enumerate(req.conditions, start=1):
                write_log(f"Processing condition: {condition.name}")
                condition_out = req.output_root / sanitize_filename_stem(condition.name)
                stem = req.output_stems.get(condition.name) or sanitize_filename_stem(
                    f"{condition.name}_individual_detectability_grid"
                )
                processed, total = generate_condition_figure(
                    condition=condition,
                    output_dir=condition_out,
                    output_stem=stem,
                    excluded=req.excluded_participants,
                    settings=req.settings,
                    export_png=req.export_png,
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
    def _log_header(log: Callable[[str], None], req: RunRequest) -> None:
        log("Individual Detectability run")
        log(f"Input root: {req.input_root}")
        log(f"Output root: {req.output_root}")
        log("Selected conditions:")
        for cond in req.conditions:
            log(f" - {cond.name} ({len(cond.files)} files)")
        log(f"Harmonics: {', '.join([str(h) for h in req.settings.oddball_harmonics_hz])}")
        log(f"Z threshold: {req.settings.z_threshold}")
        log(f"BH-FDR enabled: {req.settings.use_bh_fdr}")
        log(f"FDR alpha: {req.settings.fdr_alpha}")
        log(f"SNR half window: {req.settings.half_window_hz}")
        log(
            "SNR y-limits: "
            f"{req.settings.snr_ymin_fixed} to {req.settings.snr_ymax_fixed}"
        )
        log(f"SNR mid xtick: {req.settings.snr_show_mid_xtick}")
        log(f"Grid columns: {req.settings.grid_ncols}")
        log(f"Letter portrait: {req.settings.use_letter_portrait}")
        log(f"Export PNG: {req.export_png}")
