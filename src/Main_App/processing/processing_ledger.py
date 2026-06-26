"""Project-local processing ledger and incremental planning helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from Main_App.processing.processing_controller import RawFileInfo

logger = logging.getLogger(__name__)

PROCESSING_STATE_DIR = ".fpvs_processing"
LEDGER_FILENAME = "processing_ledger.json"
RUNS_FILENAME = "processing_runs.jsonl"
PROCESSING_FINGERPRINT_VERSION = "processing_fingerprint_v6_manual_removed_electrode_qc"
GENERATED_EXCEL_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".xlsb"}
MISSING_EXPECTED_OUTPUTS_WARNING = "missing_expected_outputs"
NO_EXPECTED_OUTPUTS_FAILURE = "no_expected_outputs"


@dataclass(frozen=True)
class ProcessingInputState:
    info: RawFileInfo
    participant_id: str
    status: str
    reason: str
    expected_outputs: tuple[Path, ...]

    @property
    def should_run_incremental(self) -> bool:
        return self.status not in {"completed", "excluded"}


@dataclass(frozen=True)
class ProcessingPlan:
    states: tuple[ProcessingInputState, ...]
    fingerprint: str
    condition_labels: tuple[str, ...]
    choice: str = "incremental"

    @property
    def completed_count(self) -> int:
        return sum(1 for state in self.states if state.status == "completed")

    @property
    def incremental_files(self) -> tuple[Path, ...]:
        return tuple(
            state.info.path for state in self.states if state.should_run_incremental
        )

    @property
    def all_files(self) -> tuple[Path, ...]:
        return tuple(state.info.path for state in self.states)

    @property
    def run_files(self) -> tuple[Path, ...]:
        if self.choice in {"reprocess_all", "reprocess_this_file"}:
            return self.all_files
        return self.incremental_files

    @property
    def stale_count(self) -> int:
        return sum(
            1
            for state in self.states
            if state.status in {"changed_settings", "changed_raw", "missing_outputs"}
        )

    @property
    def new_count(self) -> int:
        return sum(1 for state in self.states if state.status == "new")

    @property
    def excluded_count(self) -> int:
        return sum(1 for state in self.states if state.status == "excluded")


def processing_state_dir(project_root: Path) -> Path:
    return Path(project_root) / PROCESSING_STATE_DIR


def ledger_path(project_root: Path) -> Path:
    return processing_state_dir(project_root) / LEDGER_FILENAME


def runs_path(project_root: Path) -> Path:
    return processing_state_dir(project_root) / RUNS_FILENAME


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _resolved_path_strings(values: Sequence[Any]) -> set[str]:
    resolved: set[str] = set()
    for value in values:
        try:
            resolved.add(str(Path(str(value)).resolve()))
        except (OSError, TypeError, ValueError):
            continue
    return resolved


def _has_missing_condition_warning(entry: Mapping[str, Any]) -> bool:
    return (
        str(entry.get("completion_warning") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
        or str(entry.get("failure_reason") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
        or str(entry.get("condition_completeness") or "").casefold() == "partial"
    )


def _missing_outputs_are_recorded_condition_warning(
    entry: Mapping[str, Any],
    missing_outputs: Sequence[Any],
) -> bool:
    if not _has_missing_condition_warning(entry):
        return False
    current_missing = _resolved_path_strings(missing_outputs)
    recorded_missing = _resolved_path_strings(_string_list(entry.get("missing_outputs")))
    return not recorded_missing or current_missing.issubset(recorded_missing)


def _excel_root(project: Any) -> Path:
    project_root = Path(project.project_root)
    subfolders = getattr(project, "subfolders", {}) or {}
    excel_subfolder = subfolders.get("excel") if isinstance(subfolders, Mapping) else None
    if excel_subfolder:
        root = Path(excel_subfolder)
        return root if root.is_absolute() else project_root / root
    return project_root / "1 - Excel Data Files"


def _condition_folder_name(label: str) -> str:
    return re.sub(
        r"^\d+\s*-\s*",
        "",
        str(label).replace("/", "-").replace("\\", "-").strip(),
    )


def _group_folder_name(project: Any, group_id: str | None) -> str | None:
    if not group_id:
        return None
    groups = getattr(project, "groups", {}) or {}
    if not isinstance(groups, Mapping):
        return None
    entry = groups.get(group_id)
    if not isinstance(entry, Mapping):
        return group_id
    folder_name = str(entry.get("folder_name") or entry.get("label") or group_id).strip()
    return folder_name or group_id


def _expected_excel_paths(
    project: Any,
    info: RawFileInfo,
    condition_labels: Sequence[str],
) -> tuple[Path, ...]:
    root = _excel_root(project)
    paths: list[Path] = []
    for label in condition_labels:
        condition_folder = _condition_folder_name(label)
        file_name = f"{info.subject_id}_{condition_folder}_Results.xlsx"
        group_folder = _group_folder_name(project, info.group)
        output_folder = root / condition_folder
        if group_folder:
            output_folder = output_folder / group_folder
        paths.append((output_folder / file_name).resolve())
    return tuple(paths)


def _condition_labels_for_missing_outputs(
    plan: ProcessingPlan,
    state: ProcessingInputState,
    missing_outputs: Sequence[Any],
) -> list[str]:
    missing = _resolved_path_strings(missing_outputs)
    labels: list[str] = []
    for index, output_path in enumerate(state.expected_outputs):
        if str(output_path.resolve()) not in missing:
            continue
        if index < len(plan.condition_labels):
            labels.append(str(plan.condition_labels[index]))
        else:
            labels.append(output_path.parent.name)
    return labels


def raw_file_metadata(file_path: Path) -> dict[str, Any]:
    stat = Path(file_path).stat()
    return {
        "raw_file": str(Path(file_path).resolve()),
        "raw_size": int(stat.st_size),
        "raw_mtime_ns": int(stat.st_mtime_ns),
    }


def build_processing_fingerprint(
    project: Any,
    settings: Mapping[str, Any],
    event_map: Mapping[str, int],
) -> str:
    payload = {
        "version": PROCESSING_FINGERPRINT_VERSION,
        "settings": dict(settings),
        "event_map": {str(key): int(value) for key, value in event_map.items()},
        "project_preprocessing": getattr(project, "preprocessing", {}) or {},
        "project_options": getattr(project, "options", {}) or {},
        "project_subfolders": getattr(project, "subfolders", {}) or {},
        "project_groups": getattr(project, "groups", {}) or {},
    }
    encoded = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path(project_root)
    if not path.exists():
        return {"schema_version": 1, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("processing_ledger_unreadable", extra={"path": str(path)})
        return {"schema_version": 1, "entries": {}}
    if not isinstance(data, dict):
        return {"schema_version": 1, "entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        data["entries"] = {}
    data.setdefault("schema_version", 1)
    return data


def save_ledger(project_root: Path, ledger: Mapping[str, Any]) -> None:
    state_dir = processing_state_dir(project_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_path(project_root)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(ledger, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


def append_run_log(project_root: Path, record: Mapping[str, Any]) -> None:
    state_dir = processing_state_dir(project_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("timestamp", _now_iso())
    with runs_path(project_root).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def classify_processing_inputs(
    project: Any,
    files: Sequence[RawFileInfo],
    settings: Mapping[str, Any],
    event_map: Mapping[str, int],
) -> ProcessingPlan:
    condition_labels = tuple(str(label) for label in event_map.keys())
    fingerprint = build_processing_fingerprint(project, settings, event_map)
    ledger = load_ledger(Path(project.project_root))
    entries = ledger.get("entries", {})
    if not isinstance(entries, Mapping):
        entries = {}

    states: list[ProcessingInputState] = []
    for info in files:
        participant_id = info.subject_id
        expected_outputs = _expected_excel_paths(project, info, condition_labels)
        entry = entries.get(participant_id)
        raw_meta = raw_file_metadata(info.path)
        if not isinstance(entry, Mapping):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="new",
                    reason="No completed ledger entry exists.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        entry_status = str(entry.get("status") or "incomplete")
        if entry_status == "excluded":
            if (
                entry.get("raw_file") != raw_meta["raw_file"]
                or entry.get("raw_size") != raw_meta["raw_size"]
                or entry.get("raw_mtime_ns") != raw_meta["raw_mtime_ns"]
            ):
                states.append(
                    ProcessingInputState(
                        info=info,
                        participant_id=participant_id,
                        status="changed_raw",
                        reason="Previously excluded raw file changed.",
                        expected_outputs=expected_outputs,
                    )
                )
                continue

            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="excluded",
                    reason=str(
                        entry.get("exclusion_message")
                        or entry.get("exclusion_reason")
                        or "Raw file was excluded from processing."
                    ),
                    expected_outputs=expected_outputs,
                )
            )
            continue

        present_outputs_now = [path for path in expected_outputs if path.exists()]
        missing_outputs_now = [path for path in expected_outputs if not path.exists()]
        legacy_partial_condition_entry = (
            entry_status == "failed"
            and bool(present_outputs_now)
            and bool(missing_outputs_now)
        )
        if (
            entry_status != "completed"
            and not _has_missing_condition_warning(entry)
            and not legacy_partial_condition_entry
        ):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="missing_outputs",
                    reason=f"Ledger entry is {entry_status}, not completed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if entry.get("processing_fingerprint_version") != PROCESSING_FINGERPRINT_VERSION:
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_settings",
                    reason="Processing fingerprint version changed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if entry.get("processing_fingerprint") != fingerprint:
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_settings",
                    reason="Project processing settings changed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if (
            entry.get("raw_file") != raw_meta["raw_file"]
            or entry.get("raw_size") != raw_meta["raw_size"]
            or entry.get("raw_mtime_ns") != raw_meta["raw_mtime_ns"]
        ):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_raw",
                    reason="Raw file path, size, or mtime changed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        missing_outputs = missing_outputs_now
        if missing_outputs:
            if (
                _missing_outputs_are_recorded_condition_warning(entry, missing_outputs)
                or legacy_partial_condition_entry
            ):
                states.append(
                    ProcessingInputState(
                        info=info,
                        participant_id=participant_id,
                        status="completed",
                        reason=(
                            "Available condition outputs are completed; missing "
                            "condition outputs are flagged in QC."
                        ),
                        expected_outputs=expected_outputs,
                    )
                )
                continue
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="missing_outputs",
                    reason="Expected Excel output files are missing.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        states.append(
            ProcessingInputState(
                info=info,
                participant_id=participant_id,
                status="completed",
                reason="Ledger and expected Excel outputs match.",
                expected_outputs=expected_outputs,
            )
        )
    return ProcessingPlan(states=tuple(states), fingerprint=fingerprint, condition_labels=condition_labels)


def with_processing_choice(plan: ProcessingPlan, choice: str) -> ProcessingPlan:
    return ProcessingPlan(
        states=plan.states,
        fingerprint=plan.fingerprint,
        condition_labels=plan.condition_labels,
        choice=choice,
    )


def output_group_folder_by_file(
    project: Any,
    files: Sequence[RawFileInfo],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for info in files:
        group_folder = _group_folder_name(project, info.group)
        if group_folder:
            mapping[str(info.path.resolve())] = group_folder
    return mapping


def _assert_under_excel_root(excel_root: Path, path: Path) -> Path:
    root = excel_root.resolve()
    target = path.resolve()
    if target == root or root in target.parents:
        return target
    raise ValueError(f"Refusing to delete unmanaged Excel output path: {target}")


def clean_managed_excel_root(project: Any) -> Path:
    root = _excel_root(project).resolve()
    project_root = Path(project.project_root).resolve()
    if root == project_root or root.parent == root:
        raise ValueError(f"Refusing to delete unsafe Excel output root: {root}")
    if root.exists():
        try:
            candidates = [
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in GENERATED_EXCEL_SUFFIXES
            ]
        except OSError as exc:
            raise RuntimeError(
                "Unable to scan the managed Excel output folder for cleanup. "
                f"Check OneDrive sync/permissions for: {root}. Original error: {exc}"
            ) from exc
        for path in candidates:
            try:
                path.unlink()
            except PermissionError as exc:
                raise RuntimeError(
                    "Unable to remove an existing Excel output file. Close it in Excel "
                    f"and pause OneDrive sync if needed, then retry: {path}"
                ) from exc
            except OSError as exc:
                raise RuntimeError(
                    f"Unable to remove existing Excel output file: {path}. "
                    f"Original error: {exc}"
                ) from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def clean_participant_outputs(project: Any, plan: ProcessingPlan) -> list[Path]:
    root = _excel_root(project).resolve()
    deleted: list[Path] = []
    run_files = {path.resolve() for path in plan.run_files}
    for state in plan.states:
        if state.info.path.resolve() not in run_files or state.status == "new":
            continue
        for expected_output in state.expected_outputs:
            target = _assert_under_excel_root(root, expected_output)
            if target.exists():
                target.unlink()
                deleted.append(target)
    return deleted


def _remove_expected_outputs_for_state(project: Any, state: ProcessingInputState) -> list[str]:
    root = _excel_root(project).resolve()
    removed: list[str] = []
    for expected_output in state.expected_outputs:
        target = _assert_under_excel_root(root, expected_output)
        if not target.exists():
            continue
        try:
            target.unlink()
        except OSError as exc:
            logger.warning(
                "excluded_output_cleanup_failed",
                extra={"path": str(target), "participant_id": state.participant_id, "error": str(exc)},
            )
            continue
        removed.append(str(target))
    return removed


def _info_by_resolved_path(plan: ProcessingPlan) -> dict[Path, ProcessingInputState]:
    return {state.info.path.resolve(): state for state in plan.states}


def record_processing_results(
    project: Any,
    plan: ProcessingPlan,
    results: Sequence[Mapping[str, Any]],
    *,
    run_mode: str,
    user_choice: str,
    cancelled: bool,
) -> None:
    project_root = Path(project.project_root)
    ledger = load_ledger(project_root)
    entries = ledger.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        ledger["entries"] = entries

    states_by_path = _info_by_resolved_path(plan)
    successful_paths: set[Path] = set()
    partial_condition_paths: set[Path] = set()
    excluded_by_path: dict[Path, Mapping[str, Any]] = {}
    no_output_failures_by_path: dict[Path, dict[str, Any]] = {}
    for result in results:
        if result.get("status") == "excluded":
            raw_path_value = result.get("file")
            if raw_path_value:
                excluded_by_path[Path(str(raw_path_value)).resolve()] = result
            continue
        if result.get("status") != "ok":
            continue
        raw_path_value = result.get("file")
        if not raw_path_value:
            continue
        raw_path = Path(str(raw_path_value)).resolve()
        state = states_by_path.get(raw_path)
        if state is None:
            continue
        missing_outputs = [
            str(path) for path in state.expected_outputs if not path.exists()
        ]
        present_outputs = [
            str(path) for path in state.expected_outputs if path.exists()
        ]
        missing_condition_labels = _condition_labels_for_missing_outputs(
            plan,
            state,
            missing_outputs,
        )
        if missing_outputs and not present_outputs:
            no_output_failures_by_path[raw_path] = {
                "result": result,
                "missing_outputs": missing_outputs,
                "missing_condition_labels": missing_condition_labels,
            }
            continue
        if missing_outputs:
            partial_condition_paths.add(raw_path)
        successful_paths.add(raw_path)
        raw_meta = raw_file_metadata(state.info.path)
        audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
        raw_qc_bad_channels = _string_list(audit.get("raw_qc_bad_channels"))
        raw_qc_low_variance_channels = _string_list(
            audit.get("raw_qc_low_variance_channels")
        )
        raw_qc_high_amplitude_channels = _string_list(
            audit.get("raw_qc_high_amplitude_channels")
        )
        raw_qc_spatial_outlier_channels = _string_list(
            audit.get("raw_qc_spatial_outlier_channels")
        )
        raw_qc_manual_removed_channels = _string_list(
            audit.get("raw_qc_manual_removed_channels")
        )
        raw_qc_warning_rules = _string_list(audit.get("raw_qc_warning_rules"))
        kurtosis_bad_channels = _string_list(audit.get("kurtosis_bad_channels"))
        interpolated_channels = _string_list(
            audit.get("interpolated_channels")
        ) or list(kurtosis_bad_channels)
        n_rejected = _int_or_default(audit.get("n_rejected"), len(kurtosis_bad_channels))
        entries[state.participant_id] = {
            "participant_id": state.participant_id,
            "group_id": state.info.group,
            **raw_meta,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
            "expected_outputs": [str(path) for path in state.expected_outputs],
            "status": "completed",
            "completed_at": _now_iso(),
            "run_mode": run_mode,
            "raw_qc_bad_channels": raw_qc_bad_channels,
            "raw_qc_low_variance_channels": raw_qc_low_variance_channels,
            "raw_qc_high_amplitude_channels": raw_qc_high_amplitude_channels,
            "raw_qc_spatial_outlier_channels": raw_qc_spatial_outlier_channels,
            "raw_qc_manual_removed_channels": raw_qc_manual_removed_channels,
            "raw_qc_warning_rules": raw_qc_warning_rules,
            "kurtosis_bad_channels": kurtosis_bad_channels,
            "interpolated_channels": interpolated_channels,
            "n_rejected": n_rejected,
            "condition_completeness": "partial" if missing_outputs else "complete",
            "completion_warning": (
                MISSING_EXPECTED_OUTPUTS_WARNING if missing_outputs else None
            ),
            "missing_outputs": missing_outputs,
            "missing_condition_labels": missing_condition_labels,
            "present_outputs": present_outputs,
        }

    run_files = {path.resolve() for path in plan.run_files}
    excluded_paths = set(excluded_by_path) & run_files
    for raw_path in sorted(run_files - successful_paths):
        state = states_by_path.get(raw_path)
        if state is None:
            continue
        excluded_result = excluded_by_path.get(raw_path)
        if excluded_result is not None:
            removed_outputs = _remove_expected_outputs_for_state(project, state)
            qc_payload = (
                excluded_result.get("raw_channel_qc")
                if isinstance(excluded_result.get("raw_channel_qc"), Mapping)
                else {}
            )
            raw_qc_bad_channels = _string_list(qc_payload.get("bad_channels"))
            raw_qc_low_variance_channels = _string_list(
                qc_payload.get("low_variance_channels")
            )
            raw_qc_high_amplitude_channels = _string_list(
                qc_payload.get("high_amplitude_channels")
            )
            raw_qc_spatial_outlier_channels = _string_list(
                qc_payload.get("spatial_outlier_channels")
            )
            raw_qc_manual_removed_channels = _string_list(
                qc_payload.get("manual_removed_channels")
            )
            raw_qc_warning_rules = _string_list(qc_payload.get("warning_rules"))
            n_rejected = _int_or_default(
                qc_payload.get("n_bad_channels"),
                len(raw_qc_bad_channels),
            )
            entries[state.participant_id] = {
                "participant_id": state.participant_id,
                "group_id": state.info.group,
                **raw_file_metadata(state.info.path),
                "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                "processing_fingerprint": plan.fingerprint,
                "expected_outputs": [str(path) for path in state.expected_outputs],
                "status": "excluded",
                "completed_at": None,
                "run_mode": run_mode,
                "exclusion_reason": str(excluded_result.get("reason") or "excluded"),
                "exclusion_message": str(
                    excluded_result.get("message") or "Raw file was excluded from processing."
                ),
                "excluded_at": _now_iso(),
                "removed_outputs": removed_outputs,
                "raw_qc_bad_channels": raw_qc_bad_channels,
                "raw_qc_low_variance_channels": raw_qc_low_variance_channels,
                "raw_qc_high_amplitude_channels": raw_qc_high_amplitude_channels,
                "raw_qc_spatial_outlier_channels": raw_qc_spatial_outlier_channels,
                "raw_qc_manual_removed_channels": raw_qc_manual_removed_channels,
                "raw_qc_warning_rules": raw_qc_warning_rules,
                "kurtosis_bad_channels": [],
                "interpolated_channels": [],
                "n_rejected": n_rejected,
            }
            continue
        no_output_failure = no_output_failures_by_path.get(raw_path)
        if no_output_failure is not None:
            result = (
                no_output_failure.get("result")
                if isinstance(no_output_failure.get("result"), Mapping)
                else {}
            )
            audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
            raw_qc_bad_channels = _string_list(audit.get("raw_qc_bad_channels"))
            raw_qc_low_variance_channels = _string_list(
                audit.get("raw_qc_low_variance_channels")
            )
            raw_qc_high_amplitude_channels = _string_list(
                audit.get("raw_qc_high_amplitude_channels")
            )
            raw_qc_spatial_outlier_channels = _string_list(
                audit.get("raw_qc_spatial_outlier_channels")
            )
            raw_qc_manual_removed_channels = _string_list(
                audit.get("raw_qc_manual_removed_channels")
            )
            raw_qc_warning_rules = _string_list(audit.get("raw_qc_warning_rules"))
            kurtosis_bad_channels = _string_list(audit.get("kurtosis_bad_channels"))
            interpolated_channels = _string_list(
                audit.get("interpolated_channels")
            ) or list(kurtosis_bad_channels)
            n_rejected = _int_or_default(
                audit.get("n_rejected"),
                len(interpolated_channels) or len(kurtosis_bad_channels),
            )
            missing_outputs = [
                str(path) for path in no_output_failure.get("missing_outputs", [])
            ]
            missing_condition_labels = [
                str(label)
                for label in no_output_failure.get("missing_condition_labels", [])
            ]
            entries[state.participant_id] = {
                "participant_id": state.participant_id,
                "group_id": state.info.group,
                **raw_file_metadata(state.info.path),
                "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                "processing_fingerprint": plan.fingerprint,
                "expected_outputs": [str(path) for path in state.expected_outputs],
                "status": "failed",
                "completed_at": None,
                "run_mode": run_mode,
                "failure_reason": NO_EXPECTED_OUTPUTS_FAILURE,
                "failure_message": (
                    "Processing did not produce any expected Excel condition outputs; "
                    "no condition-level workbooks are available for this participant."
                ),
                "missing_outputs": missing_outputs,
                "missing_condition_labels": missing_condition_labels,
                "removed_outputs": [],
                "raw_qc_bad_channels": raw_qc_bad_channels,
                "raw_qc_low_variance_channels": raw_qc_low_variance_channels,
                "raw_qc_high_amplitude_channels": raw_qc_high_amplitude_channels,
                "raw_qc_spatial_outlier_channels": raw_qc_spatial_outlier_channels,
                "raw_qc_manual_removed_channels": raw_qc_manual_removed_channels,
                "raw_qc_warning_rules": raw_qc_warning_rules,
                "kurtosis_bad_channels": kurtosis_bad_channels,
                "interpolated_channels": interpolated_channels,
                "n_rejected": n_rejected,
            }
            continue
        removed_outputs = _remove_expected_outputs_for_state(project, state)
        entries[state.participant_id] = {
            "participant_id": state.participant_id,
            "group_id": state.info.group,
            **raw_file_metadata(state.info.path),
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
            "expected_outputs": [str(path) for path in state.expected_outputs],
            "status": "incomplete" if cancelled else "failed",
            "completed_at": None,
            "run_mode": run_mode,
            "removed_outputs": removed_outputs,
            "raw_qc_bad_channels": [],
            "raw_qc_low_variance_channels": [],
            "raw_qc_high_amplitude_channels": [],
            "raw_qc_spatial_outlier_channels": [],
            "raw_qc_manual_removed_channels": [],
            "raw_qc_warning_rules": [],
            "kurtosis_bad_channels": [],
            "interpolated_channels": [],
            "n_rejected": 0,
        }

    save_ledger(project_root, ledger)

    if getattr(project, "groups", {}) and not getattr(project, "groups_locked", False):
        project.groups_locked = True
        project.groups_locked_at = _now_iso()
        project.save()

    append_run_log(
        project_root,
        {
            "run_mode": run_mode,
            "user_choice": user_choice,
            "cancelled": cancelled,
            "total_files": len(plan.states),
            "run_files": len(plan.run_files),
            "completed_before": plan.completed_count,
            "new_files": plan.new_count,
            "stale_files": plan.stale_count,
            "successful_files": len(successful_paths),
            "excluded_files": len(excluded_paths),
            "failed_files": max(0, len(run_files - successful_paths - excluded_paths)),
            "condition_warning_files": len(partial_condition_paths),
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
        },
    )
