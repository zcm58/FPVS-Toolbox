"""Processing input workflow helpers for the Main App GUI shell."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
)

import config
from Main_App.Shared.file_filters import is_bdf_file
from Main_App.gui.manual_removed_electrodes_dialog import ManualRemovedElectrodesDialog
from Main_App.gui.participant_review import review_participants_for_processing
from Main_App.processing.processing_controller import (
    participant_review_rows,
    prepare_batch_file_infos,
    raw_file_info_for_path,
    register_participants,
)
from Main_App.projects.preprocessing_settings import (
    PREPROCESSING_CANONICAL_KEYS,
    normalize_preprocessing_settings,
)
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
    normalize_manual_removed_electrodes_map,
)
from Main_App.gui.project_workflows import (
    WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT,
    _illegal_condition_chars,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def validate_inputs(host: Any) -> bool:
    """Modern input validation + parameter collection."""
    if not getattr(host, "currentProject", None):
        QMessageBox.warning(host, "No Project", "Please open or create a project first.")
        return False

    # File selection rules differ in Single vs Batch
    mode_now = (host.file_mode.get() if hasattr(host, "file_mode") else "Batch")
    raw_file_infos = []
    if mode_now == "Single":
        # In single mode, require an explicit .bdf selection
        if not host.data_paths:
            QMessageBox.warning(host, "No File Selected", "Please choose one .bdf file first.")
            return False
        try:
            raw_file_infos = [
                raw_file_info_for_path(host.currentProject, Path(host.data_paths[0]))
            ]
        except Exception as exc:
            logger.exception("Single-file source validation failed.")
            QMessageBox.warning(host, "Invalid File Selection", str(exc))
            return False

    # Batch: always build the file list from the project definition
    # (multi-group aware via prepare_batch_files). This ensures that
    # all .bdf files from all configured group input folders are used.
    if mode_now == "Batch":
        try:
            raw_file_infos = prepare_batch_file_infos(host.currentProject)
        except Exception as exc:
            logger.exception("Batch raw-file discovery failed.")
            QMessageBox.critical(host, "Project Data Error", str(exc))
            return False
        if not raw_file_infos:
            QMessageBox.warning(
                host,
                "No Data",
                "No .bdf files found in the configured input folder(s).",
            )
            return False
        file_paths = [info.path for info in raw_file_infos]
        host.data_paths = [str(p) for p in file_paths]
        host.log(f"Processing: {len(host.data_paths)} file(s) selected.")

    # Single: if we somehow have no data_paths at this point, fall back to
    # the legacy input_folder glob (defensive-only; normal flow requires an
    # explicit file selection above).
    elif not host.data_paths:
        input_dir = Path(host.currentProject.input_folder)
        if not input_dir.is_dir():
            QMessageBox.critical(host, "Input Folder Missing", str(input_dir))
            return False
        bdf_files = sorted(str(p) for p in input_dir.glob("*.bdf") if is_bdf_file(p))
        if not bdf_files:
            QMessageBox.warning(
                host,
                "No Data",
                "No .bdf files found in the input folder.",
            )
            return False
        host.data_paths = bdf_files
        host.log(f"Processing: {len(host.data_paths)} file(s) selected.")

    # Save/output folder from project
    excel_sub = host.currentProject.subfolders.get("excel")
    if not excel_sub:
        QMessageBox.critical(host, "Project Error", "Excel subfolder not configured in project.json.")
        return False
    excel_dir = Path(host.currentProject.project_root) / excel_sub
    excel_dir.mkdir(parents=True, exist_ok=True)
    host.save_folder_path = SimpleNamespace(get=lambda: str(excel_dir))

    # Build params from project + settings + event-map UI
    params = host._build_validated_params()
    if params is None:
        return False
    host.validated_params = params

    review_rows = participant_review_rows(host.currentProject, raw_file_infos)
    if review_rows:
        if any("conflict" in row.status.casefold() for row in review_rows):
            QMessageBox.warning(
                host,
                "Participant Assignment Conflict",
                "One or more discovered files conflict with existing participant assignments. "
                "Move or rename the raw files, then try processing again.",
            )
            return False
        reviewer = getattr(host, "review_participants_for_processing", None)
        if not callable(reviewer):
            reviewer = review_participants_for_processing
        if not reviewer(host, review_rows):
            host.log("Participant review cancelled.")
            return False
        try:
            register_participants(host.currentProject, raw_file_infos)
        except Exception as exc:
            logger.exception("Failed to save participant review updates.")
            QMessageBox.critical(host, "Project Save Error", str(exc))
            return False
    if not _ensure_manual_removed_electrodes_reviewed(host, raw_file_infos, params):
        return False
    host._processing_raw_file_infos = list(raw_file_infos)

    debug_enabled = bool(host.settings.debug_enabled()) if hasattr(host, "settings") else False
    project_preproc = getattr(host.currentProject, "preprocessing", {}) or {}
    project_snapshot = {key: project_preproc.get(key) for key in PREPROCESSING_CANONICAL_KEYS}
    settings_snapshot = None
    if hasattr(host, "settings") and hasattr(host.settings, "config"):
        settings_snapshot = {}
        preproc_options = (
            "low_pass",
            "high_pass",
            "downsample",
            "epoch_start",
            "reject_thresh",
            "epoch_end",
            "ref_chan1",
            "ref_chan2",
            "max_idx_keep",
            "max_bad_chans",
            "auto_detect_removed_electrodes",
            "removed_electrode_detection_mode",
            "manual_removed_electrodes",
        )
        for opt in preproc_options:
            if host.settings.config.has_option("preprocessing", opt):
                settings_snapshot[opt] = host.settings.get("preprocessing", opt, "")
        if host.settings.config.has_option("stim", "channel"):
            settings_snapshot["stim_channel"] = host.settings.get("stim", "channel", "")
    dialog_snapshot = None
    if getattr(host, "_settings_dialog", None):
        try:
            dialog_preproc_keys = (
                "low_pass",
                "high_pass",
                "downsample",
                "epoch_start",
                "reject_thresh",
                "epoch_end",
                "ref_chan1",
                "ref_chan2",
                "max_idx_keep",
                "max_bad_chans",
                "auto_detect_removed_electrodes",
                "removed_electrode_detection_mode",
                "manual_removed_electrodes",
            )
            dialog_snapshot = {
                key: edit.text()
                for key, edit in zip(dialog_preproc_keys, host._settings_dialog.preproc_edits)
            }
        except Exception:
            dialog_snapshot = {"error": "unavailable"}
    if debug_enabled:
        logger.debug(
            "PREPROC_SOURCE_SNAPSHOT project=%s settings=%s dialog=%s",
            project_snapshot,
            settings_snapshot,
            dialog_snapshot,
        )
    else:
        logger.debug(
            "PREPROC_SOURCE_SNAPSHOT project_keys=%s settings_keys=%s dialog_present=%s",
            list(project_snapshot.keys()),
            list(settings_snapshot.keys()) if settings_snapshot else [],
            bool(dialog_snapshot),
        )
    fp_hp = params.get("high_pass")
    fp_lp = params.get("low_pass")
    fp_ds = params.get("downsample")
    fp_rz = params.get("reject_thresh")
    fp_r1 = params.get("ref_channel1")
    fp_r2 = params.get("ref_channel2")
    fp_stim = params.get("stim_channel")
    validated_fingerprint = (
        f"hp={fp_hp}|lp={fp_lp}|ds={fp_ds}|rz={fp_rz}|"
        f"ref={fp_r1},{fp_r2}|stim={fp_stim}"
    )
    logger.debug("PREPROC_FINGERPRINT_VALIDATED %s", validated_fingerprint)
    host._preproc_fingerprint_validated = validated_fingerprint

    # We show a concise summary (not noisy) so users see what's about to run
    lp = params.get("low_pass")
    hp = params.get("high_pass")
    ds = params.get("downsample")
    rz = params.get("reject_thresh")
    r1, r2 = params.get("ref_channel1"), params.get("ref_channel2")
    ep = (params.get("epoch_start"), params.get("epoch_end"))
    stim = params.get("stim_channel")
    host.log(
        f"Preproc params → HPF={hp if hp is not None else 'DC'}Hz, "
        f"LPF={lp if lp is not None else 'Nyq'}Hz, DS={ds}Hz, "
        f"Zreject={rz}, ref=({r1},{r2}), epoch=[{ep[0]}, {ep[1]}], stim='{stim}', "
        f"events={len(params.get('event_id_map', {}))}"
    )
    return True


def _ensure_manual_removed_electrodes_reviewed(
    host: Any,
    raw_file_infos: list[Any],
    params: dict[str, Any],
) -> bool:
    if params.get("removed_electrode_detection_mode") != REMOVED_ELECTRODE_DETECTION_MODE_MANUAL:
        return True
    if not raw_file_infos:
        return True

    manual_map = normalize_manual_removed_electrodes_map(
        params.get("manual_removed_electrodes")
    )
    reviewed = {pid.casefold() for pid in manual_map}
    missing = [
        str(info.subject_id).strip()
        for info in raw_file_infos
        if str(info.subject_id).strip()
        and str(info.subject_id).strip().casefold() not in reviewed
    ]
    if not missing:
        return True

    logger.info(
        "manual_removed_electrodes_review_required",
        extra={
            "project_root": str(getattr(host.currentProject, "project_root", "")),
            "missing_participant_ids": list(missing),
        },
    )
    dialog = ManualRemovedElectrodesDialog(
        [str(info.subject_id) for info in raw_file_infos],
        manual_map,
        host,
    )
    if dialog.exec() != QDialog.Accepted:
        host.log("Manual removed-electrode review cancelled.")
        return False

    updated_map = normalize_manual_removed_electrodes_map(
        dialog.manual_removed_electrodes()
    )
    updated_preproc = dict(getattr(host.currentProject, "preprocessing", {}) or {})
    updated_preproc["removed_electrode_detection_mode"] = (
        REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
    )
    updated_preproc["manual_removed_electrodes"] = updated_map
    try:
        normalized = host.currentProject.update_preprocessing(updated_preproc)
        host.currentProject.save()
    except ValueError as exc:
        QMessageBox.warning(host, "Invalid Manual Removed Electrodes", str(exc))
        return False
    except OSError as exc:
        logger.exception("Failed to save manual removed-electrode settings.")
        QMessageBox.critical(host, "Project Save Error", str(exc))
        return False

    params["manual_removed_electrodes"] = dict(
        normalized.get("manual_removed_electrodes") or {}
    )
    params["removed_electrode_detection_mode"] = normalized.get(
        "removed_electrode_detection_mode"
    )
    params["auto_detect_removed_electrodes"] = bool(
        normalized.get("auto_detect_removed_electrodes")
    )
    host.validated_params = params
    host.log("Manual removed-electrode list reviewed for current BDF pool.")
    return True


def build_validated_params(host: Any) -> dict | None:
    normalized = normalize_preprocessing_settings(host.currentProject.preprocessing)
    logger.debug(
        "NORMALIZED_PREPROC_SNAPSHOT file_mode=%s normalized.high_pass=%r "
        "normalized.low_pass=%r normalized.downsample=%r",
        getattr(host, "file_mode", None).get() if hasattr(host, "file_mode") else "UNKNOWN",
        normalized.get("high_pass"),
        normalized.get("low_pass"),
        normalized.get("downsample"),
    )

    # Event map from UI rows → {label: int_id}
    event_map: dict[str, int] = {}
    for row in host.event_rows:
        edits = row.findChildren(QLineEdit)
        if len(edits) >= 2:
            label_edit = edits[0]
            label = label_edit.text().strip()
            ident = edits[1].text().strip()
            if label:
                illegal_chars = _illegal_condition_chars(label)
                if illegal_chars:
                    bad = " ".join(illegal_chars)
                    QMessageBox.warning(
                        host,
                        "Invalid Condition Name",
                        (
                            "Condition names cannot contain characters that are invalid for "
                            "Windows file/folder names.\n\n"
                            f"Condition: {label}\n"
                            f"Illegal character(s): {bad}\n\n"
                            "Please rename this condition using only allowed characters.\n"
                            f"Not allowed: {WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT}"
                        ),
                    )
                    try:
                        label_edit.setFocus()
                        label_edit.selectAll()
                    except Exception:
                        pass
                    return None
            if label and ident.isdigit():
                event_map[label] = int(ident)
    if not event_map:
        QMessageBox.warning(host, "No Events", "Please add at least one event map entry.")
        return None

    epoch_start = float(normalized.get("epoch_start_s", -1.0))
    epoch_end = float(normalized.get("epoch_end_s", 125.0))
    if epoch_end <= epoch_start:
        QMessageBox.warning(
            host,
            "Invalid Epoch Window",
            "Epoch end must be greater than epoch start.",
        )
        return None

    stim_channel = normalized.get("stim_channel") or config.DEFAULT_STIM_CHANNEL
    try:
        base_freq = float(host.settings.get("analysis", "base_freq", "6.0"))
    except Exception:
        base_freq = 6.0
    try:
        oddball_freq = float(
            host.settings.get("analysis", "oddball_freq", str(config.DEFAULT_ODDBALL_FREQ))
        )
    except Exception:
        oddball_freq = float(config.DEFAULT_ODDBALL_FREQ)
    oddball_freq = config.validate_locked_oddball_frequency(oddball_freq)
    try:
        bca_upper_limit = float(
            host.settings.get(
                "analysis",
                "bca_upper_limit",
                str(config.DEFAULT_BCA_UPPER_LIMIT),
            )
        )
    except Exception:
        bca_upper_limit = float(config.DEFAULT_BCA_UPPER_LIMIT)

    params = {
        "low_pass": float(normalized.get("low_pass")),
        "high_pass": float(normalized.get("high_pass")),
        "downsample": int(normalized.get("downsample")),
        "downsample_rate": int(normalized.get("downsample")),
        "reject_thresh": float(normalized.get("rejection_z")),
        "ref_channel1": (normalized.get("ref_chan1") or None),
        "ref_channel2": (normalized.get("ref_chan2") or None),
        "max_idx_keep": int(normalized.get("max_chan_idx_keep")),
        "max_bad_channels_alert_thresh": int(normalized.get("max_bad_chans")),
        "auto_detect_removed_electrodes": bool(
            normalized.get("auto_detect_removed_electrodes")
        ),
        "removed_electrode_detection_mode": normalized.get(
            "removed_electrode_detection_mode"
        ),
        "manual_removed_electrodes": dict(
            normalized.get("manual_removed_electrodes") or {}
        ),
        "epoch_start": epoch_start,
        "epoch_end": epoch_end,
        "stim_channel": stim_channel,
        "save_preprocessed_fif": False,
        "event_id_map": event_map,
        "base_freq": base_freq,
        "oddball_freq": oddball_freq,
        "bca_upper_limit": bca_upper_limit,
        "analysis": {
            "base_freq": base_freq,
            "oddball_freq": oddball_freq,
            "bca_upper_limit": bca_upper_limit,
        },
    }
    logger.debug(
        "VALIDATED_PARAMS_SNAPSHOT high_pass=%r low_pass=%r downsample_rate=%r "
        "reject_thresh=%r ref=(%r,%r) stim=%r",
        params.get("high_pass"),
        params.get("low_pass"),
        params.get("downsample_rate"),
        params.get("reject_thresh"),
        params.get("ref_channel1"),
        params.get("ref_channel2"),
        params.get("stim_channel"),
    )
    return params


def on_mode_changed(host: Any, mode: str) -> None:
    """
    Adapter for UI radio buttons (wired in ui_main.py).
    Keeps legacy-compatible mode string and toggles any present selectors.
    """
    mode_norm = (mode or "").strip().lower()
    if mode_norm not in ("single", "batch"):
        host.log(f"Unknown mode '{mode}'; ignoring.", level=logging.WARNING)
        return

    # Maintain legacy-readable getter that some helpers expect
    pretty = "Single" if mode_norm == "single" else "Batch"
    host.file_mode = SimpleNamespace(get=lambda p=pretty: p)
    host.log(f"File mode changed to {pretty}")

    # Opportunistically toggle common widgets if they exist; no-ops otherwise
    def _safe_set_enabled(obj_name: str, enabled: bool) -> None:
        w = getattr(host, obj_name, None)
        if w and hasattr(w, "setEnabled"):
            try:
                w.setEnabled(enabled)
            except Exception:
                pass

    # Typical names used in our UI builder; harmless if missing
    is_single = (mode_norm == "single")

    host.parallel_mode = "single" if is_single else "process"

    _safe_set_enabled("btn_select_input_file", is_single)
    _safe_set_enabled("le_input_file", is_single)
    _safe_set_enabled("btn_select_input_folder", not is_single)
    _safe_set_enabled("le_input_folder", not is_single)

    # Toggle visibility of the single-file row, if present
    row = getattr(host, "row_single_file", None)
    if row and hasattr(row, "setVisible"):
        try:
            row.setVisible(is_single)
        except Exception:
            pass
    file_label = getattr(host, "lbl_single_file", None)
    if file_label and hasattr(file_label, "setVisible"):
        try:
            file_label.setVisible(is_single)
        except Exception:
            pass

    folder_row = getattr(host, "row_input_folder", None)
    if folder_row and hasattr(folder_row, "setVisible"):
        try:
            folder_row.setVisible(not is_single)
        except Exception:
            pass
    folder_label = getattr(host, "lbl_input_folder", None)
    if folder_label and hasattr(folder_label, "setVisible"):
        try:
            folder_label.setVisible(not is_single)
        except Exception:
            pass

    host._sync_input_folder_display()
    host.update_select_button_text()

    # Optional label feedback
    lbl = getattr(host, "lbl_mode", None)
    if isinstance(lbl, QLabel):
        try:
            lbl.setText(f"Mode: {pretty}")
        except Exception:
            pass

    host._update_start_enabled()


def set_controls_enabled(host: Any, enabled: bool) -> None:
    """
    Required by Main_App.Shared.processing_mixin.
    Disables common inputs while a run is active. No-ops if widgets missing.

    The main Start/Stop button is intentionally left enabled so the user can
    always request a stop.
    """
    host.busy = not enabled

    def _safe_enable(name: str) -> None:
        w = getattr(host, name, None)
        if w and hasattr(w, "setEnabled"):
            try:
                w.setEnabled(enabled)
            except Exception:
                host.log(f"_set_controls_enabled: could not toggle {name}", level=logging.DEBUG)

    # Common controls (exists-if-present).
    # NOTE: 'btn_start' is deliberately omitted.
    for n in (
            "btn_select_input_file", "le_input_file",
            "btn_select_input_folder", "le_input_folder",
            "btn_add_event", "btn_add_row",
            "btn_create_project", "btn_open_project",
    ):
        _safe_enable(n)

    # Event-map row edits/buttons (query per-type; Qt doesn't accept tuple here)
    for row in getattr(host, "event_rows", []):
        try:
            for child in row.findChildren(QLineEdit):
                child.setEnabled(enabled)
            for child in row.findChildren(QAbstractButton):
                child.setEnabled(enabled)
        except Exception:
            # Be quiet but safe
            host.log("_set_controls_enabled: child toggle failed", level=logging.DEBUG)


def update_start_enabled(host: Any) -> None:
    """Enable Start only when valid selection exists in Single mode."""
    btn = getattr(host, "btn_start", None)
    if not btn:
        return
    try:
        mode = host.file_mode.get()
    except Exception:
        mode = "Batch"
    if mode == "Single":
        txt = getattr(host, "le_input_file", None).text() if hasattr(host, "le_input_file") else ""
        ok = bool(txt) and Path(txt).suffix.lower() == ".bdf" and Path(txt).exists()
        btn.setEnabled(ok)
    else:
        btn.setEnabled(True)


def select_single_file(host: Any) -> None:
    """Windows-native file dialog to pick one .bdf under the project's input folder."""
    if not getattr(host, "currentProject", None):
        QMessageBox.warning(host, "No Project", "Please open or create a project first.")
        return
    start_dir = str(Path(host.currentProject.input_folder))
    fname, _ = QFileDialog.getOpenFileName(
        host,
        "Select EEG File (.bdf)",
        start_dir,
        "EEG BioSemi (*.bdf)",
    )
    if not fname:
        host.log("Single-file selection canceled.")
        host._update_start_enabled()
        return
    p = Path(fname)
    if p.suffix.lower() != ".bdf":
        QMessageBox.warning(host, "Invalid File", "Please select a .bdf file.")
        host._update_start_enabled()
        return
    try:
        info = raw_file_info_for_path(host.currentProject, p)
    except Exception as exc:
        QMessageBox.warning(
            host,
            "Outside Project",
            str(exc),
        )
        host._update_start_enabled()
        return
    # Accept
    if hasattr(host, "le_input_file"):
        host.le_input_file.setText(str(info.path))
    host._selected_bdf = str(info.path)
    host.data_paths = [str(info.path)]
    host.log(f"Single-file selected: {info.path.name}")
    host._update_start_enabled()
