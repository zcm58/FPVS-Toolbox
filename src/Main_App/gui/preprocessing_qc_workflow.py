"""This module handles the data quality check that occurs prior to data processing. ."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from PySide6.QtCore import QEventLoop, QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
)

from Main_App.gui.components import ActionRow, make_action_button
from Main_App.gui.open_paths import open_path_in_file_manager
from Main_App.gui.signal_review_model import (
    SignalReviewItem, episode_view_context, review_time_scope,
)
from Main_App.gui.signal_review_panel import SignalReviewPanel
from Main_App.gui.marker_occurrence_review import (
    MARKER_DECISION_EXCLUDE,
    MARKER_DECISION_RETAIN_FULL,
    MARKER_DECISION_USE_CONTIGUOUS,
    MarkerOccurrenceReviewError,
    MarkerOccurrenceReviewItem,
    build_marker_review_decision,
    canonical_event_plans_by_file,
    collect_marker_occurrence_reviews,
    marker_occurrence_review_rows,
    merge_marker_review_decision,
    merge_rescanned_results,
    resolved_path_text,
)
from Main_App.gui.kurtosis_review_dialog import (
    KurtosisReviewDialog,
    KurtosisReviewDialogError,
)
from Main_App.gui.recording_qc_identity import (
    participant_sort_key,
    project_recording_coverage_rows,
)
from Main_App.io.load_utils import format_bdf_recording_not_started_message
from Main_App.processing.qc_summary_export import QUALITY_CHECK_FOLDER
from Main_App.processing.full_fft_grid_qc import audit_project_full_fft_grids
from Main_App.processing.preflight_qc import (
    HeaderOnlyPreflight,
    PreflightConditionCropGridAudit,
    PreflightConditionCropObservation,
    PreflightQcFileResult,
    PreflightQcScan,
    build_preflight_condition_crop_grid_audit,
    scan_preprocessing_qc,
    scan_recording_not_started_files,
)
from Main_App.processing.preflight_qc_plan import PREFLIGHT_QC_MAX_WORKERS
from Main_App.processing.qc_source_prefetch import QcSourcePrefetch
from Main_App.processing.kurtosis_review_scan import (
    KurtosisReviewScan,
    reconcile_kurtosis_review_decisions,
    scan_kurtosis_review,
)
from Main_App.processing.raw_channel_qc import (
    BIOSEMI_SHARED_NOISE_HELP_URL,
    SEVERE_RAW_AMPLITUDE_HELP_TEXT,
)
from Main_App.processing.frequency_domain_qc import (
    mark_frequency_domain_outputs_stale,
)
from Main_App.processing.removed_electrode_detection import (
    build_removed_electrode_review_record,
    normalize_manual_removed_electrodes_map,
    parse_electrode_list,
)
from Main_App.projects.grouping import project_group_context
from Main_App.workers.qc_source_prefetch_worker import QcSourcePrefetchWorker
from Main_App.projects.preprocessing_settings import (
    KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recording_conditions,
    normalize_manual_excluded_recordings,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_DATA_QUALITY_CHECK_TITLE = "Data Quality Check"
_DATA_QUALITY_SCAN_WAIT_MESSAGE = (
    "FPVS Toolbox is checking the configured condition intervals in your data. "
    "Large recordings can take several minutes; completed participants are reused "
    "if the check is restarted."
)
_DATA_QUALITY_REVIEW_FLAGS_FILENAME = "Data_Quality_Check_Review_Flags.xlsx"
_REMOVED_REVIEW_HEADERS = (
    "PID",
    "Group",
    "FPVS Toolbox flagged",
    "Why flagged",
    "Manual additions",
    "Final confirmed removed electrodes",
)
_REMOVED_REVIEW_PID_COLUMN = 0
_REMOVED_REVIEW_AUTO_COLUMN = 2
_REMOVED_REVIEW_REASON_COLUMN = 3
_REMOVED_REVIEW_MANUAL_COLUMN = 4
_REMOVED_REVIEW_FINAL_COLUMN = 5
_HARD_EXCLUSION_PID_COLUMN = 0
_HARD_EXCLUSION_REASON_COLUMN = 3
_HARD_EXCLUSION_DECISION_COLUMN = 4
_HARD_EXCLUSION_DETAILS_COLUMN = 5
_HARD_EXCLUSION_DECISION_UNSELECTED = "unselected"
_HARD_EXCLUSION_DECISION_KEEP = "keep"
_HARD_EXCLUSION_DECISION_EXCLUDE = "exclude"
_HARD_EXCLUSION_DETAILS_ATTR = "_preflight_hard_exclusion_details_by_pid"
_PREFLIGHT_TABLE_CLICK_HANDLER_ATTR = "_preflight_table_item_clicked_handler"
_CONDITION_EXCLUSION_CHECK_COLUMN = 6
_DATA_QUALITY_STEP_TOTAL = 7
_SCAN_SIGNAL_HEALTH_STEP = 1
_REVIEW_MARKER_OCCURRENCES_STEP = 2
_CONFIRM_CONDITION_EXCLUSIONS_STEP = 3
_CONFIRM_REMOVED_ELECTRODES_STEP = 4
_CONFIRM_PARTICIPANT_EXCLUSIONS_STEP = 5
_REVIEW_KURTOSIS_STEP = 6
_REVIEW_OTHER_FLAGS_STEP = 7


class _PreflightQcWorker(QObject):
    progress = Signal(str, int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        raw_file_infos: Sequence[Any],
        settings: dict[str, Any],
        skip_paths: Sequence[Path],
        max_workers: int,
        project_root: Path | None = None,
        event_map: Mapping[str, int] | None = None,
    ) -> None:
        super().__init__()
        self._raw_file_infos = list(raw_file_infos)
        self._settings = dict(settings)
        self._skip_paths = [Path(path) for path in skip_paths]
        self._max_workers = max(1, int(max_workers))
        self._project_root = Path(project_root) if project_root is not None else None
        self._event_map = dict(event_map or {})
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            scan = scan_preprocessing_qc(
                self._raw_file_infos,
                self._settings,
                skip_paths=self._skip_paths,
                max_workers=self._max_workers,
                progress=self.progress.emit,
                should_cancel=lambda: self._cancelled,
                project_root=self._project_root,
                event_map=self._event_map,
            )
            if self._project_root is not None and not self._cancelled:
                project_grid_audit = audit_project_full_fft_grids(
                    self._project_root
                )
                event_ids = {
                    str(label).strip().casefold(): int(condition_id)
                    for label, condition_id in self._event_map.items()
                    if str(label).strip()
                }
                scan = replace(
                    scan,
                    project_grid_observations=tuple(
                        PreflightConditionCropObservation(
                            path=observation.path,
                            participant_id=observation.participant_id,
                            group_id=observation.group_id,
                            condition_label=observation.condition,
                            condition_id=event_ids.get(
                                observation.condition.casefold(),
                                -1,
                            ),
                            repetition_count=0,
                            oddball_cycles=observation.oddball_cycles,
                            duration_s=observation.duration_s,
                            issue=observation.issue,
                            already_excluded=observation.already_excluded,
                            recording_id=observation.recording_id,
                            session_id=observation.session_id,
                            session_label=observation.session_label,
                            visit_index=observation.visit_index,
                        )
                        for observation in project_grid_audit.observations
                    ),
                )
        except Exception as exc:  # pragma: no cover - defensive signal bridge
            logger.exception("Preprocessing QC scan failed.")
            self.failed.emit(str(exc))
            return
        self.finished.emit(scan)


class _KurtosisReviewWorker(QObject):
    """Prepare QC-16 evidence outside the GUI thread."""

    progress = Signal(str, int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        raw_file_infos: Sequence[Any],
        settings: Mapping[str, Any],
        *,
        event_map: Mapping[str, int],
        reviewed_event_plans_by_file: Mapping[str, Any],
        raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]],
        source_prefetch: QcSourcePrefetch | None = None,
    ) -> None:
        super().__init__()
        self._raw_file_infos = list(raw_file_infos)
        self._settings = dict(settings)
        self._source_prefetch = source_prefetch
        self._event_map = dict(event_map)
        self._reviewed_event_plans_by_file = dict(reviewed_event_plans_by_file)
        self._raw_channel_qc_by_recording = {
            str(recording_id): dict(payload)
            for recording_id, payload in raw_channel_qc_by_recording.items()
        }
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            scan = scan_kurtosis_review(
                self._raw_file_infos,
                self._settings,
                event_map=self._event_map,
                reviewed_event_plans_by_file=self._reviewed_event_plans_by_file,
                raw_channel_qc_by_recording=self._raw_channel_qc_by_recording,
                progress=self.progress.emit,
                should_cancel=lambda: self._cancelled,
                source_prefetch=self._source_prefetch,
            )
        except Exception as exc:  # pragma: no cover - defensive signal bridge
            logger.exception("Kurtosis review scan failed.")
            self.failed.emit(str(exc))
            return
        self.finished.emit(scan)


def _project_group_labels(host: Any) -> dict[str, str]:
    project = getattr(host, "currentProject", None)
    if project is None:
        raise RuntimeError("Preprocessing QC requires an active project.")
    context = project_group_context(project)
    return {group.group_id: group.label for group in context.groups}


def _group_display_name(
    group_id: object,
    group_labels: Mapping[str, str],
) -> str:
    normalized = str(group_id or "").strip()
    if not normalized:
        if group_labels:
            raise RuntimeError(
                "Multi-group preprocessing QC received a file without a group_id."
            )
        return "Single group"
    if normalized not in group_labels:
        raise RuntimeError(
            f"Preprocessing QC received unknown project group_id '{normalized}'."
        )
    return str(group_labels[normalized])


def _participant_group_display_map(
    raw_file_infos: Sequence[Any],
    group_labels: Mapping[str, str],
) -> dict[str, str]:
    groups: dict[str, str] = {}
    for info in raw_file_infos:
        participant_id = str(info.subject_id).strip()
        if not participant_id:
            continue
        groups[participant_id] = _group_display_name(
            getattr(info, "group", None),
            group_labels,
        )
    return groups


def _result_group_display_name(
    result: HeaderOnlyPreflight | PreflightQcFileResult,
    group_labels: Mapping[str, str],
) -> str:
    return _group_display_name(result.group_id, group_labels)


def _recording_aware(values: Sequence[Any]) -> bool:
    """Return whether rows carry canonical v2.2 recording identities."""

    return any(
        str(getattr(value, "recording_id", "") or "").strip()
        for value in values
    )


def _identity_id(value: Any) -> str:
    """Use recording identity for v2.2 and the exact participant fallback."""

    return str(
        getattr(value, "recording_id", None)
        or getattr(value, "participant_id", None)
        or getattr(value, "subject_id", "")
    ).strip()


def _session_label(value: Any) -> str:
    return str(
        getattr(value, "session_label", None)
        or getattr(value, "session_id", None)
        or "—"
    )


def _visit_label(value: Any) -> str:
    visit_index = getattr(value, "visit_index", None)
    return str(visit_index) if visit_index is not None else "—"


def _merge_removed_maps(
    existing: dict[str, list[str]],
    suggestions: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = normalize_manual_removed_electrodes_map(existing)
    for pid, electrodes in suggestions.items():
        current = merged.get(pid, [])
        seen = {electrode.casefold() for electrode in current}
        for electrode in electrodes:
            if electrode.casefold() in seen:
                continue
            current.append(electrode)
            seen.add(electrode.casefold())
        merged[pid] = current
    return dict(sorted(merged.items(), key=lambda item: participant_sort_key(item[0])))


def _filter_removed_map_for_participants(
    values: dict[str, list[str]],
    participant_ids: Sequence[str],
) -> dict[str, list[str]]:
    keys = {participant_id.casefold() for participant_id in participant_ids}
    return {
        pid: list(electrodes)
        for pid, electrodes in values.items()
        if pid.casefold() in keys
    }


def _replace_removed_map_for_participants(
    existing: dict[str, list[str]],
    replacements: dict[str, list[str]],
    participant_ids: Sequence[str],
) -> dict[str, list[str]]:
    keys = {participant_id.casefold() for participant_id in participant_ids}
    merged = {
        pid: list(electrodes)
        for pid, electrodes in existing.items()
        if pid.casefold() not in keys
    }
    for pid, electrodes in replacements.items():
        if pid.casefold() in keys:
            merged[pid] = list(electrodes)
    return dict(sorted(merged.items(), key=lambda item: participant_sort_key(item[0])))


def _settings_with_reviewed_manual_removed_electrodes(
    preprocessing: Mapping[str, Any] | None,
    *,
    participant_map: Mapping[str, Sequence[str]],
    recording_map: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Activate reviewed manual maps without changing the detector mode."""

    updated = dict(preprocessing or {})
    updated[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] = True
    updated["manual_removed_electrodes"] = {
        str(identity): list(electrodes)
        for identity, electrodes in participant_map.items()
    }
    if recording_map is not None:
        updated["manual_removed_electrodes_by_recording"] = {
            str(identity): list(electrodes)
            for identity, electrodes in recording_map.items()
        }
    return updated


def _unique_channels(*values: Sequence[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in values:
        for channel in parse_electrode_list(source):
            key = channel.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(channel)
    return merged


def _map_lookup(values: Mapping[str, Sequence[str]], participant_id: str) -> list[str]:
    if participant_id in values:
        return list(values[participant_id])
    key = participant_id.casefold()
    for candidate, electrodes in values.items():
        if candidate.casefold() == key:
            return list(electrodes)
    return []


def _removed_review_row_values(
    participant_ids: Sequence[str],
    auto_flagged: Mapping[str, Sequence[str]],
    existing_manual: Mapping[str, Sequence[str]],
    participant_groups: Mapping[str, str],
    flag_reasons: Mapping[str, str] | None = None,
) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    seen_pids: set[str] = set()
    all_pids: list[str] = []
    for source_pid in (
        *participant_ids,
        *tuple(auto_flagged),
        *tuple(existing_manual),
    ):
        pid = str(source_pid).strip()
        if not pid:
            continue
        key = pid.casefold()
        if key in seen_pids:
            continue
        seen_pids.add(key)
        all_pids.append(pid)
    all_pids.sort(key=participant_sort_key)

    for pid in all_pids:
        auto_values = parse_electrode_list(_map_lookup(auto_flagged, pid))
        existing_values = parse_electrode_list(_map_lookup(existing_manual, pid))
        auto_lookup = {channel.casefold() for channel in auto_values}
        manual_additions = [
            channel
            for channel in existing_values
            if channel.casefold() not in auto_lookup
        ]
        final_confirmed = _unique_channels(auto_values, manual_additions)
        reason = _string_map_lookup(flag_reasons or {}, pid)
        if not reason and existing_values:
            reason = "Existing manual list"
        group = _string_map_lookup(participant_groups, pid)
        if not group:
            raise RuntimeError(
                f"Preprocessing QC could not resolve group membership for '{pid}'."
            )
        rows.append(
            (
                pid,
                group,
                ", ".join(auto_values),
                reason,
                ", ".join(manual_additions),
                ", ".join(final_confirmed),
            )
        )
    return rows


def _string_map_lookup(values: Mapping[str, str], participant_id: str) -> str:
    if participant_id in values:
        return str(values[participant_id]).strip()
    key = participant_id.casefold()
    for candidate, value in values.items():
        if candidate.casefold() == key:
            return str(value).strip()
    return ""


def _removed_review_reason_map(scan: PreflightQcScan) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for result in scan.results:
        fragments: list[str] = []
        if result.auto_removed_electrodes:
            fragments.append(
                "Low signal / flat candidate(s): "
                + ", ".join(result.auto_removed_electrodes)
            )
        if fragments:
            reasons[result.identity_id] = "; ".join(fragments)
    return reasons


def _normalize_removed_review_entry(
    *,
    original_auto: Sequence[str],
    accepted_auto_text: str,
    manual_additions_text: str,
) -> tuple[dict[str, object], list[str], list[str]]:
    original = parse_electrode_list(original_auto)
    original_lookup = {channel.casefold(): channel for channel in original}
    accepted_raw = parse_electrode_list(accepted_auto_text)
    manual_raw = parse_electrode_list(manual_additions_text)

    accepted_auto: list[str] = []
    moved_to_manual: list[str] = []
    for channel in accepted_raw:
        original_label = original_lookup.get(channel.casefold())
        if original_label is None:
            moved_to_manual.append(channel)
            continue
        accepted_auto.append(original_label)

    moved_to_auto: list[str] = []
    manual_additions: list[str] = []
    accepted_lookup = {channel.casefold() for channel in accepted_auto}
    for channel in manual_raw:
        original_label = original_lookup.get(channel.casefold())
        if original_label is not None:
            if original_label.casefold() not in accepted_lookup:
                accepted_auto.append(original_label)
                accepted_lookup.add(original_label.casefold())
            moved_to_auto.append(original_label)
            continue
        manual_additions.append(channel)

    manual_additions = _unique_channels(manual_additions, moved_to_manual)
    record = build_removed_electrode_review_record(
        original_auto_flagged=original,
        accepted_auto_flagged=accepted_auto,
        manual_additions=manual_additions,
    )
    return record, moved_to_manual, moved_to_auto


def _removed_review_records_from_rows(
    rows: Sequence[Sequence[str]],
    auto_flagged: Mapping[str, Sequence[str]],
) -> tuple[dict[str, dict[str, object]], dict[str, list[str]], list[str]]:
    records: dict[str, dict[str, object]] = {}
    final_confirmed: dict[str, list[str]] = {}
    warnings: list[str] = []
    for row_values in rows:
        if len(row_values) < 3:
            continue
        pid = str(row_values[0]).strip()
        if not pid:
            continue
        manual_index = 3 if len(row_values) >= 5 else 2
        record, moved_to_manual, moved_to_auto = _normalize_removed_review_entry(
            original_auto=_map_lookup(auto_flagged, pid),
            accepted_auto_text=str(row_values[1]),
            manual_additions_text=str(row_values[manual_index]),
        )
        records[pid] = record
        final_confirmed[pid] = list(record["final_confirmed_removed"])  # type: ignore[index]
        if moved_to_manual:
            warnings.append(
                f"{pid}: moved to Manual additions: {', '.join(moved_to_manual)}"
            )
        if moved_to_auto:
            warnings.append(
                f"{pid}: treated original FPVS flag(s) as accepted: "
                f"{', '.join(moved_to_auto)}"
            )
    return records, final_confirmed, warnings


def _casefold_electrode_lookup(
    values: dict[str, list[str]],
    participant_id: str,
) -> list[str]:
    if participant_id in values:
        return list(values[participant_id])
    key = participant_id.casefold()
    for candidate, electrodes in values.items():
        if candidate.casefold() == key:
            return list(electrodes)
    return []


def _path_strings(items: Sequence[HeaderOnlyPreflight]) -> list[str]:
    return [str(item.path.resolve()) for item in items]


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except (OSError, RuntimeError, ValueError):
        return str(path).casefold()


def _scan_progress_text(message: str | None = None) -> str:
    detail = (message or "").strip()
    if detail:
        return f"{_DATA_QUALITY_SCAN_WAIT_MESSAGE}\n\n{detail}"
    return _DATA_QUALITY_SCAN_WAIT_MESSAGE


def _show_data_quality_notice(
    host: Any,
    heading: str,
    message: str,
    *,
    details: str = "",
) -> None:
    box = QMessageBox(host)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(_DATA_QUALITY_CHECK_TITLE)
    box.setText(heading)
    box.setInformativeText(message)
    if details:
        box.setDetailedText(details)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()


def _set_label(host: Any, attr_name: str, text: str) -> None:
    label = getattr(host, attr_name, None)
    if label is not None:
        label.setText(text)


def _set_amplitude_help_label(host: Any, attr_name: str, prefix: str = "") -> None:
    """Show the brief amplitude explanation and opt-in external help link."""

    label = getattr(host, attr_name, None)
    if label is None:
        return
    lead = f"{prefix.strip()} " if prefix.strip() else ""
    label.setText(
        lead
        + SEVERE_RAW_AMPLITUDE_HELP_TEXT
        + f' <a href="{BIOSEMI_SHARED_NOISE_HELP_URL}">'
        "BioSemi: referencing and shared noise</a>"
    )
    if hasattr(label, "setTextFormat"):
        label.setTextFormat(Qt.RichText)
    if hasattr(label, "setOpenExternalLinks"):
        label.setOpenExternalLinks(True)


def _set_progress(host: Any, completed: int, total: int) -> None:
    bar = getattr(host, "progress_bar", None)
    if bar is None:
        return
    pct = 0 if total <= 0 else round(max(0, completed) / max(1, total) * 100)
    bar.setRange(0, 100)
    bar.setValue(max(0, min(100, pct)))
    bar.setFormat("%p%")


def _set_spinner_running(host: Any, running: bool) -> None:
    spinner = getattr(host, "processing_spinner", None)
    if spinner is None:
        return
    if running:
        spinner.start()
    else:
        spinner.stop()
        spinner.update()


def _set_activity_section_title(host: Any, attr_name: str, title: str) -> None:
    label_attr = {
        "processing_status_card": "processing_status_title_label",
        "processing_files_card": "processing_files_title_label",
    }.get(attr_name)
    label = getattr(host, label_attr, None) if label_attr is not None else None
    if label is not None:
        try:
            label.setText(title)
        except RuntimeError:
            pass
        return

    container = getattr(host, attr_name, None)
    if container is None:
        return
    try:
        container.header.title_label.setText(title)
    except (AttributeError, RuntimeError):
        pass


def _set_review_visible(host: Any, visible: bool, *, title: str = "Review") -> None:
    card = getattr(host, "processing_files_card", None)
    if card is not None:
        card.setVisible(visible)
    if visible:
        _set_activity_section_title(host, "processing_files_card", title)


def _set_progress_visible(host: Any, visible: bool) -> None:
    bar = getattr(host, "progress_bar", None)
    if bar is not None:
        bar.setVisible(visible)
    heading = getattr(host, "processing_progress_heading_label", None)
    if heading is not None:
        heading.setVisible(visible)


def _set_data_quality_sections(
    host: Any,
    *,
    summary_heading: str,
    live_heading: str,
    checklist: Sequence[str],
) -> None:
    _set_label(host, "processing_summary_heading_label", summary_heading)
    _set_label(host, "processing_live_heading_label", live_heading)
    _set_label(host, "processing_progress_heading_label", "Progress")
    _set_label(host, "processing_checklist_heading_label", "Checks in this step")
    checklist_panel = getattr(host, "processing_checklist_panel", None)
    if checklist_panel is not None:
        checklist_panel.setVisible(bool(checklist))
    _set_label(
        host,
        "processing_checklist_label",
        "\n".join(f"- {item}" for item in checklist),
    )


def _begin_preflight_page(
    host: Any,
    *,
    step: int | None,
    title: str,
    message: str,
    busy: bool,
    review_visible: bool,
    review_title: str = "Review",
    progress_visible: bool = True,
    checklist: Sequence[str] = (),
) -> None:
    if hasattr(host, "_busy_start"):
        host._busy_start()
    if hasattr(host, "_set_controls_enabled"):
        host._set_controls_enabled(False)
    _set_label(host, "processing_title_label", _DATA_QUALITY_CHECK_TITLE)
    _set_data_quality_sections(
        host,
        summary_heading="What's Happening Now",
        live_heading="Live status",
        checklist=checklist,
    )
    step_label = getattr(host, "processing_step_label", None)
    if step_label is not None:
        if step is None:
            step_label.setVisible(False)
        else:
            step_label.setText(f"Step {step} of {_DATA_QUALITY_STEP_TOTAL}: {title}")
            step_label.setVisible(True)
    _set_label(host, "processing_message_label", message)
    _set_label(host, "processing_summary_label", "Preparing data quality checks...")
    _set_label(host, "processing_current_file_label", "Latest file: Not started")
    _set_activity_section_title(host, "processing_status_card", title)
    _set_review_visible(host, review_visible, title=review_title)
    _set_progress_visible(host, progress_visible)
    _set_spinner_running(host, busy)
    _set_progress(host, 0, 1)
    button = getattr(host, "btn_start", None)
    if button is not None:
        button.hide()


def _clear_preflight_actions(host: Any) -> None:
    layout = getattr(host, "processing_action_layout", None)
    slot = getattr(host, "processing_action_slot", None)
    for button in list(getattr(host, "_preflight_qc_action_buttons", []) or []):
        try:
            # Deferred deletion can wait through the next QC event loop;
            # hide the old action before its slot is shown again.
            button.hide()
            if layout is not None and layout.indexOf(button) >= 0:
                layout.removeWidget(button)
            button.deleteLater()
        except RuntimeError:
            continue
    host._preflight_qc_action_buttons = []
    if slot is not None:
        slot.setMinimumWidth(0)
        slot.setMaximumWidth(16777215)
        slot.setVisible(False)


def _install_preflight_actions(
    host: Any,
    actions: Sequence[tuple[str, str, str]],
    callback: Any,
) -> None:
    _clear_preflight_actions(host)
    layout = getattr(host, "processing_action_layout", None)
    slot = getattr(host, "processing_action_slot", None)
    if layout is None or slot is None:
        return
    buttons = []
    for label, choice, variant in actions:
        button = make_action_button(label, variant=variant, parent=slot)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(lambda _checked=False, value=choice: callback(value))
        layout.addWidget(button, 0, Qt.AlignRight)
        buttons.append(button)
    if buttons:
        width = max(button.sizeHint().width() for button in buttons)
        width = max(176, min(width, 260))
        for button in buttons:
            button.setMinimumWidth(width)
        slot.setMinimumWidth(width)
        slot.setMaximumWidth(width)
        slot.setVisible(True)
    host._preflight_qc_action_buttons = buttons


def _set_preflight_table(
    host: Any,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    editable_last_column: bool = False,
    editable_columns: Sequence[int] | None = None,
    stretch_column: int | None = None,
    center_columns: bool = False,
    compact_rows: bool = False,
    preferred_column_widths: Mapping[int, int] | None = None,
) -> None:
    table = getattr(host, "processing_files_table", None)
    if table is None:
        return
    _clear_preflight_table_click_handler(host, table)
    editable_lookup = {int(column) for column in (editable_columns or ())}
    if editable_last_column and headers:
        editable_lookup.add(len(headers) - 1)
    for row_index in range(table.rowCount()):
        for column_index in range(table.columnCount()):
            widget = table.cellWidget(row_index, column_index)
            if widget is None:
                continue
            widget.hide()
            table.removeCellWidget(row_index, column_index)
            widget.deleteLater()
    table.clearContents()
    preferred_widths = {
        int(column): max(1, int(width))
        for column, width in (preferred_column_widths or {}).items()
    }
    table.setWordWrap(not compact_rows)
    table.setTextElideMode(Qt.ElideRight)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    if center_columns:
        for column_index in range(len(headers)):
            header_item = table.horizontalHeaderItem(column_index)
            if header_item is not None:
                header_item.setTextAlignment(Qt.AlignCenter)
    header = table.horizontalHeader()
    header.setStretchLastSection(not compact_rows)
    resolved_stretch_column = len(headers) - 1 if stretch_column is None else stretch_column
    for column_index in range(len(headers)):
        if column_index in preferred_widths:
            mode = QHeaderView.Interactive
        elif column_index == resolved_stretch_column:
            mode = QHeaderView.Stretch
        else:
            mode = QHeaderView.ResizeToContents
        header.setSectionResizeMode(column_index, mode)
    table.setRowCount(len(rows))
    table.setEditTriggers(
        QAbstractItemView.AllEditTriggers
        if editable_lookup
        else QAbstractItemView.NoEditTriggers
    )
    table.setSelectionMode(
        QAbstractItemView.SingleSelection
        if editable_lookup
        else QAbstractItemView.NoSelection
    )
    for row_index, row_values in enumerate(rows):
        for column_index, value in enumerate(row_values):
            item = QTableWidgetItem(str(value))
            if column_index not in editable_lookup:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if center_columns or column_index == 0:
                item.setTextAlignment(Qt.AlignCenter)
            if str(value):
                item.setToolTip(str(value))
            table.setItem(row_index, column_index, item)
    for column_index, width in preferred_widths.items():
        if 0 <= column_index < len(headers):
            header.resizeSection(column_index, width)
    vertical_header = table.verticalHeader()
    if compact_rows:
        row_height = max(30, table.fontMetrics().lineSpacing() + 14)
        vertical_header.setSectionResizeMode(QHeaderView.Fixed)
        vertical_header.setDefaultSectionSize(row_height)
        for row_index in range(table.rowCount()):
            table.setRowHeight(row_index, row_height)
    else:
        vertical_header.setSectionResizeMode(QHeaderView.Interactive)
        table.resizeRowsToContents()
    table.scrollToTop()
    horizontal_scroll = table.horizontalScrollBar()
    horizontal_scroll.setValue(horizontal_scroll.minimum())
    vertical_scroll = table.verticalScrollBar()
    vertical_scroll.setValue(vertical_scroll.minimum())


def _install_preflight_cell_widget(
    table: Any,
    row: int,
    column: int,
    widget: Any,
) -> None:
    """Install a compact editor without letting it inherit a tall review row."""

    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    widget.setMaximumHeight(widget.sizeHint().height())
    table.setCellWidget(row, column, widget)


def _clear_preflight_table_click_handler(host: Any, table: Any | None = None) -> None:
    table = table or getattr(host, "processing_files_table", None)
    handler = getattr(host, _PREFLIGHT_TABLE_CLICK_HANDLER_ATTR, None)
    if table is not None and handler is not None:
        try:
            table.itemClicked.disconnect(handler)
        except (TypeError, RuntimeError):
            pass
    setattr(host, _PREFLIGHT_TABLE_CLICK_HANDLER_ATTR, None)
    setattr(host, _HARD_EXCLUSION_DETAILS_ATTR, {})


def _await_preflight_choice(
    host: Any,
    actions: Sequence[tuple[str, str, str]],
) -> str:
    if not actions:
        return ""
    if (
        getattr(host, "processing_action_layout", None) is None
        or getattr(host, "processing_action_slot", None) is None
    ):
        return actions[0][1]

    loop = QEventLoop(host)
    result = {"choice": ""}

    def _choose(choice: str) -> None:
        result["choice"] = choice
        loop.quit()

    _set_spinner_running(host, False)
    _install_preflight_actions(host, actions, _choose)
    loop.exec()
    _clear_preflight_actions(host)
    return result["choice"]


def _show_clear_preflight_step(
    host: Any,
    *,
    step: int,
    title: str,
    summary: str,
    rows: Sequence[Sequence[str]],
) -> None:
    """Keep a completed check visible until the user is ready to continue."""

    _begin_preflight_page(
        host,
        step=step,
        title=title,
        message="Review the summary, then continue to the next step.",
        busy=False,
        review_visible=True,
        review_title="Check Summary",
        progress_visible=False,
    )
    _set_label(host, "processing_summary_label", summary)
    _set_label(host, "processing_current_file_label", "Continue when you're ready.")
    _set_preflight_table(host, ("Check", "Result"), rows, stretch_column=1)
    _await_preflight_choice(host, (("Continue", "continue", "primary"),))


def _file_name_from_progress(message: str) -> str:
    for prefix in ("Planning ", "Scanning ", "Cached ", "Finished "):
        if message.startswith(prefix):
            detail = message[len(prefix) :].strip()
            return detail.split(" · ", 1)[0].strip().casefold()
    return ""


def _grouped_scan_progress_text(host: Any, message: str) -> str:
    file_name = _file_name_from_progress(message)
    if not file_name:
        return message
    group_by_file = getattr(host, "_preflight_qc_group_by_file", {}) or {}
    group = str(group_by_file.get(file_name) or "").strip()
    if not group:
        return message
    action = message.split(" ", 1)[0]
    display_name = message.split(" ", 1)[1].strip()
    return f"{action} {group} · {display_name}"


def _update_scan_row(host: Any, message: str) -> None:
    file_name = _file_name_from_progress(message)
    if not file_name:
        return
    rows = getattr(host, "_preflight_qc_file_rows", {}) or {}
    row = rows.get(file_name)
    table = getattr(host, "processing_files_table", None)
    if table is None or row is None:
        return
    status_item = table.item(row, 0)
    if status_item is None:
        status_item = QTableWidgetItem()
        table.setItem(row, 0, status_item)
    if message.startswith("Cached "):
        status = "Cached"
    elif message.startswith("Finished "):
        status = "Checked"
    elif message.startswith("Planning "):
        status = "Planning"
    else:
        status = "Scanning"
    status_item.setText(status)
    status_item.setTextAlignment(Qt.AlignCenter)
    table.scrollToItem(status_item)


class _PreflightQcEmbeddedBridge(QObject):
    """Keep preflight worker signals marshalled through the GUI thread."""

    def __init__(
        self,
        host: Any,
        thread: QThread,
        result_holder: dict[str, Any],
        loop: QEventLoop,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._thread = thread
        self._result_holder = result_holder
        self._loop = loop

    @Slot(str, int, int)
    def on_progress(self, message: str, completed: int, total: int) -> None:
        _set_progress(self._host, completed, total)
        _set_label(
            self._host,
            "processing_summary_label",
            f"Checked {completed} of {total} participant file(s).",
        )
        _set_label(
            self._host,
            "processing_current_file_label",
            _grouped_scan_progress_text(self._host, message),
        )
        _update_scan_row(self._host, message)

    @Slot(object)
    def on_finished(self, scan: object) -> None:
        self._result_holder["scan"] = scan
        _set_progress(self._host, 1, 1)
        _set_label(
            self._host,
            "processing_current_file_label",
            "Finalizing data quality review...",
        )
        self._thread.quit()

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self._result_holder["error"] = message
        self._thread.quit()

    @Slot()
    def on_thread_finished(self) -> None:
        self._loop.quit()


class _KurtosisReviewEmbeddedBridge(QObject):
    """Marshal the QC-16 worker's results and progress to the GUI thread."""

    def __init__(
        self,
        host: Any,
        thread: QThread,
        result_holder: dict[str, Any],
        loop: QEventLoop,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._thread = thread
        self._result_holder = result_holder
        self._loop = loop

    @Slot(str, int, int)
    def on_progress(self, message: str, completed: int, total: int) -> None:
        _set_progress(self._host, completed, total)
        _set_label(
            self._host,
            "processing_summary_label",
            f"Checked {completed} of {total} recording(s) for kurtosis evidence.",
        )
        _set_label(self._host, "processing_current_file_label", message)

    @Slot(object)
    def on_finished(self, scan: object) -> None:
        self._result_holder["scan"] = scan
        _set_progress(self._host, 1, 1)
        self._thread.quit()

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self._result_holder["error"] = message
        self._thread.quit()

    @Slot()
    def on_thread_finished(self) -> None:
        self._loop.quit()


def _confirm_recording_not_started(
    host: Any,
    flagged: Sequence[HeaderOnlyPreflight],
    group_labels: Mapping[str, str],
) -> bool:
    if not flagged:
        return True
    names = [item.path.name for item in flagged]
    recording_mode = _recording_aware(flagged)
    detail_rows = [
        (
            item.participant_id,
            item.recording_id or "Not registered",
            _session_label(item),
            _visit_label(item),
            _result_group_display_name(item, group_labels),
            item.path.name,
        )
        for item in flagged
    ]
    _show_data_quality_notice(
        host,
        "Some files do not contain recording data.",
        'These files look like BioSemi recordings that were created, but no data '
        'was actually recorded. The most likely reason is that the experiment '
        'administrator forgot to click "Start Recording".',
        details="\n".join(
            " | ".join(row)
            if recording_mode
            else f"{row[4]} | {row[0]} | {row[5]}"
            for row in detail_rows
        ),
    )
    _begin_preflight_page(
        host,
        step=None,
        title="Check Raw Files",
        message="FPVS Toolbox found files that do not contain recording data.",
        busy=False,
        review_visible=True,
        review_title="Files to Exclude",
        progress_visible=False,
        checklist=(
            "Confirm files that contain no recording samples",
            "Exclude empty files from processing",
            "Keep the original raw files unchanged",
        ),
    )
    _set_label(
        host,
        "processing_summary_label",
        "It appears that the following files were created, but no data actually "
        "exists inside the files.",
    )
    _set_label(
        host,
        "processing_current_file_label",
        'The most likely explanation is that the experiment administrator forgot to push "Start Recording" on BioSemi.',
    )
    if recording_mode:
        _set_preflight_table(
            host,
            [
                "Participant",
                "Recording",
                "Session / phase-at-visit",
                "Visit",
                "Group",
                "File",
                "Recommended action",
            ],
            [(*row, "Exclude this recording") for row in detail_rows],
            stretch_column=6,
        )
    else:
        _set_preflight_table(
            host,
            ["PID", "Group", "File", "Recommended action"],
            [
                (participant_id, group, file_name, "Exclude from processing")
                for participant_id, _recording, _session, _visit, group, file_name
                in detail_rows
            ],
            stretch_column=3,
        )
    choice = _await_preflight_choice(
        host,
        (
            ("Exclude Files", "exclude", "primary"),
            ("Cancel Processing", "cancel", "secondary"),
        ),
    )
    if choice != "exclude":
        try:
            host.log("Data quality check cancelled at recording-not-started review.")
        except (AttributeError, TypeError, RuntimeError):
            pass
        return False
    try:
        host.log(format_bdf_recording_not_started_message(names), level=logging.WARNING)
    except (AttributeError, TypeError, RuntimeError):
        pass
    return True


def _run_scan_embedded(
    host: Any,
    raw_file_infos: Sequence[Any],
    params: dict[str, Any],
    *,
    skip_paths: Sequence[Path],
    group_labels: Mapping[str, str],
) -> PreflightQcScan | None:
    skip_keys = {_path_key(Path(path)) for path in skip_paths}
    remaining = [
        info
        for info in raw_file_infos
        if _path_key(Path(info.path)) not in skip_keys
    ]
    if not remaining:
        return PreflightQcScan(results=())

    host._preflight_qc_group_by_file = {
        Path(info.path).name.casefold(): _group_display_name(
            getattr(info, "group", None),
            group_labels,
        )
        for info in remaining
    }

    _begin_preflight_page(
        host,
        step=_SCAN_SIGNAL_HEALTH_STEP,
        title="Scan Signal Health",
        message=_DATA_QUALITY_SCAN_WAIT_MESSAGE,
        busy=True,
        review_visible=False,
        checklist=(
            "Inspect 5-second windows with 50% overlap inside analyzed occurrences",
            "Look for electrodes that appear physically disconnected",
            "Screen exact on-bin condition spectra through the retained band",
        ),
    )
    host._preflight_qc_file_rows = {}
    try:
        max_workers = max(1, int(getattr(host, "max_workers", 1) or 1))
    except (TypeError, ValueError):
        max_workers = 1
    worker_count = min(max_workers, len(remaining), PREFLIGHT_QC_MAX_WORKERS)
    project = getattr(host, "currentProject", None)
    project_root_value = getattr(project, "project_root", None)
    project_root = (
        Path(project_root_value).resolve()
        if project_root_value not in (None, "")
        else None
    )
    raw_event_map = params.get("event_id_map")
    event_map = (
        {str(label): int(code) for label, code in raw_event_map.items()}
        if isinstance(raw_event_map, Mapping)
        else {}
    )
    try:
        host.log(
            f"Data quality scan using {worker_count} parallel worker(s).",
            level=logging.INFO,
        )
    except (AttributeError, TypeError, RuntimeError):
        pass
    _set_label(host, "processing_summary_label", _DATA_QUALITY_SCAN_WAIT_MESSAGE)
    _set_label(
        host,
        "processing_current_file_label",
        f"Starting data quality scan with {worker_count} parallel worker(s)...",
    )
    _set_progress(host, 0, len(remaining))

    thread = QThread(host)
    worker = _PreflightQcWorker(
        remaining,
        params,
        skip_paths,
        max_workers=worker_count,
        project_root=project_root,
        event_map=event_map,
    )
    worker.moveToThread(thread)
    result_holder: dict[str, Any] = {}
    loop = QEventLoop(host)
    bridge = _PreflightQcEmbeddedBridge(host, thread, result_holder, loop)
    host._preflight_qc_thread = thread
    host._preflight_qc_worker = worker
    host._preflight_qc_bridge = bridge

    def _request_cancel(_choice: str) -> None:
        result_holder["cancelled"] = True
        worker.cancel()
        _clear_preflight_actions(host)
        _set_label(
            host,
            "processing_current_file_label",
            "Cancelling as soon as the active condition reads finish...",
        )

    _install_preflight_actions(
        host,
        (("Cancel Check", "cancel", "secondary"),),
        _request_cancel,
    )
    worker.progress.connect(bridge.on_progress)
    worker.finished.connect(bridge.on_finished)
    worker.failed.connect(bridge.on_failed)
    thread.started.connect(worker.run)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(bridge.on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()

    loop.exec()

    _clear_preflight_actions(host)
    host._preflight_qc_thread = None
    host._preflight_qc_worker = None
    host._preflight_qc_bridge = None
    host._preflight_qc_group_by_file = {}

    error = result_holder.get("error")
    if error:
        _set_label(host, "processing_summary_label", "Data quality check could not complete.")
        _set_label(host, "processing_current_file_label", str(error))
        _await_preflight_choice(
            host,
            (("Cancel Processing", "cancel", "primary"),),
        )
        return None

    if result_holder.get("cancelled"):
        return None

    scan = result_holder.get("scan")
    return scan if isinstance(scan, PreflightQcScan) else None


def _raw_channel_qc_by_recording(
    scan: PreflightQcScan,
) -> dict[str, dict[str, object]]:
    """Expose already-scored raw-QC findings to QC-16 for display only."""

    result: dict[str, dict[str, object]] = {}
    canonical_keys: dict[str, str] = {}
    for file_result in scan.results:
        recording_id = str(
            file_result.recording_id or file_result.participant_id
        ).strip()
        if not recording_id or file_result.raw_channel_qc is None:
            continue
        folded = recording_id.casefold()
        previous = canonical_keys.get(folded)
        if previous is not None and previous != recording_id:
            raise ValueError(
                "Raw-channel QC contains ambiguous recording identifiers "
                f"{previous!r} and {recording_id!r}."
            )
        if previous is not None:
            raise ValueError(
                f"Raw-channel QC contains duplicate recording {recording_id!r}."
            )
        canonical_keys[folded] = recording_id
        result[recording_id] = dict(file_result.raw_channel_qc)
    return result


class _QcSourcePrefetchBridge(QObject):
    """Retain the prefetch worker through the review and join it responsively."""

    def __init__(self, host: Any, thread: QThread, worker: QcSourcePrefetchWorker,
                 source_prefetch: QcSourcePrefetch) -> None:
        super().__init__(host)
        self.thread = thread
        self.worker = worker
        self.source_prefetch = source_prefetch
        self.finished = False
        self.loop: QEventLoop | None = None

    @Slot()
    def on_finished(self) -> None:
        self.thread.quit()

    @Slot()
    def on_thread_finished(self) -> None:
        self.finished = True
        if self.loop is not None:
            self.loop.quit()


def _start_qc_source_prefetch(
    host: Any, raw_file_infos: Sequence[Any], params: Mapping[str, Any],
) -> _QcSourcePrefetchBridge | None:
    """Start source-only work as step 2 opens; choices remain on the GUI thread."""
    project = getattr(host, "currentProject", None)
    project_root = getattr(project, "project_root", None)
    if not project_root or not raw_file_infos or not params.get("reject_thresh"):
        return None
    try:
        source_prefetch = QcSourcePrefetch(project_root, raw_file_infos, params)
    except (OSError, TypeError, ValueError, RuntimeError):
        logger.warning("qc_source_prefetch_setup_unavailable", exc_info=True)
        return None
    thread = QThread(host)
    worker = QcSourcePrefetchWorker(source_prefetch)
    worker.moveToThread(thread)
    bridge = _QcSourcePrefetchBridge(host, thread, worker, source_prefetch)
    host._qc_source_prefetch_bridge = bridge
    worker.finished.connect(bridge.on_finished)
    worker.finished.connect(worker.deleteLater)
    thread.started.connect(worker.run)
    thread.finished.connect(bridge.on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return bridge


def _finish_qc_source_prefetch(host: Any, bridge: _QcSourcePrefetchBridge | None) -> None:
    """Close run-owned maps off the GUI thread before leaving the QC workflow."""
    if bridge is None:
        return
    if not bridge.finished:
        bridge.loop = QEventLoop(host)
        bridge.worker.request_finish()
        _clear_preflight_actions(host)
        _set_label(host, "processing_current_file_label", "Finishing data quality checks...")
        bridge.loop.exec()
        bridge.loop.deleteLater()
        bridge.loop = None
    host._qc_source_prefetch_bridge = None
    bridge.deleteLater()


def _run_kurtosis_review_scan_embedded(
    host: Any,
    raw_file_infos: Sequence[Any],
    params: dict[str, Any],
    *,
    reviewed_event_plans_by_file: Mapping[str, Any],
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]],
    source_prefetch: QcSourcePrefetch | None = None,
) -> KurtosisReviewScan | None:
    """Run the shared QC-16 evidence preparation without blocking the GUI."""

    if not raw_file_infos:
        return KurtosisReviewScan(results=())
    raw_event_map = params.get("event_id_map")
    event_map = (
        {str(label): int(code) for label, code in raw_event_map.items()}
        if isinstance(raw_event_map, Mapping)
        else {}
    )
    _begin_preflight_page(
        host,
        step=_REVIEW_KURTOSIS_STEP,
        title="Review Kurtosis Findings",
        message=(
            "FPVS Toolbox is preparing current kurtosis evidence from the exact "
            "analyzed intervals."
        ),
        busy=True,
        review_visible=False,
        checklist=(
            "Apply the same filter and downsample stages used by processing",
            "Calculate kurtosis from included analyzed occurrences",
            "Reuse only decisions whose evidence fingerprint is still current",
        ),
    )
    _set_label(
        host,
        "processing_summary_label",
        (
            "Experimental automatic interpolation is enabled for valid kurtosis flags."
            if params.get("kurtosis_auto_interpolate_all", False) else
            "Checking whether any kurtosis-only electrode findings need review..."
        ),
    )
    _set_progress(host, 0, len(raw_file_infos))

    thread = QThread(host)
    worker = _KurtosisReviewWorker(
        raw_file_infos,
        params,
        event_map=event_map,
        reviewed_event_plans_by_file=reviewed_event_plans_by_file,
        raw_channel_qc_by_recording=raw_channel_qc_by_recording,
        source_prefetch=source_prefetch,
    )
    worker.moveToThread(thread)
    result_holder: dict[str, Any] = {}
    loop = QEventLoop(host)
    bridge = _KurtosisReviewEmbeddedBridge(host, thread, result_holder, loop)
    host._kurtosis_review_thread = thread
    host._kurtosis_review_worker = worker
    host._kurtosis_review_bridge = bridge

    def _request_cancel(_choice: str) -> None:
        result_holder["cancelled"] = True
        worker.cancel()
        _clear_preflight_actions(host)
        _set_label(
            host,
            "processing_current_file_label",
            "Cancelling after the active recording stage finishes...",
        )

    _install_preflight_actions(
        host,
        (("Cancel Check", "cancel", "secondary"),),
        _request_cancel,
    )
    worker.progress.connect(bridge.on_progress)
    worker.finished.connect(bridge.on_finished)
    worker.failed.connect(bridge.on_failed)
    thread.started.connect(worker.run)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(bridge.on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    loop.exec()

    _clear_preflight_actions(host)
    host._kurtosis_review_thread = None
    host._kurtosis_review_worker = None
    host._kurtosis_review_bridge = None
    error = result_holder.get("error")
    if error:
        _set_label(
            host,
            "processing_summary_label",
            "Kurtosis evidence could not be prepared.",
        )
        _set_label(host, "processing_current_file_label", str(error))
        _await_preflight_choice(
            host,
            (("Cancel Processing", "cancel", "primary"),),
        )
        return None
    if result_holder.get("cancelled"):
        return None
    scan = result_holder.get("scan")
    return scan if isinstance(scan, KurtosisReviewScan) else None


def _merge_kurtosis_review_receipts(
    existing: object,
    *,
    scanned_recording_ids: Sequence[str],
    current_scanned_receipts: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> dict[str, dict[str, dict[str, object]]]:
    """Replace active receipts only for the recordings rescored in this run."""

    scanned_keys = {
        str(recording_id).strip().casefold()
        for recording_id in scanned_recording_ids
        if str(recording_id).strip()
    }
    merged: dict[str, dict[str, dict[str, object]]] = {}
    if isinstance(existing, Mapping):
        for raw_recording, raw_channels in existing.items():
            recording_id = str(raw_recording).strip()
            if not recording_id or recording_id.casefold() in scanned_keys:
                continue
            if not isinstance(raw_channels, Mapping):
                continue
            merged[recording_id] = {
                str(channel): dict(receipt)
                for channel, receipt in raw_channels.items()
                if str(channel).strip() and isinstance(receipt, Mapping)
            }
    for recording_id, channels in current_scanned_receipts.items():
        normalized_recording = str(recording_id).strip()
        if normalized_recording.casefold() not in scanned_keys:
            raise ValueError(
                "QC-16 produced a decision for an unscanned recording: "
                f"{normalized_recording!r}."
            )
        merged[normalized_recording] = {
            str(channel): dict(receipt)
            for channel, receipt in channels.items()
            if str(channel).strip() and isinstance(receipt, Mapping)
        }
    return merged


def _save_kurtosis_review_receipts(
    host: Any,
    params: dict[str, Any],
    receipts: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    auto_interpolate_all: bool | None = None,
) -> bool:
    project = getattr(host, "currentProject", None)
    if project is None:
        QMessageBox.critical(
            host,
            "Project Save Error",
            "Kurtosis review decisions require an active project.",
        )
        return False
    previous = dict(
        (getattr(project, "preprocessing", {}) or {}).get(
            KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
            {},
        )
        or {}
    )
    updated_preprocessing = dict(getattr(project, "preprocessing", {}) or {})
    previous_auto_all = bool(updated_preprocessing.get("kurtosis_auto_interpolate_all", False))
    if auto_interpolate_all is not None:
        updated_preprocessing["kurtosis_auto_interpolate_all"] = bool(auto_interpolate_all)
    updated_preprocessing[KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY] = {
        str(recording_id): {
            str(channel): dict(receipt)
            for channel, receipt in channels.items()
        }
        for recording_id, channels in receipts.items()
    }
    try:
        normalized = project.update_preprocessing(updated_preprocessing)
        project.save()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        logger.exception("Failed to save kurtosis review decisions.")
        QMessageBox.critical(
            host,
            "Project Save Error",
            f"Could not save kurtosis review decisions: {exc}",
        )
        return False
    saved = dict(
        normalized.get(KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY) or {}
    )
    params[KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY] = saved
    params["kurtosis_auto_interpolate_all"] = bool(
        normalized.get("kurtosis_auto_interpolate_all", False)
    )
    host.validated_params = params
    if saved != previous or params["kurtosis_auto_interpolate_all"] != previous_auto_all:
        try:
            mark_frequency_domain_outputs_stale(
                project.project_root,
                reason="Kurtosis review decisions changed.",
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            logger.exception(
                "Kurtosis decisions were saved but downstream state could not "
                "be marked stale."
            )
            QMessageBox.warning(
                host,
                "Decisions Saved With Warning",
                "The kurtosis decisions were saved, but FPVS Toolbox could not "
                f"mark downstream frequency outputs stale: {exc}",
            )
    return True


def _review_kurtosis_findings(
    host: Any,
    params: dict[str, Any],
    scan: KurtosisReviewScan,
) -> bool:
    """Use the selected experimental policy or current explicit review decisions."""

    if scan.cancelled:
        return False
    if scan.errors:
        rows = [
            (
                result.participant_id,
                result.recording_id,
                result.path.name,
                result.error or "Unknown evidence error",
            )
            for result in scan.errors
        ]
        _begin_preflight_page(
            host,
            step=_REVIEW_KURTOSIS_STEP,
            title="Kurtosis Evidence Incomplete",
            message="Processing cannot continue without current QC-16 evidence.",
            busy=False,
            review_visible=True,
            review_title="Recordings That Need Attention",
            progress_visible=False,
            checklist=(
                "Review the recording and error below",
                "Correct the source or project settings",
                "Run preprocessing again to produce current evidence",
            ),
        )
        _set_preflight_table(
            host,
            ("Participant", "Recording", "File", "Evidence error"),
            rows,
            stretch_column=3,
        )
        _await_preflight_choice(
            host,
            (("Cancel Processing", "cancel", "primary"),),
        )
        return False

    project = getattr(host, "currentProject", None)
    existing = (
        (getattr(project, "preprocessing", {}) or {}).get(
            KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
            {},
        )
        if project is not None
        else params.get(KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY, {})
    )
    auto_all = bool(params.get("kurtosis_auto_interpolate_all", False))
    try:
        reconciliation = reconcile_kurtosis_review_decisions(
            scan, existing, kurtosis_auto_interpolate_all=auto_all,
        )
    except (TypeError, ValueError) as exc:
        logger.exception("Kurtosis decision reconciliation failed.")
        QMessageBox.critical(
            host,
            "Kurtosis Review Error",
            f"Saved kurtosis decisions could not be reconciled: {exc}",
        )
        return False

    scanned_receipts = reconciliation.processing_decisions_by_recording
    if reconciliation.pending_items:
        try:
            dialog = KurtosisReviewDialog(
                reconciliation, parent=host, auto_interpolate_all=auto_all,
                project_root=getattr(project, "project_root", None), signal_params=params,
            )
        except KurtosisReviewDialogError as exc:
            QMessageBox.critical(host, "Kurtosis Review Error", str(exc))
            return False
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            scanned_receipts = dialog.review_decisions_by_recording()
            auto_all = dialog.auto_interpolate_all()
        except KurtosisReviewDialogError as exc:
            QMessageBox.critical(host, "Kurtosis Review Error", str(exc))
            return False

    scanned_recordings = [result.recording_id for result in scan.results]
    try:
        merged = _merge_kurtosis_review_receipts(
            existing,
            scanned_recording_ids=scanned_recordings,
            current_scanned_receipts=scanned_receipts,
        )
    except ValueError as exc:
        QMessageBox.critical(host, "Kurtosis Review Error", str(exc))
        return False
    return _save_kurtosis_review_receipts(
        host, params, merged, auto_interpolate_all=auto_all,
    )


def _marker_review_actions() -> tuple[tuple[str, str, str], ...]:
    return (
        ("Use Verified Span", MARKER_DECISION_USE_CONTIGUOUS, "primary"),
        ("Retain Full Occurrence", MARKER_DECISION_RETAIN_FULL, "secondary"),
        ("Exclude Occurrence", MARKER_DECISION_EXCLUDE, "secondary"),
        ("Cancel Processing", "cancel", "secondary"),
    )


def _show_marker_review_error(host: Any, message: str) -> None:
    box = QMessageBox(host)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Marker Review")
    box.setText("This marker-review decision cannot be saved.")
    box.setInformativeText(message)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()


def _collect_retain_full_marker_evidence(
    host: Any,
    item: MarkerOccurrenceReviewItem,
) -> dict[str, object] | None:
    dialog = QDialog(host)
    dialog.setObjectName("marker_retain_full_evidence_dialog")
    dialog.setWindowTitle("Evidence for Full Occurrence")
    dialog.setModal(True)
    dialog.setMinimumWidth(620)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel(
        f"{item.participant_id} · {item.recording_id or item.path.name} · "
        f"{item.condition_label}, repetition {item.repetition_index + 1}",
        dialog,
    )
    title.setObjectName("marker_retain_full_evidence_title")
    title.setWordWrap(True)
    layout.addWidget(title)

    explanation = QLabel(
        "Retain the full proposed crop only when independent evidence shows that "
        "stimulation continued at the expected phase through the marker finding. "
        "Choose the evidence type and enter a note or a log/file reference.",
        dialog,
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    form = QFormLayout()
    form.setSpacing(10)
    evidence_type = QComboBox(dialog)
    evidence_type.setObjectName("marker_evidence_type_combo")
    evidence_type.addItem("Select evidence type...", "")
    evidence_type.addItem("Presentation log", "presentation_log")
    evidence_type.addItem("Photodiode trace", "photodiode_trace")
    evidence_type.addItem("Experimenter or session log", "session_log")
    evidence_type.addItem("Video recording", "video_recording")
    evidence_type.addItem("Other contemporaneous evidence", "other")
    form.addRow("Evidence type", evidence_type)

    evidence_reference = QLineEdit(dialog)
    evidence_reference.setObjectName("marker_evidence_reference_edit")
    evidence_reference.setPlaceholderText("For example: presentation_log.json, trial 4")
    form.addRow("Log or file reference", evidence_reference)

    evidence_note = QPlainTextEdit(dialog)
    evidence_note.setObjectName("marker_evidence_note_edit")
    evidence_note.setPlaceholderText(
        "Briefly state what the evidence shows about continuous, phase-correct stimulation."
    )
    evidence_note.setMaximumHeight(120)
    form.addRow("Evidence note", evidence_note)
    layout.addLayout(form)

    validation_label = QLabel("", dialog)
    validation_label.setObjectName("marker_evidence_validation_label")
    validation_label.setWordWrap(True)
    layout.addWidget(validation_label)

    accepted: dict[str, object] = {}
    actions = QHBoxLayout()
    actions.addStretch(1)
    back_button = make_action_button("Back", variant="secondary", parent=dialog)
    save_button = make_action_button(
        "Save Evidence",
        variant="primary",
        parent=dialog,
    )

    def _save() -> None:
        try:
            decision = build_marker_review_decision(
                item,
                MARKER_DECISION_RETAIN_FULL,
                evidence_type=str(evidence_type.currentData() or ""),
                evidence_note=evidence_note.toPlainText(),
                evidence_reference=evidence_reference.text(),
            )
        except MarkerOccurrenceReviewError as exc:
            validation_label.setText(str(exc))
            return
        accepted.update(decision)
        dialog.accept()

    back_button.clicked.connect(dialog.reject)
    save_button.clicked.connect(_save)
    actions.addWidget(back_button)
    actions.addWidget(save_button)
    layout.addLayout(actions)

    if dialog.exec() != QDialog.Accepted:
        return None
    return accepted or None


def _collect_verified_marker_span(
    host: Any,
    item: MarkerOccurrenceReviewItem,
) -> dict[str, object] | None:
    if not item.contiguous_candidate_spans:
        _show_marker_review_error(
            host,
            "This occurrence has no contiguous candidate that contains exactly the "
            "project's expected analyzed oddball cycles.",
        )
        return None

    dialog = QDialog(host)
    dialog.setObjectName("marker_contiguous_span_dialog")
    dialog.setWindowTitle("Choose Verified Contiguous Span")
    dialog.setModal(True)
    dialog.setMinimumWidth(560)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    explanation = QLabel(
        "Choose one span found by the marker check. Each listed span stays inside "
        "this occurrence and contains exactly the expected analyzed cycles.",
        dialog,
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    span_combo = QComboBox(dialog)
    span_combo.setObjectName("marker_contiguous_span_combo")
    for start, stop in item.contiguous_candidate_spans:
        start_s = float((start - item.first_samp) / item.sampling_rate_hz)
        stop_s = float((stop - item.first_samp) / item.sampling_rate_hz)
        duration_s = float((stop - start) / item.sampling_rate_hz)
        span_combo.addItem(
            f"Samples [{start}, {stop}) · {start_s:.6g} to {stop_s:.6g} s "
            f"from recording start · {duration_s:.6g} s duration",
            (start, stop),
        )
    layout.addWidget(span_combo)

    selected: dict[str, object] = {}
    actions = QHBoxLayout()
    actions.addStretch(1)
    back_button = make_action_button("Back", variant="secondary", parent=dialog)
    use_button = make_action_button("Use This Span", variant="primary", parent=dialog)

    def _use() -> None:
        raw_span = span_combo.currentData()
        span = tuple(raw_span) if isinstance(raw_span, Sequence) else None
        try:
            decision = build_marker_review_decision(
                item,
                MARKER_DECISION_USE_CONTIGUOUS,
                selected_span=span,  # type: ignore[arg-type]
            )
        except MarkerOccurrenceReviewError as exc:
            _show_marker_review_error(host, str(exc))
            return
        selected.update(decision)
        dialog.accept()

    back_button.clicked.connect(dialog.reject)
    use_button.clicked.connect(_use)
    actions.addWidget(back_button)
    actions.addWidget(use_button)
    layout.addLayout(actions)

    if dialog.exec() != QDialog.Accepted:
        return None
    return selected or None


def _collect_marker_exclusion_reason(
    host: Any,
    item: MarkerOccurrenceReviewItem,
) -> dict[str, object] | None:
    dialog = QDialog(host)
    dialog.setObjectName("marker_exclusion_reason_dialog")
    dialog.setWindowTitle("Exclude Occurrence")
    dialog.setModal(True)
    dialog.setMinimumWidth(560)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    explanation = QLabel(
        f"Exclude {item.condition_label}, repetition "
        f"{item.repetition_index + 1}, from analysis. You may add a reason below.",
        dialog,
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    reason_edit = QPlainTextEdit(dialog)
    reason_edit.setObjectName("marker_exclusion_reason_edit")
    reason_edit.setPlaceholderText(
        "Reason (optional)"
    )
    reason_edit.setMaximumHeight(120)
    layout.addWidget(reason_edit)

    validation_label = QLabel("", dialog)
    validation_label.setObjectName("marker_exclusion_reason_validation_label")
    validation_label.setWordWrap(True)
    layout.addWidget(validation_label)

    accepted: dict[str, object] = {}
    actions = QHBoxLayout()
    actions.addStretch(1)
    back_button = make_action_button("Back", variant="secondary", parent=dialog)
    exclude_button = make_action_button(
        "Exclude Occurrence",
        variant="primary",
        parent=dialog,
    )

    def _exclude() -> None:
        try:
            decision = build_marker_review_decision(
                item,
                MARKER_DECISION_EXCLUDE,
                reason=reason_edit.toPlainText(),
            )
        except MarkerOccurrenceReviewError as exc:
            validation_label.setText(str(exc))
            return
        accepted.update(decision)
        dialog.accept()

    back_button.clicked.connect(dialog.reject)
    exclude_button.clicked.connect(_exclude)
    actions.addWidget(back_button)
    actions.addWidget(exclude_button)
    layout.addLayout(actions)

    if dialog.exec() != QDialog.Accepted:
        return None
    return accepted or None


def _show_marker_occurrence_review(
    host: Any,
    item: MarkerOccurrenceReviewItem,
    *,
    index: int,
    total: int,
) -> str:
    _begin_preflight_page(
        host,
        step=_REVIEW_MARKER_OCCURRENCES_STEP,
        title="Review Marker Occurrence",
        message=(
            "A marker gap or extra marker needs a decision before signal-quality "
            "checks can use this condition occurrence."
        ),
        busy=False,
        review_visible=True,
        review_title=f"Marker occurrence {index} of {total}",
        progress_visible=False,
        checklist=(
            "Review the exact marker and interval evidence",
            "Choose one occurrence-level analysis decision",
            "Use independent evidence when retaining across a marker finding",
        ),
    )
    _set_label(
        host,
        "processing_summary_label",
        f"Reviewing {item.participant_id} · {item.condition_label} · repetition "
        f"{item.repetition_index + 1}.",
    )
    _set_label(
        host,
        "processing_current_file_label",
        "No marker is guessed or silently discarded. Your decision applies only "
        "to this occurrence.",
    )
    _set_preflight_table(
        host,
        ("Evidence", "Observed"),
        marker_occurrence_review_rows(item),
        stretch_column=1,
        preferred_column_widths={0: 240},
    )
    return _await_preflight_choice(host, _marker_review_actions())


def _review_marker_occurrences(
    host: Any,
    raw_file_infos: Sequence[Any],
    params: dict[str, Any],
    scan: PreflightQcScan,
    group_labels: Mapping[str, str],
) -> PreflightQcScan | None:
    try:
        review_items = collect_marker_occurrence_reviews(scan)
    except MarkerOccurrenceReviewError as exc:
        _show_marker_review_error(host, str(exc))
        return None
    if not review_items:
        _show_clear_preflight_step(
            host,
            step=_REVIEW_MARKER_OCCURRENCES_STEP,
            title="Review Marker Occurrences",
            summary="No marker occurrences are flagged for a review decision.",
            rows=(
                ("Recordings in scan", str(len(scan.results))),
                ("Marker decisions needed", "0"),
            ),
        )
        return scan

    affected_path_keys: set[str] = set()
    for index, item in enumerate(review_items, start=1):
        while True:
            choice = _show_marker_occurrence_review(
                host,
                item,
                index=index,
                total=len(review_items),
            )
            if choice == "cancel":
                try:
                    host.log(
                        "Data quality check cancelled at marker-occurrence review."
                    )
                except (AttributeError, TypeError, RuntimeError):
                    pass
                return None
            if choice == MARKER_DECISION_RETAIN_FULL:
                decision = _collect_retain_full_marker_evidence(host, item)
                if decision is None:
                    continue
            elif choice == MARKER_DECISION_USE_CONTIGUOUS:
                decision = _collect_verified_marker_span(host, item)
                if decision is None:
                    continue
            elif choice == MARKER_DECISION_EXCLUDE:
                decision = _collect_marker_exclusion_reason(host, item)
                if decision is None:
                    continue
            else:
                _show_marker_review_error(host, "Choose an occurrence-level decision.")
                continue
            params["_fpvs_marker_review_decisions_by_file"] = (
                merge_marker_review_decision(
                    params.get("_fpvs_marker_review_decisions_by_file"),
                    file_path=item.path,
                    occurrence_key=item.occurrence_key,
                    decision=decision,
                )
            )
            affected_path_keys.add(resolved_path_text(item.path).casefold())
            break

    affected_infos = [
        info
        for info in raw_file_infos
        if resolved_path_text(info.path).casefold() in affected_path_keys
    ]
    if len({resolved_path_text(info.path).casefold() for info in affected_infos}) != len(
        affected_path_keys
    ):
        _show_marker_review_error(
            host,
            "The source-file identity for one reviewed occurrence could not be resolved.",
        )
        return None

    rescanned = _run_scan_embedded(
        host,
        affected_infos,
        params,
        skip_paths=(),
        group_labels=group_labels,
    )
    if rescanned is None or rescanned.cancelled:
        return None
    try:
        merged_results = merge_rescanned_results(
            scan.results,
            rescanned.results,
            affected_paths=[info.path for info in affected_infos],
        )
        merged_scan = replace(
            scan,
            results=merged_results,
            project_grid_observations=(
                rescanned.project_grid_observations
                or scan.project_grid_observations
            ),
        )
        unresolved = collect_marker_occurrence_reviews(merged_scan)
    except MarkerOccurrenceReviewError as exc:
        _show_marker_review_error(host, str(exc))
        return None
    if unresolved:
        files = ", ".join(dict.fromkeys(item.path.name for item in unresolved))
        _show_marker_review_error(
            host,
            "Marker review remains unresolved after the affected-file rescan: " + files,
        )
        return None
    return merged_scan


def _review_removed_electrodes(
    host: Any,
    raw_file_infos: Sequence[Any],
    params: dict[str, Any],
    scan: PreflightQcScan,
    group_labels: Mapping[str, str],
) -> bool:
    if _recording_aware(raw_file_infos):
        return _review_removed_electrodes_by_recording(
            host,
            raw_file_infos,
            params,
            scan,
        )

    existing = normalize_manual_removed_electrodes_map(
        params.get("manual_removed_electrodes")
    )
    participant_ids = [str(info.subject_id) for info in raw_file_infos]
    participant_groups = _participant_group_display_map(raw_file_infos, group_labels)
    existing_for_review = _filter_removed_map_for_participants(existing, participant_ids)
    auto_flagged = scan.suggested_removed_electrodes
    prompt = (
        "FPVS Toolbox found electrode-level candidates that may need to be "
        "treated as removed or unusable before preprocessing. Review FPVS "
        "Toolbox's flags, remove any flags that are wrong, and add missed "
        "removed electrodes in the Manual additions column."
        if auto_flagged
        else "No removed-electrode candidates were flagged. Review any saved "
        "entries and add physically removed electrodes in Manual additions, "
        "then save the confirmed list to continue."
    )
    if auto_flagged:
        _show_data_quality_notice(
            host,
            "Review electrodes that may have been removed before recording.",
            "FPVS Toolbox will show low-signal removed-electrode candidates. "
            "High-amplitude, rare-burst, and spatial findings remain separate "
            "review evidence and are not preselected for interpolation. Confirm the "
            "list and add any physically removed electrodes that are missing.",
        )
    _begin_preflight_page(
        host,
        step=_CONFIRM_REMOVED_ELECTRODES_STEP,
        title="Confirm Removed Electrodes",
        message="Review the removed-electrode list before processing begins.",
        busy=False,
        review_visible=True,
        review_title="Removed Electrodes",
        progress_visible=False,
        checklist=(
            "Review all electrode-level removal candidates",
            "Add any missing removed electrodes",
            "Save the confirmed list into project settings",
        ),
    )
    _set_label(host, "processing_summary_label", prompt)
    _set_label(
        host,
        "processing_current_file_label",
        "Use the FPVS Toolbox flagged column only to accept or remove existing "
        "flags. Put missed electrodes in Manual additions.",
    )
    rows = _removed_review_row_values(
        participant_ids,
        auto_flagged,
        existing_for_review,
        participant_groups,
        _removed_review_reason_map(scan),
    )
    _set_preflight_table(
        host,
        _REMOVED_REVIEW_HEADERS,
        rows,
        editable_columns=(_REMOVED_REVIEW_AUTO_COLUMN, _REMOVED_REVIEW_MANUAL_COLUMN),
        stretch_column=_REMOVED_REVIEW_REASON_COLUMN,
    )
    table = getattr(host, "processing_files_table", None)

    def _refresh_final_column(row_index: int) -> None:
        if table is None:
            return
        pid_item = table.item(row_index, _REMOVED_REVIEW_PID_COLUMN)
        accepted_item = table.item(row_index, _REMOVED_REVIEW_AUTO_COLUMN)
        manual_item = table.item(row_index, _REMOVED_REVIEW_MANUAL_COLUMN)
        final_item = table.item(row_index, _REMOVED_REVIEW_FINAL_COLUMN)
        if pid_item is None or final_item is None:
            return
        record, _moved_to_manual, _moved_to_auto = _normalize_removed_review_entry(
            original_auto=_map_lookup(auto_flagged, pid_item.text().strip()),
            accepted_auto_text=accepted_item.text() if accepted_item else "",
            manual_additions_text=manual_item.text() if manual_item else "",
        )
        final_item.setText(
            ", ".join(record["final_confirmed_removed"])  # type: ignore[index]
        )

    def _on_removed_review_item_changed(item: QTableWidgetItem) -> None:
        if item.column() in (_REMOVED_REVIEW_AUTO_COLUMN, _REMOVED_REVIEW_MANUAL_COLUMN):
            _refresh_final_column(item.row())

    if table is not None:
        table.itemChanged.connect(_on_removed_review_item_changed)
    choice = _await_preflight_choice(
        host,
        (
            ("Save / Next", "save", "primary"),
            ("Cancel Processing", "cancel", "secondary"),
        ),
    )
    if table is not None:
        try:
            table.itemChanged.disconnect(_on_removed_review_item_changed)
        except (TypeError, RuntimeError):
            pass
    if choice != "save":
        try:
            host.log("Data quality check cancelled at removed-electrode review.")
        except (AttributeError, TypeError, RuntimeError):
            pass
        return False

    records, updated_review_map, warnings = _removed_review_records_from_rows(
        _removed_review_rows_from_table(host),
        auto_flagged,
    )
    if warnings:
        QMessageBox.warning(
            host,
            "Removed Electrode Review",
            "Some entries were moved to preserve source tracking:\n\n"
            + "\n".join(warnings),
        )
    updated_map = _replace_removed_map_for_participants(
        existing,
        updated_review_map,
        participant_ids,
    )
    updated_preproc = _settings_with_reviewed_manual_removed_electrodes(
        getattr(host.currentProject, "preprocessing", {}),
        participant_map=updated_map,
    )
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
    params[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] = bool(
        normalized.get(MANUAL_REMOVED_ELECTRODES_ENABLED_KEY)
    )
    params["_fpvs_removed_electrode_review_by_pid"] = records
    host.validated_params = params
    try:
        host.log("Data quality check saved the reviewed removed-electrode list.")
    except (AttributeError, TypeError, RuntimeError):
        pass
    return True


def _review_removed_electrodes_by_recording(
    host: Any,
    raw_file_infos: Sequence[Any],
    params: dict[str, Any],
    scan: PreflightQcScan,
) -> bool:
    """Review v2.2 removed-electrode decisions without merging two visits."""

    participant_map = normalize_manual_removed_electrodes_map(
        params.get("manual_removed_electrodes")
    )
    recording_map = normalize_manual_removed_electrodes_map(
        params.get("manual_removed_electrodes_by_recording")
    )
    auto_flagged = scan.suggested_removed_electrodes
    reasons = _removed_review_reason_map(scan)
    active_recording_keys = {
        str(getattr(info, "recording_id", "") or "").strip().casefold()
        for info in raw_file_infos
        if str(getattr(info, "recording_id", "") or "").strip()
    }
    coverage = project_recording_coverage_rows(
        host.currentProject,
        raw_file_infos,
    )
    displayed = tuple(
        identity
        for identity in coverage
        if identity.recording_id is None
        or identity.recording_id.casefold() in active_recording_keys
    )

    if auto_flagged:
        _show_data_quality_notice(
            host,
            "Review removed electrodes for each recording.",
            "Each visit keeps its own recording identity. Participant-wide entries "
            "remain available as legacy fallbacks, while recording-specific decisions "
            "can differ between visits.",
        )
    _begin_preflight_page(
        host,
        step=_CONFIRM_REMOVED_ELECTRODES_STEP,
        title="Confirm Removed Electrodes",
        message="Review each recording before processing begins.",
        busy=False,
        review_visible=True,
        review_title="Removed Electrodes by Recording",
        progress_visible=False,
        checklist=(
            "Confirm electrode decisions for each available recording",
            "Choose participant-wide fallback or this-recording scope",
            "Treat missing visits as coverage, not fabricated data",
        ),
    )
    _set_label(
        host,
        "processing_summary_label",
        "Session/phase-at-visit labels and visit order are shown separately. "
        "When every participant follows the same order, phase and order effects "
        "remain confounded."
        if auto_flagged
        else "No removed-electrode candidates were flagged. Review the saved "
        "entries for each recording and add physically removed electrodes if "
        "needed, then save the confirmed list to continue. Session/phase-at-visit "
        "and visit order are distinct; fixed order can confound them.",
    )
    _set_label(
        host,
        "processing_current_file_label",
        "Edit accepted FPVS flags and manual additions, then choose whether the "
        "final list applies to this recording or as the participant fallback.",
    )

    headers = (
        "Participant",
        "Recording",
        "Session / phase-at-visit",
        "Visit",
        "Group",
        "Coverage",
        "FPVS Toolbox flagged",
        "Why flagged",
        "Manual additions",
        "Final confirmed removed",
        "Scope",
    )
    rows: list[tuple[str, ...]] = []
    available_rows: dict[int, Any] = {}
    for identity in displayed:
        recording_id = str(identity.recording_id or "").strip()
        if not recording_id:
            rows.append(
                (
                    identity.participant_id,
                    "Not registered",
                    identity.session_label or identity.session_id or "—",
                    str(identity.visit_index or "—"),
                    identity.group_label,
                    identity.coverage_status,
                    "",
                    "Missing declared visit",
                    "",
                    "",
                    "Coverage only",
                )
            )
            continue
        explicit_override = any(
            key.casefold() == recording_id.casefold() for key in recording_map
        )
        existing_values = (
            _map_lookup(recording_map, recording_id)
            if explicit_override
            else _map_lookup(participant_map, identity.participant_id)
        )
        auto_values = parse_electrode_list(_map_lookup(auto_flagged, recording_id))
        auto_lookup = {channel.casefold() for channel in auto_values}
        manual_additions = [
            channel
            for channel in parse_electrode_list(existing_values)
            if channel.casefold() not in auto_lookup
        ]
        final_values = _unique_channels(auto_values, manual_additions)
        row_index = len(rows)
        rows.append(
            (
                identity.participant_id,
                recording_id,
                identity.session_label or identity.session_id or "—",
                str(identity.visit_index or "—"),
                identity.group_label,
                identity.coverage_status,
                ", ".join(auto_values),
                _string_map_lookup(reasons, recording_id)
                or ("Existing recording override" if explicit_override else "Participant fallback"),
                ", ".join(manual_additions),
                ", ".join(final_values),
                "",
            )
        )
        available_rows[row_index] = (identity, explicit_override, bool(auto_values))

    _set_preflight_table(
        host,
        headers,
        rows,
        editable_columns=(6, 8),
        stretch_column=7,
        compact_rows=True,
        preferred_column_widths={
            1: 156,
            2: 184,
            7: 240,
            8: 140,
            9: 176,
            10: 176,
        },
    )
    table = getattr(host, "processing_files_table", None)
    if table is not None:
        for row_index in range(table.rowCount()):
            if row_index not in available_rows:
                for column in (6, 8):
                    item = table.item(row_index, column)
                    if item is not None:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                continue
            _identity, explicit_override, has_auto = available_rows[row_index]
            scope = QComboBox(table)
            scope.setObjectName(f"removed_electrode_scope_{row_index}")
            scope.addItem("This recording", "recording")
            scope.addItem("Participant (all visits)", "participant")
            if not explicit_override and not has_auto:
                scope.setCurrentIndex(1)
            scope.setToolTip(
                "Recording scope keeps visits independent. Participant scope updates "
                "the fallback used by every visit without its own override."
            )
            _install_preflight_cell_widget(table, row_index, 10, scope)

    def _refresh_final_column(row_index: int) -> None:
        if table is None or row_index not in available_rows:
            return
        identity, _explicit, _auto = available_rows[row_index]
        accepted_item = table.item(row_index, 6)
        manual_item = table.item(row_index, 8)
        final_item = table.item(row_index, 9)
        if final_item is None or not identity.recording_id:
            return
        record, _moved_to_manual, _moved_to_auto = _normalize_removed_review_entry(
            original_auto=_map_lookup(auto_flagged, identity.recording_id),
            accepted_auto_text=accepted_item.text() if accepted_item else "",
            manual_additions_text=manual_item.text() if manual_item else "",
        )
        final_item.setText(
            ", ".join(record["final_confirmed_removed"])  # type: ignore[index]
        )

    def _on_item_changed(item: QTableWidgetItem) -> None:
        if item.column() in (6, 8):
            _refresh_final_column(item.row())

    if table is not None:
        table.itemChanged.connect(_on_item_changed)
    choice = _await_preflight_choice(
        host,
        (
            ("Save / Next", "save", "primary"),
            ("Cancel Processing", "cancel", "secondary"),
        ),
    )
    if table is not None:
        try:
            table.itemChanged.disconnect(_on_item_changed)
        except (TypeError, RuntimeError):
            pass
    if choice != "save":
        return False

    records: dict[str, dict[str, object]] = {}
    recording_replacements: dict[str, list[str]] = {}
    participant_replacements: dict[str, list[str]] = {}
    participant_scope_values: dict[str, list[list[str]]] = {}
    warnings: list[str] = []
    recording_ids: list[str] = []
    for row_index, (identity, _explicit, _has_auto) in available_rows.items():
        if table is None or not identity.recording_id:
            continue
        recording_id = identity.recording_id
        recording_ids.append(recording_id)
        accepted_item = table.item(row_index, 6)
        manual_item = table.item(row_index, 8)
        scope_widget = table.cellWidget(row_index, 10)
        scope = (
            str(scope_widget.currentData())
            if isinstance(scope_widget, QComboBox)
            else "recording"
        )
        record, moved_to_manual, moved_to_auto = _normalize_removed_review_entry(
            original_auto=_map_lookup(auto_flagged, recording_id),
            accepted_auto_text=accepted_item.text() if accepted_item else "",
            manual_additions_text=manual_item.text() if manual_item else "",
        )
        final_values = list(record["final_confirmed_removed"])  # type: ignore[arg-type]
        record.update(
            {
                "participant_id": identity.participant_id,
                "recording_id": recording_id,
                "session_id": identity.session_id,
                "session_label": identity.session_label,
                "visit_index": identity.visit_index,
                "scope": scope,
            }
        )
        records[recording_id] = record
        if scope == "participant":
            participant_scope_values.setdefault(
                identity.participant_id.casefold(), []
            ).append(final_values)
            participant_replacements[identity.participant_id] = final_values
        else:
            recording_replacements[recording_id] = final_values
        if moved_to_manual:
            warnings.append(
                f"{recording_id}: moved to Manual additions: "
                + ", ".join(moved_to_manual)
            )
        if moved_to_auto:
            warnings.append(
                f"{recording_id}: treated original FPVS flag(s) as accepted: "
                + ", ".join(moved_to_auto)
            )

    for participant_key, decisions in participant_scope_values.items():
        normalized_decisions = {
            tuple(channel.casefold() for channel in decision)
            for decision in decisions
        }
        if len(normalized_decisions) > 1:
            QMessageBox.warning(
                host,
                "Conflicting Participant-Wide Decisions",
                "Participant-wide rows for the same participant must use the same "
                f"final electrode list ({participant_key}). Choose recording scope "
                "for visit-specific differences.",
            )
            return False
    if warnings:
        QMessageBox.warning(
            host,
            "Removed Electrode Review",
            "Some entries were moved to preserve source tracking:\n\n"
            + "\n".join(warnings),
        )

    updated_participants = _replace_removed_map_for_participants(
        participant_map,
        participant_replacements,
        list(participant_replacements),
    )
    updated_recordings = _replace_removed_map_for_participants(
        recording_map,
        recording_replacements,
        recording_ids,
    )
    updated_preproc = _settings_with_reviewed_manual_removed_electrodes(
        getattr(host.currentProject, "preprocessing", {}),
        participant_map=updated_participants,
        recording_map=updated_recordings,
    )
    try:
        normalized = host.currentProject.update_preprocessing(updated_preproc)
        host.currentProject.save()
    except ValueError as exc:
        QMessageBox.warning(host, "Invalid Manual Removed Electrodes", str(exc))
        return False
    except OSError as exc:
        logger.exception("Failed to save recording removed-electrode settings.")
        QMessageBox.critical(host, "Project Save Error", str(exc))
        return False

    params["manual_removed_electrodes"] = dict(
        normalized.get("manual_removed_electrodes") or {}
    )
    params["manual_removed_electrodes_by_recording"] = dict(
        normalized.get("manual_removed_electrodes_by_recording") or {}
    )
    params["removed_electrode_detection_mode"] = normalized.get(
        "removed_electrode_detection_mode"
    )
    params["auto_detect_removed_electrodes"] = bool(
        normalized.get("auto_detect_removed_electrodes")
    )
    params[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] = bool(
        normalized.get(MANUAL_REMOVED_ELECTRODES_ENABLED_KEY)
    )
    params["_fpvs_removed_electrode_review_by_recording"] = records
    host.validated_params = params
    try:
        host.log(
            "Data quality check saved recording-aware removed-electrode decisions."
        )
    except (AttributeError, TypeError, RuntimeError):
        pass
    return True


def _removed_review_rows_from_table(host: Any) -> list[tuple[str, str, str, str]]:
    table = getattr(host, "processing_files_table", None)
    if table is None:
        return []
    rows: list[tuple[str, str, str, str]] = []
    for row in range(table.rowCount()):
        values = []
        for column in (
            _REMOVED_REVIEW_PID_COLUMN,
            _REMOVED_REVIEW_AUTO_COLUMN,
            _REMOVED_REVIEW_MANUAL_COLUMN,
            _REMOVED_REVIEW_FINAL_COLUMN,
        ):
            item = table.item(row, column)
            values.append(item.text().strip() if item else "")
        if values and values[0]:
            rows.append(tuple(values))
    return rows


def _payload_list(payload: Mapping[str, object] | None, key: str) -> tuple[str, ...]:
    values = (payload or {}).get(key)
    if not isinstance(values, Sequence) or isinstance(values, str):
        return ()
    return tuple(str(value) for value in values if str(value).strip())


def _payload_float(payload: Mapping[str, object] | None, key: str) -> float | None:
    try:
        value = (payload or {}).get(key)
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_uv(value: float | None) -> str:
    if value is None:
        return "not available"
    return f"{value:.1f} uV"


def _hard_candidate_flag(result: PreflightQcFileResult) -> str:
    if result.raw_qc_excluded:
        return "Technical raw QC"
    if result.raw_qc_decision_review_required:
        return "Signal review"
    return "Recording review"


def _hard_candidate_reason(result: PreflightQcFileResult) -> str:
    payload = result.raw_channel_qc or {}
    rules = set(_payload_list(payload, "review_rules"))
    rules.update(_payload_list(payload, "triggered_rules"))
    if any(
        str(finding.get("severity") or "") == "severe_review"
        for finding in result.raw_amplitude_review_findings
    ):
        return "High raw signal amplitude"
    if {
        "left_hemisphere_candidate_burden_review",
        "right_hemisphere_candidate_burden_review",
        "left_hemisphere_failure",
        "right_hemisphere_failure",
    } & rules:
        return "Candidates concentrated on one cap side"
    if {"candidate_cluster_review", "bad_channel_cluster"} & rules:
        return "Connected cluster of candidate channels"
    if {
        "candidate_count_review",
        "candidate_fraction_review",
        "bad_channel_count",
        "bad_channel_fraction",
    } & rules:
        return "High candidate-channel burden"
    if result.raw_qc_excluded:
        return "Raw data could not be evaluated"
    return "Recording-level signal review"


def _hard_candidate_plain_explanation(result: PreflightQcFileResult) -> str:
    reason = _hard_candidate_reason(result)
    if reason == "High raw signal amplitude":
        return SEVERE_RAW_AMPLITUDE_HELP_TEXT
    if reason == "Candidates concentrated on one cap side":
        return (
            "Candidate channels are concentrated on one side of the cap. This is "
            "a provisional review flag; inspect the evidence before deciding."
        )
    if reason == "Connected cluster of candidate channels":
        return (
            "Several nearby channels were flagged together using BioSemi64 sensor "
            "positions. The cluster is review evidence, not an automatic exclusion."
        )
    if reason == "High candidate-channel burden":
        return (
            "The count or fraction of candidate channels crossed a provisional "
            "review threshold. The threshold alone does not show that the recording "
            "is unusable."
        )
    if result.raw_qc_excluded:
        return "A technical raw-data check could not produce analyzable EEG samples."
    return "The recording crossed a signal-review threshold before preprocessing."


def _hard_candidate_detail_text(
    result: PreflightQcFileResult,
    group_labels: Mapping[str, str] | None = None,
) -> str:
    labels = group_labels or {}
    raw_payload = result.raw_channel_qc or {}
    thresholds = raw_payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        thresholds = {}
    baseline_std = _payload_float(raw_payload, "raw_baseline_median_std_uv")
    baseline_p2p = _payload_float(raw_payload, "raw_baseline_median_p2p_99_uv")
    baseline_std_limit = _payload_float(
        thresholds,
        "baseline_severe_review_median_std_uv",
    )
    if baseline_std_limit is None:
        baseline_std_limit = _payload_float(
            thresholds,
            "baseline_exclusion_median_std_uv",
        )
    baseline_p2p_limit = _payload_float(
        thresholds,
        "baseline_severe_review_median_p2p_99_uv",
    )
    if baseline_p2p_limit is None:
        baseline_p2p_limit = _payload_float(
            thresholds,
            "baseline_exclusion_median_p2p_99_uv",
        )
    raw_message = result.raw_qc_message
    lines = [
        f"Participant: {result.participant_id}",
        *(
            (
                f"Recording: {result.recording_id}",
                f"Session / phase-at-visit: {_session_label(result)}",
                f"Visit: {_visit_label(result)}",
            )
            if result.recording_id
            else ()
        ),
        f"Group: {_result_group_display_name(result, labels)}",
        f"File: {result.path.name}",
        f"Flag: {_hard_candidate_flag(result)}",
        f"Reason: {_hard_candidate_reason(result)}",
        "",
        _hard_candidate_plain_explanation(result),
    ]
    if baseline_std is not None or baseline_p2p is not None:
        lines.extend(
            [
                "",
                "Full-occurrence aggregate metrics:",
                f"- Median STD: {_format_uv(baseline_std)}"
                + (
                    f" (severe review >= {_format_uv(baseline_std_limit)})"
                    if baseline_std_limit is not None
                    else ""
                ),
                f"- Median P2P99: {_format_uv(baseline_p2p)}"
                + (
                    f" (severe review >= {_format_uv(baseline_p2p_limit)})"
                    if baseline_p2p_limit is not None
                    else ""
                ),
            ]
        )
    if result.raw_amplitude_review_findings:
        lines.extend(["", "Amplitude review evidence:"])
        for finding in result.raw_amplitude_review_findings:
            scope = str(finding.get("scope") or "analyzed interval").replace(
                "_", " "
            )
            condition = str(finding.get("condition_label") or "").strip()
            occurrence = finding.get("occurrence_display")
            location = (
                f"; {condition}, occurrence {occurrence}"
                if condition and occurrence not in (None, "")
                else ""
            )
            window_count = finding.get("diagnostic_window_count")
            window_text = (
                f"; {window_count} overlapping diagnostic window(s)"
                if window_count not in (None, "")
                else ""
            )
            union_spans = finding.get("flagged_window_union_spans")
            span_text = (
                f"; flagged-window union {union_spans}"
                if isinstance(union_spans, Sequence)
                and not isinstance(union_spans, (str, bytes))
                else ""
            )
            lines.append(
                "- "
                + str(finding.get("severity") or "review").replace("_", " ")
                + f" ({scope}{location}): median STD "
                + _format_uv(_payload_float(finding, "median_std_uv"))
                + ", median P2P99 "
                + _format_uv(_payload_float(finding, "median_p2p_99_uv"))
                + window_text
                + span_text
            )
    rule_lines = _payload_list(raw_payload, "review_rules")
    if not rule_lines:
        rule_lines = _payload_list(raw_payload, "triggered_rules")
    if rule_lines:
        lines.extend(["", "Review rule(s):", "- " + "\n- ".join(rule_lines)])
    if result.candidate_burden_findings:
        lines.extend(["", "Candidate burden evidence:"])
        for finding in result.candidate_burden_findings:
            denominator = finding.get("denominator")
            observed = finding.get("observed")
            measured = (
                f"{observed}/{denominator}"
                if denominator not in (None, 0) and isinstance(observed, int)
                else str(observed)
            )
            lines.append(
                "- "
                + str(finding.get("rule") or "candidate burden")
                + f": observed {measured} {finding.get('comparator') or ''} "
                + str(finding.get("threshold"))
            )
    if result.occurrence_review_findings:
        lines.extend(["", "Condition / occurrence evidence:"])
        lines.extend(
            "- " + str(finding.get("statement") or "")
            for finding in result.occurrence_review_findings
            if str(finding.get("statement") or "").strip()
        )
    bad_channels = _payload_list(raw_payload, "bad_channels")
    if bad_channels:
        lines.extend(["", "Flagged channel(s):", ", ".join(bad_channels)])
    if raw_message:
        lines.extend(["", "Original raw QC message:", raw_message])
    return "\n".join(lines)


def _hard_candidate_row_values(
    candidates: Sequence[PreflightQcFileResult],
    group_labels: Mapping[str, str] | None = None,
) -> list[tuple[str, ...]]:
    labels = group_labels or {}
    if _recording_aware(candidates):
        return [
            (
                result.participant_id,
                result.recording_id or "Not registered",
                _session_label(result),
                _visit_label(result),
                _result_group_display_name(result, labels),
                _hard_candidate_flag(result),
                _hard_candidate_reason(result),
                "",
                "",
                "",
            )
            for result in candidates
        ]
    return [
        (
            result.participant_id,
            _result_group_display_name(result, labels),
            _hard_candidate_flag(result),
            _hard_candidate_reason(result),
            "",
            "",
        )
        for result in candidates
    ]


def _show_hard_exclusion_detail_dialog(
    host: Any,
    result: PreflightQcFileResult,
    details: str,
    group_labels: Mapping[str, str],
) -> None:
    dialog = QDialog(host)
    dialog.setObjectName("participant_qc_details_dialog")
    dialog.setWindowTitle("Participant QC Details")
    dialog.setModal(True)
    dialog.setMinimumSize(640, 460)
    dialog.resize(760, 560)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel(
        (
            f"{result.participant_id}"
            + (f" · {result.recording_id}" if result.recording_id else "")
            + " · "
            f"{_result_group_display_name(result, group_labels)}: "
            f"{_hard_candidate_reason(result)}"
        ),
        dialog,
    )
    title.setObjectName("participant_qc_details_title")
    title.setWordWrap(True)
    layout.addWidget(title)

    explanation = QLabel(_hard_candidate_plain_explanation(result), dialog)
    explanation.setObjectName("participant_qc_details_explanation")
    explanation.setWordWrap(True)
    if _hard_candidate_reason(result) == "High raw signal amplitude":
        explanation.setText(
            SEVERE_RAW_AMPLITUDE_HELP_TEXT
            + f' <a href="{BIOSEMI_SHARED_NOISE_HELP_URL}">'
            "BioSemi: referencing and shared noise</a>"
        )
        explanation.setTextFormat(Qt.RichText)
        explanation.setOpenExternalLinks(True)
    layout.addWidget(explanation)

    details_edit = QPlainTextEdit(dialog)
    details_edit.setObjectName("participant_qc_details_text")
    details_edit.setReadOnly(True)
    details_edit.setPlainText(details)
    details_edit.setMinimumHeight(300)
    layout.addWidget(details_edit, 1)

    actions = QHBoxLayout()
    actions.addStretch(1)
    close_button = make_action_button("Close", variant="primary", parent=dialog)
    close_button.clicked.connect(dialog.accept)
    actions.addWidget(close_button)
    layout.addLayout(actions)

    dialog.exec()


def _install_hard_exclusion_details(
    host: Any,
    candidates: Sequence[PreflightQcFileResult],
    group_labels: Mapping[str, str],
) -> None:
    table = getattr(host, "processing_files_table", None)
    if table is None:
        return
    recording_mode = _recording_aware(candidates)
    identity_column = 1 if recording_mode else _HARD_EXCLUSION_PID_COLUMN
    details_column = 9 if recording_mode else _HARD_EXCLUSION_DETAILS_COLUMN
    candidate_by_pid = {_identity_id(result).casefold(): result for result in candidates}
    details_by_pid = {
        _identity_id(result).casefold(): _hard_candidate_detail_text(
            result,
            group_labels,
        )
        for result in candidates
    }
    setattr(host, _HARD_EXCLUSION_DETAILS_ATTR, details_by_pid)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    for row in range(table.rowCount()):
        item = table.item(row, identity_column)
        pid = item.text().strip() if item else ""
        candidate = candidate_by_pid.get(pid.casefold())
        details = details_by_pid.get(pid.casefold())
        if candidate is None or not details:
            return
        button = make_action_button("More info", variant="secondary", parent=table)
        button.setToolTip(f"Open QC details for {pid}")
        button.setMinimumWidth(96)
        button.clicked.connect(
            lambda _checked=False, current=candidate, text=details: (
                _show_hard_exclusion_detail_dialog(
                    host,
                    current,
                    text,
                    group_labels,
                )
            )
        )
        table.setCellWidget(row, details_column, button)
    table.resizeRowsToContents()


def _condition_crop_review_rows(
    audit: PreflightConditionCropGridAudit,
    group_labels: Mapping[str, str],
) -> list[tuple[str, ...]]:
    expected = (
        f"{audit.reference_duration_s:g} s "
        f"({audit.reference_oddball_cycles} oddball cycles)"
        if audit.reference_duration_s is not None
        and audit.reference_oddball_cycles is not None
        else "No strict-majority grid"
    )
    recording_mode = _recording_aware(audit.observations)
    rows: list[tuple[str, ...]] = []
    for observation in audit.review_candidates:
        observed = (
            f"{observation.duration_s:g} s "
            f"({observation.oddball_cycles} oddball cycles)"
            if observation.duration_s is not None
            and observation.oddball_cycles is not None
            else "Unavailable"
        )
        reason = observation.issue or (
            "Multiple valid FFT grids exist; choose which condition cohort to keep."
            if audit.has_unresolved_grid_conflict
            else "Usable crop has a different FFT grid from the project majority."
        )
        if recording_mode:
            rows.append(
                (
                    observation.participant_id,
                    observation.recording_id or "Not registered",
                    _session_label(observation),
                    _visit_label(observation),
                    _group_display_name(observation.group_id, group_labels),
                    observation.condition_label,
                    observed,
                    expected,
                    reason,
                    "",
                    "",
                )
            )
        else:
            rows.append(
                (
                    observation.participant_id,
                    _group_display_name(observation.group_id, group_labels),
                    observation.condition_label,
                    observed,
                    expected,
                    reason,
                    "",
                )
            )
    return rows


def _checked_condition_crop_pairs(
    host: Any,
    candidates: Sequence[PreflightConditionCropObservation],
) -> set[tuple[str, str]]:
    table = getattr(host, "processing_files_table", None)
    if table is None:
        return {candidate.pair_key for candidate in candidates if candidate.repetition_count > 0}
    checked: set[tuple[str, str]] = set()
    recording_mode = _recording_aware(candidates)
    check_column = 10 if recording_mode else _CONDITION_EXCLUSION_CHECK_COLUMN
    for row, candidate in enumerate(candidates):
        item = table.item(row, check_column)
        if item is not None and item.checkState() == Qt.Checked:
            checked.add(candidate.pair_key)
    return checked


def _checked_condition_crop_scopes(
    host: Any,
    candidates: Sequence[PreflightConditionCropObservation],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return checked participant and recording pairs from v2.2 scope widgets."""

    table = getattr(host, "processing_files_table", None)
    if table is None:
        return set(), {
            candidate.pair_key for candidate in candidates if candidate.repetition_count > 0
        }
    participant_pairs: set[tuple[str, str]] = set()
    recording_pairs: set[tuple[str, str]] = set()
    for row, candidate in enumerate(candidates):
        item = table.item(row, 10)
        if item is None or item.checkState() != Qt.Checked:
            continue
        scope_widget = table.cellWidget(row, 9)
        scope = (
            str(scope_widget.currentData())
            if isinstance(scope_widget, QComboBox)
            else "recording"
        )
        if scope == "participant":
            participant_pairs.add(candidate.participant_pair_key)
        elif candidate.recording_pair_key is not None:
            recording_pairs.add(candidate.recording_pair_key)
    return participant_pairs, recording_pairs


def _replace_reviewed_condition_exclusions(
    existing: Mapping[str, Sequence[str]] | None,
    candidates: Sequence[PreflightConditionCropObservation],
    checked_pairs: set[tuple[str, str]],
) -> dict[str, list[str]]:
    normalized = normalize_manual_excluded_participant_conditions(existing)
    reviewed_pairs = {candidate.participant_pair_key for candidate in candidates}
    values: dict[str, list[str]] = {}
    for participant_id, conditions in normalized.items():
        for condition in conditions:
            if (participant_id.casefold(), condition.casefold()) in reviewed_pairs:
                continue
            values.setdefault(participant_id, []).append(condition)
    for candidate in candidates:
        if candidate.participant_pair_key in checked_pairs:
            values.setdefault(candidate.participant_id, []).append(
                candidate.condition_label
            )
    return normalize_manual_excluded_participant_conditions(values)


def _replace_reviewed_recording_condition_exclusions(
    existing: Mapping[str, Sequence[str]] | None,
    candidates: Sequence[PreflightConditionCropObservation],
    checked_pairs: set[tuple[str, str]],
) -> dict[str, list[str]]:
    normalized = normalize_manual_excluded_recording_conditions(existing)
    reviewed_pairs = {
        pair
        for candidate in candidates
        if (pair := candidate.recording_pair_key) is not None
    }
    values: dict[str, list[str]] = {}
    for recording_id, conditions in normalized.items():
        for condition in conditions:
            if (recording_id.casefold(), condition.casefold()) in reviewed_pairs:
                continue
            values.setdefault(recording_id, []).append(condition)
    for candidate in candidates:
        if (
            candidate.recording_pair_key in checked_pairs
            and candidate.recording_id is not None
        ):
            values.setdefault(candidate.recording_id, []).append(
                candidate.condition_label
            )
    return normalize_manual_excluded_recording_conditions(values)


def _confirm_condition_crop_exclusions(
    host: Any,
    params: dict[str, Any],
    scan: PreflightQcScan,
    group_labels: Mapping[str, str],
) -> bool:
    existing = normalize_manual_excluded_participant_conditions(
        params.get("manual_excluded_participant_conditions")
    )
    existing_recordings = normalize_manual_excluded_recording_conditions(
        params.get("manual_excluded_recording_conditions")
    )
    audit = build_preflight_condition_crop_grid_audit(
        scan,
        expected_event_map=params.get("event_id_map"),
        excluded_participant_conditions=existing,
        excluded_participants=normalize_manual_excluded_participants(
            params.get("manual_excluded_participants")
        ),
        excluded_recording_conditions=existing_recordings,
        excluded_recordings=normalize_manual_excluded_recordings(
            params.get("manual_excluded_recordings")
        ),
    )
    candidates = audit.review_candidates
    if not candidates:
        _show_clear_preflight_step(
            host,
            step=_CONFIRM_CONDITION_EXCLUSIONS_STEP,
            title="Confirm Condition Exclusions",
            summary="No additional condition exclusions need review in this crop check.",
            rows=(
                ("Condition entries in crop audit", str(len(audit.observations))),
                (
                    "Condition entries already excluded",
                    str(sum(item.already_excluded for item in audit.observations)),
                ),
                ("Condition decisions needed", "0"),
            ),
        )
        return True
    recording_mode = _recording_aware(candidates)
    missing_conditions = any(candidate.repetition_count == 0 for candidate in candidates)

    _show_data_quality_notice(
        host,
        "Review missing conditions and usable FFT crops."
        if missing_conditions
        else "Review conditions with a different usable FFT crop.",
        "A declared condition has no start occurrence. If it was intentionally "
        "absent, select it for exclusion. Otherwise, cancel processing and check "
        "the condition-start triggers. Unresolved missing conditions prevent "
        "SNR and other analysis outputs from being prepared."
        if missing_conditions
        else "These condition workbooks would use a different frequency grid from "
        "the project majority. You can exclude a recording-condition or the "
        "participant-condition across all visits without deleting data."
        if recording_mode
        else "These condition workbooks would use a different frequency grid from "
        "the project majority. You can exclude selected participant-condition "
        "pairs from downstream analysis without deleting raw data or workbooks.",
    )
    _begin_preflight_page(
        host,
        step=_CONFIRM_CONDITION_EXCLUSIONS_STEP,
        title="Confirm Condition Exclusions",
        message="Resolve missing conditions before processing continues."
        if missing_conditions
        else "Review usable-data crop differences before processing continues.",
        busy=False,
        review_visible=True,
        review_title="Missing Conditions and Crop Exclusions"
        if missing_conditions
        else "Condition Crop Exclusions",
        progress_visible=False,
        checklist=(
            "Compare the usable FFT crop with the project reference",
            "Keep selected participant-condition pairs out of downstream analyses",
            "Preserve raw data and generated workbooks for audit",
        ),
    )
    _set_label(
        host,
        "processing_summary_label",
        "Missing conditions require an explicit decision. Only exclude a condition "
        "if its absence is intended; missing rows are not selected automatically."
        if missing_conditions
        else "A different crop length creates a different FFT grid and prevents "
        "project-wide statistically significant harmonic selection.",
    )
    _set_label(
        host,
        "processing_current_file_label",
        (
            "Session/phase-at-visit and visit order are distinct fields; fixed "
            "ordering can confound them. Checked rows remain on disk."
            if recording_mode
            else "Checked rows remain on disk but will not enter Stats, harmonic "
            "selection, Plot Generator, or other shared-index analyses."
        ),
    )
    if recording_mode:
        headers = (
            "Participant",
            "Recording",
            "Session / phase-at-visit",
            "Visit",
            "Group",
            "Condition",
            "Usable FFT crop",
            "Project reference",
            "Reason",
            "Scope",
            "Exclude downstream",
        )
        stretch_column = 8
        check_column = 10
    else:
        headers = (
            "PID",
            "Group",
            "Condition",
            "Usable FFT crop",
            "Project reference",
            "Reason",
            "Exclude downstream",
        )
        stretch_column = 5
        check_column = _CONDITION_EXCLUSION_CHECK_COLUMN
    _set_preflight_table(
        host,
        headers,
        _condition_crop_review_rows(audit, group_labels),
        stretch_column=stretch_column,
        center_columns=True,
        compact_rows=recording_mode,
        preferred_column_widths=(
            {
                1: 156,
                2: 184,
                6: 176,
                7: 176,
                8: 240,
                9: 176,
                10: 156,
            }
            if recording_mode
            else None
        ),
    )
    table = getattr(host, "processing_files_table", None)
    if table is not None:
        recommended_pairs = {
            observation.pair_key
            for observation in audit.recommended_exclusions
        }
        for row, candidate in enumerate(candidates):
            item = table.item(row, check_column)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, check_column, item)
            item.setFlags(
                (item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable
            )
            item.setCheckState(
                Qt.Checked
                if candidate.pair_key in recommended_pairs
                else Qt.Unchecked
            )
            if candidate.already_excluded:
                item.setToolTip("This participant-condition is already excluded.")
            if recording_mode:
                scope = QComboBox(table)
                scope.setObjectName(f"condition_crop_scope_{row}")
                scope.addItem("This recording", "recording")
                scope.addItem("Participant (all visits)", "participant")
                scope.setToolTip(
                    "Choose whether this condition omission applies to one "
                    "recording or to the participant across every visit."
                )
                _install_preflight_cell_widget(table, row, 9, scope)

    while True:
        choice = _await_preflight_choice(
            host,
            (
                ("Save Selected / Next", "save", "primary"),
                ("Cancel Processing", "cancel", "secondary")
                if missing_conditions
                else ("Continue Without Changes", "skip", "secondary"),
            ),
        )
        if choice != "save":
            return not missing_conditions and choice == "skip"
        if recording_mode:
            checked_participants, checked_recordings = (
                _checked_condition_crop_scopes(host, candidates)
            )
            updated = _replace_reviewed_condition_exclusions(
                existing,
                candidates,
                checked_participants,
            )
            updated_recordings = _replace_reviewed_recording_condition_exclusions(
                existing_recordings,
                candidates,
                checked_recordings,
            )
        else:
            updated = _replace_reviewed_condition_exclusions(
                existing,
                candidates,
                _checked_condition_crop_pairs(host, candidates),
            )
            updated_recordings = existing_recordings
        if audit.is_compatible_with_exclusions(
            updated,
            recording_exclusions=updated_recordings,
        ):
            break
        QMessageBox.warning(
            host,
            "Conditions Still Need Review" if missing_conditions else "Incompatible FFT Grids Still Included",
            "A missing condition is still included, or the retained conditions "
            "do not share one usable FFT grid. Exclude only intentionally absent "
            "conditions, or cancel processing to check the triggers."
            if missing_conditions
            else "The selected exclusions still leave no usable grid or more than one "
            "FFT grid in downstream analysis. Select complete participant-condition "
            "rows for exclusion, or continue without saving this QC decision.",
        )

    updated_preproc = dict(getattr(host.currentProject, "preprocessing", {}) or {})
    updated_preproc["manual_excluded_participant_conditions"] = updated
    updated_preproc["manual_excluded_recording_conditions"] = updated_recordings
    try:
        normalized = host.currentProject.update_preprocessing(updated_preproc)
        host.currentProject.save()
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("Failed to save participant-condition exclusions.")
        QMessageBox.critical(
            host,
            "Project Save Error",
            f"Could not save participant-condition exclusions: {exc}",
        )
        return False

    if updated != existing or updated_recordings != existing_recordings:
        try:
            mark_frequency_domain_outputs_stale(
                host.currentProject.project_root,
                reason="Participant-condition FFT crop exclusions changed.",
            )
        except (OSError, ValueError, RuntimeError) as exc:
            logger.exception(
                "Participant-condition exclusions saved, but downstream "
                "frequency-domain status could not be marked stale."
            )
            QMessageBox.warning(
                host,
                "Exclusions Saved With Warning",
                "The participant-condition exclusions were saved, but FPVS "
                "Toolbox could not update the downstream-stale status: "
                f"{exc}",
            )

    params["manual_excluded_participant_conditions"] = dict(
        normalized.get("manual_excluded_participant_conditions") or {}
    )
    params["manual_excluded_recording_conditions"] = dict(
        normalized.get("manual_excluded_recording_conditions") or {}
    )
    host.validated_params = params
    try:
        host.log(
            "Data quality check saved downstream condition exclusions: "
            f"participants={params['manual_excluded_participant_conditions']}; "
            f"recordings={params['manual_excluded_recording_conditions']}",
            level=logging.WARNING,
        )
    except (AttributeError, TypeError, RuntimeError):
        pass
    return True


def _selected_hard_exclusions(
    table: Any,
    candidates: Sequence[PreflightQcFileResult],
    *,
    recording_mode: bool,
) -> list[tuple[PreflightQcFileResult, str]]:
    """Return only rows explicitly set to Exclude; unselected rows are safe."""

    decision_column = 7 if recording_mode else _HARD_EXCLUSION_DECISION_COLUMN
    scope_column = 8 if recording_mode else None
    selected: list[tuple[PreflightQcFileResult, str]] = []
    for row, result in enumerate(candidates):
        decision_widget = table.cellWidget(row, decision_column)
        decision = (
            str(decision_widget.currentData())
            if decision_widget is not None
            and hasattr(decision_widget, "currentData")
            else _HARD_EXCLUSION_DECISION_UNSELECTED
        )
        if decision != _HARD_EXCLUSION_DECISION_EXCLUDE:
            continue
        scope = "participant"
        if scope_column is not None:
            scope_widget = table.cellWidget(row, scope_column)
            scope = (
                str(scope_widget.currentData())
                if scope_widget is not None and hasattr(scope_widget, "currentData")
                else "recording"
            )
        selected.append((result, scope))
    return selected


def _confirm_hard_exclusions(
    host: Any,
    params: dict[str, Any],
    scan: PreflightQcScan,
    group_labels: Mapping[str, str],
) -> set[str]:
    candidates = scan.hard_exclusion_candidates
    if not candidates:
        _show_clear_preflight_step(
            host,
            step=_CONFIRM_PARTICIPANT_EXCLUSIONS_STEP,
            title="Review Possible Exclusions",
            summary="No recording or participant exclusions were flagged by this check.",
            rows=(
                ("Recordings in scan", str(len(scan.results))),
                ("Possible exclusions flagged", "0"),
            ),
        )
        return set()
    recording_mode = _recording_aware(candidates)
    _show_data_quality_notice(
        host,
        (
            "Review recordings that may need to be excluded."
            if recording_mode
            else "Review participants that may need to be excluded."
        ),
        (
            "FPVS Toolbox found recording-level review flags. Review the "
            "evidence, then choose whether to continue or explicitly exclude "
            "the recording or participant."
            if recording_mode
            else "FPVS Toolbox found participant-level review flags. The next "
            "screen lets you continue or explicitly add them to the manual "
            "participant exclusion list."
        ),
    )
    _begin_preflight_page(
        host,
        step=_CONFIRM_PARTICIPANT_EXCLUSIONS_STEP,
        title="Review Possible Exclusions",
        message="Review signal evidence before deciding whether to exclude data.",
        busy=False,
        review_visible=True,
        review_title=(
            "Recording / Participant Exclusions"
            if recording_mode
            else "Participant Exclusions"
        ),
        progress_visible=False,
        checklist=(
            "Review recording-level signal evidence"
            if recording_mode
            else "Review participant-level signal evidence",
            "Choose single-recording or participant-wide scope"
            if recording_mode
            else "Add confirmed cases to the participant exclusion list",
            "Leave uncertain cases available if you want to inspect them later",
        ),
    )
    _set_label(
        host,
        "processing_summary_label",
        "FPVS Toolbox found recording-level review flags. These flags do not "
        "exclude data automatically."
        if recording_mode
        else "FPVS Toolbox found participant-level review flags. These flags do "
        "not exclude data automatically.",
    )
    amplitude_review = any(
        any(
            str(finding.get("severity") or "") == "severe_review"
            for finding in result.raw_amplitude_review_findings
        )
        for result in candidates
    )
    if amplitude_review:
        _set_amplitude_help_label(
            host,
            "processing_current_file_label",
            (
                "Review scope for each candidate below."
                if recording_mode
                else "Review the candidates below."
            ),
        )
    else:
        _set_label(
            host,
            "processing_current_file_label",
            "Session/phase-at-visit and visit order are distinct; fixed order can "
            "confound them. Review scope for each candidate below."
            if recording_mode
            else "Review the candidates below. You can add them to the manual "
            "participant exclusion list or continue without changing the list.",
        )
    if recording_mode:
        headers = (
            "Participant",
            "Recording",
            "Session / phase-at-visit",
            "Visit",
            "Group",
            "Flag",
            "Reason",
            "Decision",
            "Scope",
            "More info",
        )
        stretch_column = 6
    else:
        headers = ("PID", "Group", "Flag", "Reason", "Decision", "More info")
        stretch_column = _HARD_EXCLUSION_REASON_COLUMN
    _set_preflight_table(
        host,
        headers,
        _hard_candidate_row_values(candidates, group_labels),
        stretch_column=stretch_column,
        center_columns=True,
    )
    table = getattr(host, "processing_files_table", None)
    if table is not None:
        for row in range(len(candidates)):
            decision = QComboBox(table)
            decision.setObjectName(f"hard_exclusion_decision_{row}")
            decision.addItem(
                "No exclusion selected",
                _HARD_EXCLUSION_DECISION_UNSELECTED,
            )
            decision.addItem("Include / keep available", _HARD_EXCLUSION_DECISION_KEEP)
            decision.addItem("Exclude", _HARD_EXCLUSION_DECISION_EXCLUDE)
            decision.setToolTip(
                "Choose Exclude only after reviewing this row. The default does "
                "not exclude anything."
            )
            _install_preflight_cell_widget(
                table,
                row,
                7 if recording_mode else _HARD_EXCLUSION_DECISION_COLUMN,
                decision,
            )
            if recording_mode:
                scope = QComboBox(table)
                scope.setObjectName(f"hard_exclusion_scope_{row}")
                scope.addItem("This recording", "recording")
                scope.addItem("Participant (all visits)", "participant")
                scope.setToolTip(
                    "Recording scope excludes one visit. Participant scope excludes "
                    "all current and future visits for this participant."
                )
                _install_preflight_cell_widget(table, row, 8, scope)
    _install_hard_exclusion_details(host, candidates, group_labels)
    choice = _await_preflight_choice(
        host,
        (
            ("Apply Review Decisions", "apply", "primary"),
            ("Continue Without Changes", "skip", "secondary"),
        ),
    )
    if choice != "apply" or table is None:
        return set()

    selected_rows = _selected_hard_exclusions(
        table,
        candidates,
        recording_mode=recording_mode,
    )
    if not selected_rows:
        return set()

    current = normalize_manual_excluded_participants(
        params.get("manual_excluded_participants")
    )
    current_recordings = normalize_manual_excluded_recordings(
        params.get("manual_excluded_recordings")
    )
    if recording_mode:
        participant_additions: list[str] = []
        recording_additions: list[str] = []
        accepted: set[str] = set()
        for result, scope in selected_rows:
            if scope == "participant":
                participant_additions.append(result.participant_id)
                accepted.add(result.participant_id.casefold())
            elif result.recording_id:
                recording_additions.append(result.recording_id)
                accepted.add(result.recording_id.casefold())
        updated = normalize_manual_excluded_participants(
            [*current, *participant_additions]
        )
        updated_recordings = normalize_manual_excluded_recordings(
            [*current_recordings, *recording_additions]
        )
    else:
        updated = normalize_manual_excluded_participants(
            [*current, *(result.participant_id for result, _scope in selected_rows)]
        )
        updated_recordings = current_recordings
        accepted = {
            result.participant_id.casefold()
            for result, _scope in selected_rows
        }
    updated_preproc = dict(getattr(host.currentProject, "preprocessing", {}) or {})
    updated_preproc["manual_excluded_participants"] = updated
    updated_preproc["manual_excluded_recordings"] = updated_recordings
    try:
        normalized = host.currentProject.update_preprocessing(updated_preproc)
        host.currentProject.save()
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("Failed to save participant exclusions.")
        QMessageBox.critical(
            host,
            "Project Save Error",
            f"Could not save participant exclusions: {exc}",
        )
        return set()
    params["manual_excluded_participants"] = list(
        normalized.get("manual_excluded_participants") or []
    )
    params["manual_excluded_recordings"] = list(
        normalized.get("manual_excluded_recordings") or []
    )
    host.validated_params = params
    try:
        host.log(
            "Data quality check added exclusion(s): participants="
            + ", ".join(params["manual_excluded_participants"])
            + "; recordings="
            + ", ".join(params["manual_excluded_recordings"]),
            level=logging.WARNING,
        )
    except (AttributeError, TypeError, RuntimeError):
        pass
    return accepted


def _quality_check_dir(host: Any) -> Path:
    project = getattr(host, "currentProject", None)
    root = Path(getattr(project, "project_root", "."))
    return root / QUALITY_CHECK_FOLDER


def _style_preflight_review_sheet(worksheet: Any) -> None:
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in worksheet.iter_rows():
        for cell in row:
            cell.alignment = center
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
    if worksheet.max_row >= 1 and worksheet.max_column >= 1:
        worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.freeze_panes = "A2"
    for column_index, column_cells in enumerate(worksheet.columns, start=1):
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        worksheet.column_dimensions[get_column_letter(column_index)].width = min(
            max(max_length + 2, 12),
            80,
        )


def _write_preflight_review_flags(
    host: Any,
    rows: Sequence[tuple[str, ...]],
) -> Path:
    target = _quality_check_dir(host).resolve() / _DATA_QUALITY_REVIEW_FLAGS_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Review Flags"
    worksheet.append(
        (
            "Participant",
            "Recording",
            "Session / phase-at-visit",
            "Visit",
            "Group",
            "Source File",
            "Flagged Item",
        )
        if rows and len(rows[0]) == 7
        else ("PID", "Group", "Source File", "Flagged Item")
    )
    for row in rows:
        worksheet.append(row)
    _style_preflight_review_sheet(worksheet)
    workbook.save(target)
    return target


def _remaining_review_rows(
    scan: PreflightQcScan,
    accepted_hard_exclusions: set[str],
    group_labels: Mapping[str, str] | None = None,
    *,
    review_items: list[SignalReviewItem] | None = None,
    review_diagnostics_by_file: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[tuple[str, ...]]:
    labels = group_labels or {}
    recording_mode = _recording_aware(scan.results)
    rows: list[tuple[str, ...]] = []

    def append_row(
        result: PreflightQcFileResult,
        review_item: str,
        *,
        kind: str = "Other",
        title: str = "Signal review",
        finding: Mapping[str, Any] | None = None,
        channels: Sequence[str] = (),
    ) -> None:
        if recording_mode:
            rows.append(
                (
                    result.participant_id,
                    result.recording_id or "Not registered",
                    _session_label(result),
                    _visit_label(result),
                    _result_group_display_name(result, labels),
                    result.path.name,
                    review_item,
                )
            )
        else:
            rows.append(
                (
                    result.participant_id,
                    _result_group_display_name(result, labels),
                    result.path.name,
                    review_item,
                )
            )

        if review_items is not None:
            payload = finding or {}
            channel_names = (
                list(channels)
                or _payload_list(payload, "channels")
                or _payload_list(payload, "affected_channels")
            )
            if not channel_names and payload.get("channel"):
                channel_names = [str(payload["channel"])]
            occurrence = payload.get("occurrence_display")
            event_plan = (result.condition_qc or {}).get("event_plan")
            time_spans, time_scope = review_time_scope(payload, event_plan)
            # Spectral summaries can identify an occurrence without repeating its
            # sample bounds. Only the exact matching event-plan span supplies them.
            if (not time_spans and kind == "Spectral" and isinstance(event_plan, Mapping)
                    and not {"start_sample", "stop_sample", "flagged_window_union_spans"}.intersection(payload)):
                matching_spans = [
                    span for span in event_plan.get("spans", ())
                    if isinstance(span, Mapping)
                    and payload.get("condition_label")
                    and span.get("condition_label") == payload.get("condition_label")
                    and payload.get("occurrence") is not None
                    and span.get("repetition_index") == payload.get("occurrence")
                ]
                if len(matching_spans) == 1:
                    span = matching_spans[0]
                    time_spans, time_scope = review_time_scope({
                        "start_sample": span.get("time_start_sample"),
                        "stop_sample": span.get("time_stop_sample"),
                    }, event_plan)
            review_items.append(
                SignalReviewItem(
                    export_row=rows[-1],
                    kind=kind,
                    title=title,
                    condition=str(payload.get("condition_label") or ""),
                    occurrence=str(occurrence) if occurrence is not None else "",
                    channels=", ".join(channel_names),
                    source_path=str(result.path),
                    time_spans_s=time_spans,
                    time_scope=time_scope,
                    evidence=dict(payload),
                )
            )

    for result in scan.suspicious_results:
        if (
            result.participant_id.casefold() in accepted_hard_exclusions
            or result.identity_id.casefold() in accepted_hard_exclusions
        ):
            continue
        if result.load_error:
            append_row(
                result, f"Could not be scanned ({result.load_error}).",
                kind="Assessment status", title="Scan unavailable",
            )

        for finding in result.raw_amplitude_review_findings:
            condition = str(finding.get("condition_label") or "").strip()
            occurrence = finding.get("occurrence_display")
            location = (
                f" in {condition}, occurrence {occurrence}"
                if condition and occurrence not in (None, "")
                else " across the recording's analyzed intervals"
            )
            severity = str(finding.get("severity") or "review").replace("_", " ")
            window_count = finding.get("diagnostic_window_count")
            union_spans = finding.get("flagged_window_union_spans")
            window_scope = (
                f" {window_count} overlapping diagnostic window(s); "
                f"flagged-window union {union_spans}."
                if window_count not in (None, "")
                else ""
            )
            append_row(
                result,
                f"High raw signal amplitude ({severity}){location}: median STD "
                f"{_format_uv(_payload_float(finding, 'median_std_uv'))}; median "
                f"P2P99 {_format_uv(_payload_float(finding, 'median_p2p_99_uv'))}."
                f"{window_scope} "
                f"{SEVERE_RAW_AMPLITUDE_HELP_TEXT} BioSemi help: "
                f"{BIOSEMI_SHARED_NOISE_HELP_URL}",
                kind="Amplitude", title=f"High raw amplitude ({severity})",
                finding=finding,
            )

        for finding in result.candidate_burden_findings:
            channels = _payload_list(finding, "channels")
            denominator = finding.get("denominator")
            observed = finding.get("observed")
            observed_text = (
                f"{observed}/{denominator}"
                if isinstance(observed, int) and denominator not in (None, 0)
                else str(observed)
            )
            append_row(
                result,
                "Candidate burden review: "
                + str(finding.get("rule") or "threshold").replace("_", " ")
                + f"; observed {observed_text} {finding.get('comparator') or ''} "
                + str(finding.get("threshold"))
                + (f"; channels {', '.join(channels)}" if channels else "")
                + ". Review only; no automatic exclusion or interpolation.",
                kind="Candidate burden", title="Candidate burden",
                finding=finding,
            )

        for finding in result.occurrence_review_findings:
            statement = str(finding.get("statement") or "").strip()
            categories = _payload_list(finding, "categories")
            bounds = (
                finding.get("start_sample"),
                finding.get("stop_sample"),
            )
            append_row(
                result,
                statement
                + (f" Category: {', '.join(categories)}." if categories else "")
                + (
                    f" Analyzed samples: [{bounds[0]}, {bounds[1]})."
                    if None not in bounds
                    else ""
                ),
                kind="Channel quality",
                title=", ".join(categories).replace("_", " ").capitalize()
                or "Channel quality",
                finding=finding,
            )

        for finding in result.transient_review_findings:
            append_row(
                result,
                f"{finding.get('channel') or 'Channel'} had a transient "
                f"{str(finding.get('category') or 'signal').replace('_', ' ')} "
                f"flag in {finding.get('condition_label') or 'condition'}, occurrence "
                f"{finding.get('occurrence_display') or '?'}, across "
                f"{finding.get('diagnostic_window_count') or 0} overlapping "
                "diagnostic window(s). Reported coverage is the union of flagged "
                "windows, not measured artifact duration.",
                kind="Transient signals",
                title="Transient " + str(finding.get("category") or "signal").replace(
                    "_", " "
                ),
                finding=finding,
            )

        for scope_row in result.occurrence_evaluation_scope:
            if scope_row.get("evaluation_status") != "not_evaluated":
                continue
            reason = str(scope_row.get("reason") or "unavailable").replace("_", " ")
            append_row(
                result,
                f"{scope_row.get('condition_label') or 'Condition'}, occurrence "
                f"{scope_row.get('occurrence_display') or '?'}: Not evaluated "
                f"({reason}). It is excluded from the evaluated comparison count.",
                kind="Assessment status", title="Occurrence not evaluated",
                finding=scope_row,
            )

        if result.raw_channel_qc is not None and not result.experimental_detector_evaluated:
            append_row(
                result,
                "Experimental removed-electrode assessment: Not evaluated "
                "(disabled in project settings). No detector finding is inferred.",
                kind="Assessment status", title="Removed-electrode detection disabled",
            )

        structured_channel_findings = bool(
            result.occurrence_review_findings or result.transient_review_findings
        )
        if not structured_channel_findings and result.high_amplitude_channels:
            append_row(
                result,
                "High-amplitude channel review: "
                + ", ".join(result.high_amplitude_channels),
                kind="Amplitude", title="High-amplitude channels",
                channels=result.high_amplitude_channels,
            )
        if not structured_channel_findings and result.rare_burst_channels:
            append_row(
                result,
                "Rare-burst channel review: " + ", ".join(result.rare_burst_channels),
                kind="Transient signals", title="Rare-burst channels",
                channels=result.rare_burst_channels,
            )
        if not structured_channel_findings and result.spatial_outlier_channels:
            append_row(
                result,
                "Spatially inconsistent channel review: "
                + ", ".join(result.spatial_outlier_channels),
                kind="Channel quality", title="Spatially inconsistent channels",
                channels=result.spatial_outlier_channels,
            )
        if (
            result.review_rules
            and not result.raw_amplitude_review_findings
            and not result.candidate_burden_findings
            and not structured_channel_findings
        ):
            append_row(
                result,
                "Raw-data review rule(s): " + ", ".join(result.review_rules),
                title="Raw-data review rules",
            )
        for finding in result.raw_spectral_review_rows:
            condition = str(finding.get("condition_label") or "condition")
            occurrence = finding.get("occurrence_display") or "?"
            duration = _payload_float(finding, "analyzed_duration_s")
            cycles = finding.get("realized_oddball_cycles")
            scope = (
                f"{condition}, occurrence {occurrence}; "
                f"{duration:.3f} s / {cycles} oddball cycles"
                if duration is not None and cycles not in (None, "")
                else f"{condition}, occurrence {occurrence}"
            )
            if (
                finding.get("evidence_kind")
                == "target_below_experimental_screen_boundary"
            ):
                frequency = _payload_float(finding, "frequency_hz")
                fft_bin = finding.get("fft_bin")
                harmonic = finding.get("oddball_harmonic")
                frequency_text = (
                    f"{frequency:.3f} Hz / bin {fft_bin}"
                    if frequency is not None
                    else f"bin {fft_bin}"
                )
                append_row(
                    result,
                    "Experimental raw-spectral review limitation: "
                    + scope
                    + f"; oddball harmonic {harmonic}; {frequency_text} is below "
                    "the locked 0.5-Hz screen boundary and was not evaluated. "
                    "The recording-condition is retained.",
                    kind="Assessment status", title="Target below spectral screen boundary",
                    finding=finding,
                )
                continue
            if finding.get("evidence_kind") == "configured_notch_fpvs_collision":
                target_hz = _payload_float(finding, "target_frequency_hz")
                target_bin = finding.get("target_fft_bin")
                oddball_harmonic = finding.get("oddball_harmonic")
                base_harmonic = finding.get("base_harmonic")
                classification = str(
                    finding.get("classification") or "notch collision"
                ).replace("_", " ")
                notch_centers = _payload_list(finding, "target_notch_centers_hz")
                noise_collisions = finding.get("noise_bin_collisions")
                noise_details: list[str] = []
                if isinstance(noise_collisions, Sequence) and not isinstance(
                    noise_collisions, str
                ):
                    for collision in noise_collisions:
                        if not isinstance(collision, Mapping):
                            continue
                        bin_index = collision.get("fft_bin")
                        bin_hz = _payload_float(collision, "frequency_hz")
                        notch_hz = _payload_float(collision, "notch_center_hz")
                        noise_details.append(
                            f"bin {bin_index}"
                            + (f" ({bin_hz:.3f} Hz)" if bin_hz is not None else "")
                            + (
                                f" at {notch_hz:g}-Hz notch"
                                if notch_hz is not None
                                else ""
                            )
                        )
                affected_channels = _payload_list(finding, "affected_channels")
                target_text = (
                    f"; target {target_hz:.3f} Hz / bin {target_bin}"
                    if target_hz is not None
                    else ""
                )
                harmonic_text = f"; oddball harmonic {oddball_harmonic}"
                if base_harmonic not in (None, ""):
                    harmonic_text += f" / base harmonic {base_harmonic}"
                target_notch_text = (
                    f"; target notch center(s) {', '.join(notch_centers)} Hz"
                    if notch_centers
                    else ""
                )
                noise_text = (
                    "; required noise collision(s): " + ", ".join(noise_details)
                    if noise_details
                    else ""
                )
                channel_text = (
                    f"; {len(affected_channels)} affected scalp channel(s) "
                    f"({', '.join(affected_channels)})"
                    if affected_channels
                    else ""
                )
                method_text = (
                    f"; method {finding.get('method_version') or '?'} / thresholds "
                    f"{finding.get('threshold_policy_version') or '?'}"
                )
                append_row(
                    result,
                    "Configured line-noise/FPVS collision: "
                    + scope
                    + f"; {classification}"
                    + target_text
                    + harmonic_text
                    + target_notch_text
                    + noise_text
                    + channel_text
                    + method_text
                    + ". The configured line-noise filter stays in place. The affected "
                    "standard frequency metric is unavailable; other valid frequencies "
                    "remain available.",
                    kind="Spectral", title="Line-noise / FPVS collision",
                    finding=finding,
                )
                continue
            channels = _payload_list(finding, "channels")
            frequency = _payload_float(finding, "frequency_hz")
            legacy_score = _payload_float(
                finding,
                "max_legacy_hann_spectrum_score",
            )
            local_ratio = _payload_float(finding, "max_local_ratio")
            local_score = _payload_float(
                finding,
                "max_local_standardized_score",
            )
            fft_bin = finding.get("fft_bin")
            classification = str(
                finding.get("classification") or "unexpected signal"
            ).replace("_", " ")
            widespread = "yes" if finding.get("widespread") else "no"
            harmonic_parts = []
            if finding.get("oddball_harmonic") not in (None, ""):
                harmonic_parts.append(
                    f"oddball harmonic {finding.get('oddball_harmonic')}"
                )
            if finding.get("base_harmonic") not in (None, ""):
                harmonic_parts.append(f"base harmonic {finding.get('base_harmonic')}")
            harmonic_text = (
                "; matched " + " / ".join(harmonic_parts)
                if harmonic_parts
                else "; no canonical harmonic match"
            )
            append_row(
                result,
                f"Experimental raw-spectral signal: {scope}; "
                f"{frequency:.3f} Hz / bin {fft_bin}; {classification}"
                f"{harmonic_text}; {len(channels)} channel(s) "
                f"({', '.join(channels)}); Legacy Hann-spectrum score "
                f"{legacy_score:.3g}; local mean ratio {local_ratio:.3g}; "
                f"local standardized score {local_score:.3g}; widespread {widespread}; "
                f"method {finding.get('method_version') or '?'} / thresholds "
                f"{finding.get('threshold_policy_version') or '?'}. Review only; "
                "the default decision is retain and this check never changes data."
                if None not in (frequency, legacy_score, local_ratio, local_score)
                else f"Experimental raw-spectral signal: {scope}. Review only; "
                "the default decision is retain and this check never changes data.",
                kind="Spectral",
                title=classification.capitalize()
                + (f" ({frequency:g} Hz)" if frequency is not None else ""),
                finding=finding,
            )
        if (
            not result.raw_spectral_review_rows
            and result.raw_spectral_flagged_channels
        ):
            append_row(
                result,
                "Legacy raw-spectral history: "
                + ", ".join(result.raw_spectral_flagged_channels)
                + ". Preserved for review only; it has no current exclusion "
                "authority and does not change data.",
                kind="Spectral", title="Historical spectral flags",
                channels=result.raw_spectral_flagged_channels,
            )
        if result.raw_spectral_evaluation_status == "not_performed_disabled":
            append_row(
                result,
                "Experimental raw-spectral review: Not performed (disabled in "
                "project settings). No prior spectral flag is treated as current.",
                kind="Assessment status", title="Raw-spectral review disabled",
            )
        elif result.raw_spectral_evaluation_status == "not_evaluated":
            detail = result.raw_spectral_message or (
                "No valid analyzed condition span was available."
            )
            append_row(
                result,
                "Experimental raw-spectral review: Not evaluated. " + detail,
                kind="Assessment status", title="Raw-spectral review not evaluated",
            )
    # These extra cues never enter the detector's exclusion/interpolation state.
    # Include them even when the original scan/kurtosis gate has no findings.
    diagnostics_by_file = review_diagnostics_by_file or {}
    pattern_names = {
        "exact_flatline": "Exact flatline",
        "candidate_clipping_plateau": "Candidate clipping plateau",
        "abrupt_jump": "Abrupt transition",
    }
    for result in scan.results:
        if (result.participant_id.casefold() in accepted_hard_exclusions
                or result.identity_id.casefold() in accepted_hard_exclusions):
            continue
        report = diagnostics_by_file.get(str(result.path), {})
        if report.get("status") == "unavailable":
            reason = str(report.get("reason") or "The additional signal diagnostics could not be computed.")
            append_row(
                result,
                f"Additional signal diagnostics unavailable: {reason} "
                "No clean-recording verdict or repair/exclusion decision follows from this unavailable assessment.",
                kind="Assessment status", title="Signal diagnostics unavailable", finding=report,
            )
        omitted = report.get("events_omitted_by_display_limit", 0)
        if isinstance(omitted, int) and not isinstance(omitted, bool) and omitted > 0:
            append_row(
                result,
                f"Display limit: {omitted} additional provisional signal cue(s) are not listed. "
                "The displayed cues are incomplete; inspect the source signal for context. "
                "This does not establish a clean recording or authorize interpolation or exclusion.",
                kind="Assessment status", title="Additional signal cues omitted", finding={
                    "events_omitted_by_display_limit": omitted, "authority": "review_only",
                    "source_identity": report.get("source_identity", {}),
                },
            )
        for event in report.get("localized_events", ()):
            start, stop = event.get("start_s"), event.get("stop_s")
            name = pattern_names.get(str(event.get("kind")), "Signal pattern")
            finding = {
                **event,
                "occurrence_display": int(event.get("occurrence", 0)) + 1,
                "flagged_window_union_spans": [[event.get("start_sample"), event.get("stop_sample")]],
            }
            append_row(
                result,
                f"{name}: {event.get('channel', 'Unknown channel')}, {start}–{stop} s from recording start. "
                f"{event.get('interpretation', '')} Provisional MNE-based review cue; "
                "this does not authorize interpolation or exclusion.",
                kind="Signal patterns", title=name, finding=finding,
            )
    return rows


def _show_suspicious_remainder(
    host: Any,
    scan: PreflightQcScan,
    accepted_hard_exclusions: set[str],
    group_labels: Mapping[str, str],
    *,
    signal_params: Mapping[str, Any] | None = None,
    kurtosis_scan: KurtosisReviewScan | None = None,
) -> bool:
    review_items: list[SignalReviewItem] = []
    rows = _remaining_review_rows(
        scan, accepted_hard_exclusions, group_labels, review_items=review_items,
        review_diagnostics_by_file={
            str(result.path): result.review_diagnostics
            for result in getattr(kurtosis_scan, "results", ())
        },
    )
    if not rows:
        return True

    report_path: Path | None = None
    report_message = ""
    try:
        report_path = _write_preflight_review_flags(host, rows)
        report_message = f"Review flags saved to: {report_path}"
        try:
            host.log(report_message, level=logging.DEBUG)
        except (AttributeError, TypeError, RuntimeError):
            pass
    except OSError as exc:
        logger.exception("Failed to save data quality review flags workbook.")
        report_message = f"Could not save review flags workbook: {exc}"

    _begin_preflight_page(
        host,
        step=_REVIEW_OTHER_FLAGS_STEP,
        title="Review Signal Flags",
        message="Inspect related signal findings together. These review flags do not automatically change data.",
        busy=False,
        review_visible=True,
        review_title="Review Flags",
        progress_visible=False,
    )

    # This step is a review browser, so the shared run-status narrative and
    # full-width evidence table give their space to the summary/detail view.
    container = host.processing_files_card
    panel = SignalReviewPanel(
        review_items, container, amplitude_help_url=BIOSEMI_SHARED_NOISE_HELP_URL
    )

    def inspect_episode(episode: object) -> None:
        from Main_App.gui.qc_signal_viewer import QcSignalViewer
        from Main_App.processing.qc_signal_view import request_from_source

        project_root = getattr(getattr(host, "currentProject", None), "project_root", None)
        source_path = getattr(episode, "source_path", "")
        if not project_root or not source_path:
            return
        indices = getattr(episode, "item_indices", ())
        channels = [review_items[index].channels for index in indices if review_items[index].channels]
        channel = channels[0].split(",")[0].strip() if channels else ""
        source_result = next((result for result in scan.results if str(result.path) == source_path), None)
        event_plan = ((source_result.condition_qc or {}).get("event_plan", {})
                      if source_result is not None else {})
        spans, labels, start_seconds, occurrence_index = episode_view_context(episode, event_plan)
        request = request_from_source(
            source_path, project_root, signal_params or {}, channel=channel,
            spans=spans, span_labels=labels,
        )
        scanned = next((result for result in getattr(kurtosis_scan, "results", ())
                        if str(result.path) == source_path), None)
        unavailable = set()
        if scanned is not None:
            from Main_App.processing.kurtosis_qc import (
                CHANNEL_DECISION_DIRECT, KURTOSIS_DECISION_APPROVE,
            )

            # Current user receipts supersede the scan's pending repair scenario.
            receipts = next((values for recording, values in (signal_params or {}).get(
                KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY, {}).items()
                if str(recording).casefold() == scanned.recording_id.casefold()), {})
            for decision in (scanned.decision_plan or {}).get("channel_decisions", ()):
                name = str(decision.get("channel") or "")
                receipt = receipts.get(name)
                if receipt is not None and decision.get("state") != CHANNEL_DECISION_DIRECT:
                    blocked = receipt.get("decision") == KURTOSIS_DECISION_APPROVE
                else:
                    blocked = bool(decision.get("interpolation_authorized"))
                if name and blocked:
                    unavailable.add(name)
            request = replace(request, diagnostics=scanned.review_diagnostics,
                              source_identity=scanned.source_identity,
                              unusable_channels=tuple(sorted(unavailable)))
        request = replace(request, start_seconds=start_seconds,
                          occurrence_index=occurrence_index or 0)
        QcSignalViewer(request, panel).exec()

    panel.inspect_requested.connect(inspect_episode)
    report_row = ActionRow(panel, alignment=Qt.AlignLeft)
    report_row.setObjectName("signal_review_report_row")
    report_status = QLabel(
        "Workbook saved for later review."
        if report_path is not None
        else "Review workbook could not be saved.",
        report_row,
    )
    report_status.setObjectName("signal_review_report_status")
    report_status.setToolTip(report_message)
    report_status.setWordWrap(True)
    report_row.row_layout.addWidget(report_status, 1)
    open_report = make_action_button("Open Review Workbook", compact=True, parent=report_row)
    open_report.setObjectName("signal_review_open_report")
    open_report.setEnabled(report_path is not None)
    open_report.setToolTip(str(report_path) if report_path is not None else report_message)

    def open_saved_report() -> None:
        if report_path is None:
            return
        try:
            if not report_path.is_file():
                raise OSError("The saved review workbook is no longer available.")
            if not open_path_in_file_manager(report_path):
                raise OSError("No application could open the review workbook.")
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not open review workbook %s: %s", report_path, exc)
            report_status.setText("Could not open workbook. Hover here for details.")
            report_status.setToolTip(f"{exc}\n{report_path}")

    open_report.clicked.connect(open_saved_report)
    report_row.add_button(open_report)
    panel.layout().addWidget(report_row)

    hidden_widgets = (
        host.processing_status_card,
        host.processing_files_title_label,
        host.processing_files_table,
    )
    visibility = [(widget, not widget.isHidden()) for widget in hidden_widgets]
    try:
        for widget, _visible in visibility:
            widget.hide()
        container.layout().addWidget(panel, 1)
        panel.show()
        choice = _await_preflight_choice(
            host,
            (
                ("Continue Processing", "continue", "primary"),
                ("Cancel Processing", "cancel", "secondary"),
            ),
        )
        return choice == "continue"
    finally:
        panel.hide()
        container.layout().removeWidget(panel)
        panel.deleteLater()
        for widget, visible in visibility:
            widget.setVisible(visible)


def _condition_review_scan_identity(
    raw_file_infos: Sequence[Any],
    params: Mapping[str, Any],
) -> tuple[object, ...] | None:
    """Snapshot inputs that can change while the condition review is open."""

    sources = []
    try:
        for info in raw_file_infos:
            path = Path(info.path).resolve()
            stat = path.stat()
            sources.append((str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    except (OSError, TypeError, ValueError):
        # Let the scanner report missing/unreadable files through its normal UI.
        return None
    return (
        tuple(sources),
        normalize_manual_excluded_participant_conditions(
            params.get("manual_excluded_participant_conditions")
        ),
        normalize_manual_excluded_recording_conditions(
            params.get("manual_excluded_recording_conditions")
        ),
        deepcopy(params.get("_fpvs_marker_review_decisions_by_file")),
    )


def run_preprocessing_qc_workflow(
    host: Any,
    raw_file_infos: Sequence[Any],
    params: dict[str, Any],
    *,
    preserve_existing_plans: bool = False,
) -> bool:
    """Run embedded QC, optionally extending an earlier reviewed file set."""

    if not raw_file_infos:
        return True

    existing_event_plans: dict[str, Any] = {}
    existing_header_exclusions: list[str] = []
    if preserve_existing_plans:
        raw_existing_plans = params.get("_fpvs_preflight_event_plans_by_file")
        if isinstance(raw_existing_plans, Mapping):
            existing_event_plans = {
                str(key): dict(value)
                for key, value in raw_existing_plans.items()
                if isinstance(value, Mapping)
            }
        raw_existing_headers = params.get(
            "_fpvs_preflight_recording_not_started_files",
            (),
        )
        if isinstance(raw_existing_headers, str):
            raw_existing_headers = (raw_existing_headers,)
        if isinstance(raw_existing_headers, Sequence):
            existing_header_exclusions = [
                str(value) for value in raw_existing_headers if str(value).strip()
            ]
    else:
        params.pop("_fpvs_preflight_event_plans_by_file", None)
    group_labels = _project_group_labels(host)

    _show_data_quality_notice(
        host,
        "FPVS Toolbox will check your data before processing.",
        "This guided check looks for empty recording files, electrodes that may "
        "have been physically removed before recording, and participant-level "
        "signal problems. You will be asked to confirm anything that could "
        "change what gets processed.",
    )
    _begin_preflight_page(
        host,
        step=None,
        title="Check Raw Files",
        message=_DATA_QUALITY_SCAN_WAIT_MESSAGE,
        busy=True,
        review_visible=False,
        checklist=(
            "Check whether each BDF contains real recording data",
            "Find files created when recording was not started",
            "Prepare the deeper signal-health scan",
        ),
    )
    _set_label(host, "processing_summary_label", "Checking BDF headers...")
    _set_label(
        host,
        "processing_current_file_label",
        "Looking for empty recordings before the deeper data quality scan.",
    )
    header_only = scan_recording_not_started_files(raw_file_infos)
    if header_only and not _confirm_recording_not_started(
        host,
        header_only,
        group_labels,
    ):
        return False
    params["_fpvs_preflight_recording_not_started_files"] = sorted(
        set(existing_header_exclusions).union(_path_strings(header_only)),
        key=str.casefold,
    )
    header_only_keys = {_path_key(item.path) for item in header_only}
    active_infos = [
        info
        for info in raw_file_infos
        if _path_key(Path(info.path)) not in header_only_keys
    ]

    condition_review_identity = _condition_review_scan_identity(active_infos, params)
    scan = _run_scan_embedded(
        host,
        active_infos,
        params,
        skip_paths=[item.path for item in header_only],
        group_labels=group_labels,
    )
    if scan is None or scan.cancelled:
        return False

    prefetch = _start_qc_source_prefetch(host, active_infos, params)
    try:
        scan = _review_marker_occurrences(
            host,
            active_infos,
            params,
            scan,
            group_labels,
        )
        if scan is None or scan.cancelled:
            return False

        if not _confirm_condition_crop_exclusions(
            host,
            params,
            scan,
            group_labels,
        ):
            return False

        # The existing scan already covers unchanged included intervals. If source
        # files, marker decisions, or condition choices changed, rebuild the project-wide result via
        # the recording/occurrence caches before any later detector uses it.
        if (
            condition_review_identity is None
            or condition_review_identity != _condition_review_scan_identity(active_infos, params)
        ):
            scan = _run_scan_embedded(
                host,
                active_infos,
                params,
                skip_paths=(),
                group_labels=group_labels,
            )
            if scan is None or scan.cancelled:
                return False

        if active_infos and not _review_removed_electrodes(
            host,
            active_infos,
            params,
            scan,
            group_labels,
        ):
            return False

        accepted_hard_exclusions = _confirm_hard_exclusions(
            host,
            params,
            scan,
            group_labels,
        )
        try:
            current_event_plans = canonical_event_plans_by_file(scan)
            existing_event_plans.update(current_event_plans)
            params["_fpvs_preflight_event_plans_by_file"] = existing_event_plans
            display_only_raw_qc = _raw_channel_qc_by_recording(scan)
        except (MarkerOccurrenceReviewError, ValueError) as exc:
            _show_marker_review_error(host, str(exc))
            return False

        while True:
            scanned_auto_all = bool(params.get("kurtosis_auto_interpolate_all", False))
            kurtosis_scan = _run_kurtosis_review_scan_embedded(
                host,
                active_infos,
                params,
                reviewed_event_plans_by_file=current_event_plans,
                raw_channel_qc_by_recording=display_only_raw_qc,
                source_prefetch=prefetch.source_prefetch if prefetch is not None else None,
            )
            if kurtosis_scan is None or not _review_kurtosis_findings(
                host,
                params,
                kurtosis_scan,
            ):
                return False
            # An auto-on scan omits valid automatic flags. If review disabled the
            # policy, collect those missing manual choices before processing.
            if not scanned_auto_all or params.get("kurtosis_auto_interpolate_all", False):
                break

        if not _show_suspicious_remainder(
            host,
            scan,
            accepted_hard_exclusions,
            group_labels,
            signal_params=params,
            kurtosis_scan=kurtosis_scan,
        ):
            return False
        return True
    finally:
        _finish_qc_source_prefetch(host, prefetch)


__all__ = ["run_preprocessing_qc_workflow"]
