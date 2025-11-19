""""Processing helpers for the PySide6 app. Single-preprocessor path (PySide6 only)."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence, TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from Main_App.PySide6_App.Backend.loader import load_eeg_file
from Main_App.PySide6_App.Backend.preprocess import (
    perform_preprocessing,
    begin_preproc_audit,
    finalize_preproc_audit,
)
from Main_App.PySide6_App.Backend.processing import process_data
from Main_App.Legacy_App.post_process import post_process

if TYPE_CHECKING:
    from Main_App.PySide6_App.Backend.project import Project

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawFileInfo:
    path: Path
    subject_id: str
    group: str | None = None


_PID_REGEX = re.compile(r"\b(P\d+|Sub\d+|S\d+)\b", re.IGNORECASE)
_PID_SUFFIX_REGEX = re.compile(
    r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica).*$",
    re.IGNORECASE,
)


def _infer_subject_id(file_path: Path) -> str:
    base = file_path.stem
    match = _PID_REGEX.search(base)
    if match:
        return match.group(1).upper()

    cleaned = _PID_SUFFIX_REGEX.sub("", base)
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned if cleaned else base


def _iter_group_folders(project: "Project") -> Iterable[tuple[str | None, Path]]:
    groups = getattr(project, "groups", {}) or {}
    if isinstance(groups, dict) and groups:
        for name, info in groups.items():
            folder = info.get("raw_input_folder") if isinstance(info, dict) else None
            if not folder:
                continue
            folder_path = Path(folder)
            yield name, folder_path
    else:
        yield None, Path(project.input_folder)


def discover_raw_files(project: "Project") -> List[RawFileInfo]:
    files: List[RawFileInfo] = []
    seen: set[Path] = set()
    for group_name, folder in _iter_group_folders(project):
        folder_path = Path(folder)
        if not folder_path.exists():
            logger.warning("Input folder %s for group %s does not exist", folder_path, group_name)
            continue
        for candidate in sorted(folder_path.glob("*.bdf")):
            file_path = candidate.resolve()
            if file_path in seen:
                continue
            seen.add(file_path)
            files.append(
                RawFileInfo(
                    path=file_path,
                    subject_id=_infer_subject_id(file_path),
                    group=group_name,
                )
            )
    return files


def _group_for_path(project: "Project", file_path: Path) -> str | None:
    file_resolved = file_path.resolve()
    for group_name, folder in _iter_group_folders(project):
        if not group_name:
            continue
        try:
            folder_resolved = Path(folder).resolve()
        except Exception:
            continue
        if folder_resolved == file_resolved.parent or folder_resolved in file_resolved.parents:
            return group_name
    return None


def _update_project_participants(project: "Project", files: Sequence[RawFileInfo]) -> None:
    if not files:
        return

    if not getattr(project, "groups", {}) or not isinstance(project.groups, dict):
        return

    participants: Dict[str, Dict[str, str]] = {}
    if isinstance(getattr(project, "participants", None), dict):
        participants = dict(project.participants)

    changed = False
    for info in files:
        group = info.group
        participant_id = info.subject_id.strip()
        if not group or not participant_id:
            continue
        existing = participants.get(participant_id)
        if existing and existing.get("group") and existing.get("group") != group:
            logger.warning(
                "Conflicting group assignments for participant %s (%s vs %s). Keeping existing.",
                participant_id,
                existing.get("group"),
                group,
            )
            continue
        if not existing or existing.get("group") != group:
            participants[participant_id] = {"group": group}
            changed = True

    if changed:
        project.participants = participants
        try:
            project.save()
        except Exception:
            logger.exception("Failed to save updated participant metadata for project %s", project.project_root)


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
        project: Project = self.currentProject
        input_dir = Path(project.input_folder)
        run_loreta = bool(getattr(self, "cb_loreta", None) and self.cb_loreta.isChecked())

        batch_mode = bool(getattr(self, "rb_batch", None) and self.rb_batch.isChecked())
        raw_file_infos: List[RawFileInfo]
        if batch_mode:
            raw_file_infos = discover_raw_files(project)
            if not raw_file_infos:
                raise FileNotFoundError(
                    "No .bdf files found in the configured input folders for this project."
                )
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select .BDF File", str(input_dir), "BDF Files (*.bdf)"
            )
            if not file_path:
                self.log("No file selected, aborting.")
                return
            selected_path = Path(file_path)
            raw_file_infos = [
                RawFileInfo(
                    path=selected_path,
                    subject_id=_infer_subject_id(selected_path),
                    group=_group_for_path(project, selected_path),
                )
            ]

        bdf_files = [info.path for info in raw_file_infos]
        _update_project_participants(project, raw_file_infos)

        # Preprocessing parameters with precedence: project → settings → defaults
        p = project.preprocessing or {}

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
