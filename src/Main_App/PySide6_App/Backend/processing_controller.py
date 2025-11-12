""""Processing helpers for the PySide6 app. Single-preprocessor path (PySide6 only)."""
from __future__ import annotations

from pathlib import Path
import logging

from PySide6.QtWidgets import QFileDialog, QMessageBox

from Main_App.PySide6_App.Backend.loader import load_eeg_file
from Main_App.PySide6_App.Backend.preprocess import (
    perform_preprocessing,
    begin_preproc_audit,
    finalize_preproc_audit,
)
from Main_App.PySide6_App.Backend.processing import process_data
from Main_App.Legacy_App.post_process import post_process

logger = logging.getLogger(__name__)


def _animate_progress_to(self, value: int) -> None:
    """Non-blocking progress animation helper."""
    try:
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(value)
        self._progress_anim.start()
    except Exception:
        # Progress animation is best-effort; do not fail the run over UI niceties.
        pass


def _settings_get(self, section: str, key: str, default=None):
    try:
        return self.settings.get(section, key, default)
    except Exception:
        return default


def _promote_refs_to_eeg(self, raw, ref1: str, ref2: str, filename: str) -> None:
    """If legacy loader demoted EXG refs to misc, coerce them back to EEG before referencing."""
    promote = {}
    for ch in (ref1, ref2):
        if ch in raw.ch_names:
            try:
                ctype = raw.get_channel_types(picks=[ch])[0]
            except Exception:
                ctype = None
            if ctype != "eeg":
                promote[ch] = "eeg"
    if promote:
        raw.set_channel_types(promote)
        self.log(f"[PROMOTE] {list(promote)} → EEG before referencing for {filename}")


def start_processing(self) -> None:
    """
    Run the pipeline on one or more .bdf files using the PySide6 preprocessing module ONLY.
    Preserves the rest of the pipeline and adds structured audit logging.
    """
    try:
        input_dir = Path(self.currentProject.input_folder)
        run_loreta = bool(getattr(self, "cb_loreta", None) and self.cb_loreta.isChecked())

        # Gather input files
        if getattr(self, "rb_batch", None) and self.rb_batch.isChecked():
            bdf_files = sorted(input_dir.glob("*.bdf"))
            if not bdf_files:
                raise FileNotFoundError(f"No .bdf files in {input_dir}")
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select .BDF File", str(input_dir), "BDF Files (*.bdf)"
            )
            if not file_path:
                self.log("No file selected, aborting.")
                return
            bdf_files = [Path(file_path)]

        # Preprocessing parameters with precedence: project → settings → defaults
        p = self.currentProject.preprocessing or {}

        ref1 = (
            p.get("ref_channel1")
            or p.get("ref_chan1")
            or _settings_get(self, "preprocessing", "ref_channel1")
            or "EXG1"
        )
        ref2 = (
            p.get("ref_channel2")
            or p.get("ref_chan2")
            or _settings_get(self, "preprocessing", "ref_channel2")
            or "EXG2"
        )
        stim = p.get("stim_channel") or _settings_get(self, "stim", "channel", "Status") or "Status"

        params = {
            "downsample_rate": p.get("downsample"),
            "low_pass": p.get("low_pass"),
            "high_pass": p.get("high_pass"),
            "reject_thresh": p.get("rejection_z"),
            "ref_channel1": ref1,
            "ref_channel2": ref2,
            "max_idx_keep": p.get("max_chan_idx_keep"),
            "stim_channel": stim,
        }

        self.log(
            "Using PySide6 preprocessing: Main_App.PySide6_App.Backend.preprocess.perform_preprocessing"
        )
        logger.info(
            "Preproc route: PySide6 module with params=%s",
            {k: v for k, v in params.items() if k not in {"reject_thresh"}},
        )

        for fp in bdf_files:
            # Load
            self.log(f"Loading EEG file: {fp.name}")
            raw = load_eeg_file(self, str(fp))

            # Ensure reference channels are EEG before referencing
            _promote_refs_to_eeg(self, raw, ref1, ref2, fp.name)

            # Preprocess (single pass) with audit
            audit_before = begin_preproc_audit(raw, params, fp.name)
            processed_raw, n_bad = perform_preprocessing(raw, params, self.log, fp.name)
            raw = processed_raw or raw
            finalize_preproc_audit(
                audit_before,
                raw,
                params,
                fp.name,
                events_info=None,
                fif_written=0,
                n_rejected=int(n_bad or 0),
            )

            # Main processing and post-processing
            out_dir = str(self.currentProject.project_root / self.currentProject.subfolders["excel"])
            self.log(f"Running main processing (run_loreta={run_loreta})")
            process_data(raw, out_dir, run_loreta)

            condition_labels = list(self.currentProject.event_map.keys())
            self.log(f"Post-process condition labels: {condition_labels}")
            post_process(self, condition_labels)

        _animate_progress_to(self, 100)
        self.log("Processing complete")

    except Exception as e:
        self.log(f"Processing failed: {e}", level=logging.ERROR)
        try:
            QMessageBox.critical(self, "Processing Error", str(e))
        except Exception:
            pass
