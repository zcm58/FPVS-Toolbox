"""Project-local processing ledger and incremental planning helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from Main_App.processing.processing_controller import RawFileInfo

logger = logging.getLogger(__name__)

PROCESSING_STATE_DIR = ".fpvs_processing"
LEDGER_FILENAME = "processing_ledger.json"
RUNS_FILENAME = "processing_runs.jsonl"
PROCESSING_FINGERPRINT_VERSION = "processing_fingerprint_v1"


@dataclass(frozen=True)
class ProcessingInputState:
    info: RawFileInfo
    participant_id: str
    status: str
    reason: str
    expected_outputs: tuple[Path, ...]

    @property
    def should_run_incremental(self) -> bool:
        return self.status != "completed"


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


def _excel_root(project: Any) -> Path:
    subfolders = getattr(project, "subfolders", {}) or {}
    excel_subfolder = subfolders.get("excel") if isinstance(subfolders, Mapping) else None
    if excel_subfolder:
        return Path(excel_subfolder)
    return Path(project.project_root) / "1 - Excel Data Files"


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

        if entry.get("status") != "completed":
            status = str(entry.get("status") or "incomplete")
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="missing_outputs",
                    reason=f"Ledger entry is {status}, not completed.",
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

        missing_outputs = [path for path in expected_outputs if not path.exists()]
        if missing_outputs:
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
        shutil.rmtree(root)
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
    for result in results:
        if result.get("status") != "ok":
            continue
        raw_path_value = result.get("file")
        if not raw_path_value:
            continue
        raw_path = Path(str(raw_path_value)).resolve()
        state = states_by_path.get(raw_path)
        if state is None:
            continue
        if any(not path.exists() for path in state.expected_outputs):
            continue
        successful_paths.add(raw_path)
        raw_meta = raw_file_metadata(state.info.path)
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
        }

    run_files = {path.resolve() for path in plan.run_files}
    for raw_path in sorted(run_files - successful_paths):
        state = states_by_path.get(raw_path)
        if state is None:
            continue
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
            "failed_files": max(0, len(run_files - successful_paths)),
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
        },
    )
