"""Processing helpers for the Main App PySide6 runtime path."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Sequence

from PySide6.QtWidgets import QFileDialog, QMessageBox

from Main_App.Shared.file_filters import is_bdf_file
from Main_App.io.load_utils import load_eeg_file
from Main_App.processing.preprocess import (
    perform_preprocessing,
    begin_preproc_audit,
    finalize_preproc_audit,
)
from Main_App.processing.processing import process_data
from Main_App.Shared.post_process import post_process

if TYPE_CHECKING:
    from Main_App.projects.project import Project

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawFileInfo:
    """
    Metadata tracked for each discovered raw file.

    - path: absolute Path to the .bdf file.
    - subject_id: canonical participant label inferred from the file name.
    - group: optional experimental group_id, inferred from the folder
      where the file was discovered (for multi-group projects).
    """

    path: Path
    subject_id: str
    group: str | None = None


@dataclass(frozen=True)
class ParticipantReviewRow:
    """One participant manifest update that needs user review before processing."""

    participant_id: str
    group_id: str | None
    group_label: str
    raw_file: Path
    status: str


# ``subject_id`` is the canonical participant label inferred from the .bdf file
# name. ``group`` captures the multi-group group_id derived from the folder the
# file was found in. Both values are persisted so that downstream processing,
# participant manifests, and the Stats/Plot tools can reason about consistent
# IDs without re-scanning the filesystem.

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
    """
    Yield (group_id, folder_path) pairs for all configured input folders.

    For legacy/single-group projects, yields a single (None, project.input_folder)
    entry so callers can treat the iteration uniformly.
    """
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


def _is_within_path(parent: Path, child: Path) -> bool:
    try:
        parent_resolved = parent.resolve()
        child_resolved = child.resolve()
    except (OSError, RuntimeError):
        return False
    return parent_resolved == child_resolved or parent_resolved in child_resolved.parents


def _participant_record(
    project: "Project",
    subject_id: str,
) -> tuple[str | None, Mapping[str, Any] | None]:
    participants = getattr(project, "participants", {}) or {}
    if not isinstance(participants, Mapping):
        return None, None

    for candidate in (subject_id, subject_id.upper()):
        if candidate in participants:
            entry = participants[candidate]
            return candidate, entry if isinstance(entry, Mapping) else {}

    subject_key = subject_id.casefold()
    for raw_key, raw_entry in participants.items():
        if str(raw_key).casefold() == subject_key:
            return str(raw_key), raw_entry if isinstance(raw_entry, Mapping) else {}
    return None, None


def _participant_group_id(entry: Mapping[str, Any] | None) -> str | None:
    if not entry:
        return None
    group_value = entry.get("group_id")
    if group_value is None:
        group_value = entry.get("group")
    if group_value is None:
        return None
    group_id = str(group_value).strip()
    return group_id or None


def _participant_raw_file(project: "Project", entry: Mapping[str, Any] | None) -> Path | None:
    if not entry:
        return None
    raw_file_value = entry.get("raw_file")
    if not raw_file_value:
        return None
    raw_path = Path(raw_file_value)
    if raw_path.is_absolute():
        return raw_path
    return Path(getattr(project, "project_root", Path.cwd())) / raw_path


def _same_path(left: Path | None, right: Path) -> bool:
    if left is None:
        return False
    try:
        return left.resolve() == right.resolve()
    except (OSError, RuntimeError):
        return left == right


def _group_label(project: "Project", group_id: str | None) -> str:
    if not group_id:
        return "Single group"
    groups = getattr(project, "groups", {}) or {}
    if isinstance(groups, Mapping):
        entry = groups.get(group_id)
        if isinstance(entry, Mapping):
            label = str(entry.get("label") or entry.get("folder_name") or group_id).strip()
            if label:
                return label
    return group_id


def _warn_missing_known_raw_files(project: "Project") -> None:
    participants = getattr(project, "participants", {}) or {}
    if not isinstance(participants, Mapping):
        return
    for participant_id, raw_entry in participants.items():
        entry = raw_entry if isinstance(raw_entry, Mapping) else {}
        raw_file = _participant_raw_file(project, entry)
        if raw_file is None:
            continue
        try:
            raw_exists = raw_file.exists()
        except OSError:
            raw_exists = False
        if not raw_exists:
            logger.warning(
                "Known participant %s has a missing raw .bdf file at %s; "
                "leaving project.json unchanged and continuing with discovered files.",
                participant_id,
                raw_file,
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "participant_id": str(participant_id),
                    "raw_file": str(raw_file),
                },
            )


def _validate_locked_assignment(project: "Project", info: RawFileInfo) -> None:
    if not bool(getattr(project, "groups_locked", False)):
        return
    participant_key, existing = _participant_record(project, info.subject_id)
    if participant_key is None:
        return
    existing_group = _participant_group_id(existing)
    if existing_group and info.group and existing_group != info.group:
        raise ValueError(
            "Participant "
            f"{participant_key} is registered in group '{existing_group}' but "
            f"the selected raw file is in group '{info.group}'. Restore the "
            "registered raw folder layout or create a new project and reprocess."
        )


def raw_file_info_for_path(project: "Project", file_path: Path) -> RawFileInfo:
    selected_path = Path(file_path).resolve()
    if selected_path.suffix.lower() != ".bdf":
        raise ValueError(f"Selected file is not a .bdf file: {selected_path}")

    groups = getattr(project, "groups", {}) or {}
    group_id: str | None = None
    if isinstance(groups, Mapping) and groups:
        group_id = _group_for_path(project, selected_path)
        if not group_id:
            raise ValueError(
                "Selected .bdf file is outside the registered raw folders for "
                "this multi-group project."
            )
    else:
        input_folder = Path(project.input_folder)
        if not _is_within_path(input_folder, selected_path):
            raise ValueError(
                "Selected .bdf file is outside this project's registered input folder."
            )

    info = RawFileInfo(
        path=selected_path,
        subject_id=_infer_subject_id(selected_path),
        group=group_id,
    )
    _validate_locked_assignment(project, info)
    return info


def discover_raw_files(project: "Project") -> List[RawFileInfo]:
    """
    Discover all .bdf files across the project's configured input folders.

    For multi-group projects, this walks every group-specific folder. For
    legacy projects, this is equivalent to scanning project.input_folder.
    """
    files: List[RawFileInfo] = []
    seen_subjects: Dict[str, RawFileInfo] = {}
    groups_locked = bool(getattr(project, "groups_locked", False))
    for group_name, folder in _iter_group_folders(project):
        folder_path = Path(folder)
        if not folder_path.exists():
            if groups_locked:
                raise FileNotFoundError(
                    "Registered raw input folder is missing after group lock: "
                    f"{folder_path}. Restore the folder or create a new project."
                )
            logger.warning(
                "Input folder %s for group %s does not exist",
                folder_path,
                group_name,
            )
            continue
        for candidate in sorted(folder_path.glob("*.bdf")):
            if not is_bdf_file(candidate):
                continue
            file_path = candidate.resolve()
            info = RawFileInfo(
                path=file_path,
                subject_id=_infer_subject_id(file_path),
                group=group_name,
            )
            subject_key = info.subject_id.casefold()
            if subject_key in seen_subjects:
                previous = seen_subjects[subject_key]
                raise ValueError(
                    "Duplicate participant ID detected: "
                    f"{info.subject_id}. Files '{previous.path}' and "
                    f"'{info.path}' infer the same participant ID. A project "
                    "cannot process more than one .bdf per participant in v2.1."
                )
            _validate_locked_assignment(project, info)
            seen_subjects[subject_key] = info
            files.append(info)
    if groups_locked:
        _warn_missing_known_raw_files(project)
    logger.info(
        "discover_raw_files",
        extra={
            "project_root": str(getattr(project, "project_root", "")),
            "n_files": len(files),
            "groups": list({f.group for f in files}),
        },
    )
    return files


def _group_for_path(project: "Project", file_path: Path) -> str | None:
    """
    Infer the group name for a manually selected file based on its parent folder.
    """
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


def participant_review_rows(
    project: "Project",
    files: Sequence[RawFileInfo],
) -> list[ParticipantReviewRow]:
    rows: list[ParticipantReviewRow] = []
    for info in files:
        participant_id = info.subject_id.strip()
        if not participant_id:
            continue
        _participant_key, existing = _participant_record(project, participant_id)
        existing_group = _participant_group_id(existing)
        existing_raw_file = _participant_raw_file(project, existing)
        if existing is None:
            status = "New participant"
        elif info.group and existing_group != info.group:
            status = "Group assignment conflict"
        elif not _same_path(existing_raw_file, info.path):
            status = "Update raw file path"
        else:
            continue
        rows.append(
            ParticipantReviewRow(
                participant_id=participant_id,
                group_id=info.group,
                group_label=_group_label(project, info.group),
                raw_file=info.path,
                status=status,
            )
        )
    return rows


def _update_project_participants(project: "Project", files: Sequence[RawFileInfo]) -> bool:
    """
    Merge subject→group assignments from the given files into project.participants.

    Conflicting assignments for the same subject are logged and the existing
    mapping is preserved.
    """
    if not files:
        return False

    participants: Dict[str, Dict[str, Any]] = {}
    if isinstance(getattr(project, "participants", None), dict):
        participants = dict(project.participants)

    changed = False
    for info in files:
        group = info.group
        participant_id = info.subject_id.strip()
        if not participant_id:
            continue
        existing_key, existing = _participant_record(project, participant_id)
        participant_key = existing_key or participant_id
        existing_group = _participant_group_id(existing)
        if group and existing_group and existing_group != group:
            logger.warning(
                "Conflicting group assignments for participant %s (%s vs %s). "
                "Keeping existing.",
                participant_key,
                existing_group,
                group,
            )
            continue
        existing_entry = dict(existing or {})
        existing_entry.pop("group", None)
        updated_entry = dict(existing_entry)
        if group:
            updated_entry["group_id"] = group
        elif not getattr(project, "groups", {}) and "group_id" in updated_entry:
            updated_entry.pop("group_id", None)
        updated_entry["raw_file"] = info.path
        if updated_entry != existing_entry:
            participants[participant_key] = updated_entry
            changed = True

    if changed:
        logger.info(
            "participants_updated",
            extra={
                "project_root": str(getattr(project, "project_root", "")),
                "n_participants": len(participants),
            },
        )
        project.participants = participants
        project.save()
    return changed


def register_participants(project: "Project", files: Sequence[RawFileInfo]) -> bool:
    """Persist reviewed participant raw-file assignments to project.json."""
    return _update_project_participants(project, files)


def prepare_batch_file_infos(project: "Project") -> List[RawFileInfo]:
    """
    Build the raw-file metadata list for batch processing without mutating project.json.

    - For multi-group projects (project.groups non-empty), this uses
      discover_raw_files(project) so that all configured group folders
      contribute their .bdf files.

    - For single-group projects, this scans
      project.input_folder directly, preserving the original behavior.

    This is the single source-of-truth used by the PySide6 GUI when
    constructing the data_files list for the performance runner.
    """
    infos = discover_raw_files(project)
    groups = getattr(project, "groups", {}) or {}
    if isinstance(groups, dict) and groups:
        logger.info(
            "prepare_batch_files_multi_group",
            extra={
                "project_root": str(getattr(project, "project_root", "")),
                "n_files": len(infos),
            },
        )
    else:
        logger.info(
            "prepare_batch_files_single_group",
            extra={
                "project_root": str(getattr(project, "project_root", "")),
                "input_folder": str(getattr(project, "input_folder", "")),
                "n_files": len(infos),
            },
        )
    return infos


def prepare_batch_files(project: "Project") -> List[Path]:
    """Build the list of .bdf files for batch processing."""
    return [info.path for info in prepare_batch_file_infos(project)]


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
        try:
            logger.debug(
                "promote_refs_to_eeg",
                extra={"file": filename, "promoted": list(promote)},
            )
        except Exception:
            logger.debug("promote_refs_to_eeg_logging_failed", extra={"file": filename})


def start_processing(self) -> None:
    """
    Run the pipeline on one or more .bdf files using the active preprocessing owner.
    Preserves the rest of the pipeline and adds structured audit logging.
    """
    try:
        project: Project = self.currentProject
        input_dir = Path(project.input_folder)

        batch_mode = bool(getattr(self, "rb_batch", None) and self.rb_batch.isChecked())

        try:
            logger.info(
                "start_processing_begin",
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "input_folder": str(input_dir),
                    "batch_mode": batch_mode,
                },
            )
        except Exception:
            logger.debug(
                "start_processing_begin_logging_failed",
                extra={"input_folder": str(input_dir)},
            )

        raw_file_infos: List[RawFileInfo]
        if batch_mode:
            raw_file_infos = discover_raw_files(project)
            if not raw_file_infos:
                raise FileNotFoundError(
                    "No .bdf files found in the configured input folders for this project."
                )
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select .BDF File",
                str(input_dir),
                "BDF Files (*.bdf)",
            )
            if not file_path:
                self.log("No file selected, aborting.")
                logger.info(
                    "start_processing_no_file_selected",
                    extra={"input_folder": str(input_dir)},
                )
                return
            selected_path = Path(file_path)
            raw_file_infos = [raw_file_info_for_path(project, selected_path)]

        bdf_files = [info.path for info in raw_file_infos]

        try:
            logger.info(
                "start_processing_file_list",
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "n_files": len(bdf_files),
                    "files": [str(p) for p in bdf_files],
                },
            )
        except Exception:
            logger.debug(
                "start_processing_file_list_logging_failed",
                extra={"n_files": len(bdf_files)},
            )

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
        stim = (
            p.get("stim_channel")
            or _settings_get(self, "stim", "channel", "Status")
            or "Status"
        )

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
            "Using Main App preprocessing: "
            "Main_App.processing.preprocess.perform_preprocessing"
        )
        logger.info(
            "Preproc route: Main_App.processing.preprocess with params=%s",
            {k: v for k, v in params.items() if k not in {"reject_thresh"}},
        )

        for fp in bdf_files:
            try:
                logger.info(
                    "start_processing_file_begin",
                    extra={
                        "file": str(fp),
                        "project_root": str(getattr(project, "project_root", "")),
                    },
                )
            except Exception:
                logger.debug(
                    "start_processing_file_begin_logging_failed",
                    extra={"file": str(fp)},
                )

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

            try:
                logger.info(
                    "start_processing_file_preproc_done",
                    extra={
                        "file": str(fp),
                        "n_bad_kurtosis": int(n_bad or 0),
                        "n_channels": len(getattr(raw.info, "ch_names", [])),
                        "sfreq": float(raw.info.get("sfreq", -1.0)),
                    },
                )
            except Exception:
                logger.debug(
                    "start_processing_file_preproc_done_logging_failed",
                    extra={"file": str(fp)},
                )

            # Main processing and post-processing
            out_dir = str(
                self.currentProject.project_root
                / self.currentProject.subfolders["excel"]
            )
            self.log("Running main processing")
            logger.debug(
                "start_processing_call_process_data",
                extra={"file": str(fp), "out_dir": out_dir},
            )
            process_data(raw, out_dir)

            condition_labels = list(self.currentProject.event_map.keys())
            self.log(f"Post-process condition labels: {condition_labels}")
            logger.debug(
                "start_processing_call_post_process",
                extra={"file": str(fp), "condition_labels": condition_labels},
            )
            post_process(self, condition_labels)

            try:
                logger.info(
                    "start_processing_file_done",
                    extra={
                        "file": str(fp),
                        "n_condition_labels": len(condition_labels),
                    },
                )
            except Exception:
                logger.debug(
                    "start_processing_file_done_logging_failed",
                    extra={"file": str(fp)},
                )

        _animate_progress_to(self, 100)
        self.log("Processing complete")
        try:
            logger.info(
                "start_processing_complete",
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "n_files": len(bdf_files),
                },
            )
        except Exception:
            logger.debug(
                "start_processing_complete_logging_failed",
                extra={"n_files": len(bdf_files)},
            )

    except Exception as e:
        self.log(f"Processing failed: {e}", level=logging.ERROR)
        try:
            logger.exception(
                "start_processing_failed",
                extra={
                    "project_root": str(
                        getattr(getattr(self, "currentProject", None), "project_root", "")
                    ),
                },
            )
        except Exception:
            logger.debug("start_processing_failed_logging_failed")
        try:
            QMessageBox.critical(self, "Processing Error", str(e))
        except Exception:
            # If the GUI is in a bad state, we still want the log message.
            pass
