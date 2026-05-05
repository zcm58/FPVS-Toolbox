"""Diagnostic helper for auditing missing batch-processing results.

The script mimics the PySide6 multiprocessing pipeline without touching the
core implementation.  It loads a project, iterates over a predefined list of
.bdf files, and reports whether loading and preprocessing succeed for each
file.

Usage
-----
Pass the target project directory on the command line or set
``FPVS_DEBUG_PROJECT_ROOT``::

    python scripts/manual_diagnostics/audit_missing_results.py C:/Data/MyProject

The output lists, for every target file, whether the file exists on disk, the
stage that failed (if any), and a short error/traceback summary.
"""

from __future__ import annotations

import argparse
import os
import sys
import types
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Ensure that src/ is on sys.path so backend modules that do
# absolute imports like "import Main_App" can resolve correctly.
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))


def _ensure_pyside6_stubs() -> None:
    """Install minimal PySide6 stubs so backend imports work without Qt."""

    if "PySide6" in sys.modules:
        return

    class _QCoreApplication:
        _org = ""
        _app = ""

        @staticmethod
        def instance() -> None:
            return None

        @staticmethod
        def setOrganizationName(name: str) -> None:
            _QCoreApplication._org = name

        @staticmethod
        def setApplicationName(name: str) -> None:
            _QCoreApplication._app = name

    class _QStandardPaths:
        AppDataLocation = 0

        @staticmethod
        def writableLocation(_role: int) -> str:
            return ""

    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QCoreApplication = _QCoreApplication
    qtcore.QStandardPaths = _QStandardPaths

    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore


_ensure_pyside6_stubs()

try:
    from Main_App.io.load_utils import load_eeg_file
    from Main_App.processing.preprocess import perform_preprocessing
    from Main_App.projects.project import Project
    from Main_App.projects.preprocessing_settings import (
        normalize_preprocessing_settings,
    )
    BACKEND_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - dependency missing in diagnostics env
    load_eeg_file = perform_preprocessing = Project = normalize_preprocessing_settings = None  # type: ignore
    BACKEND_IMPORT_ERROR = exc

# ---------------------------------------------------------------------------
# Target files
# ---------------------------------------------------------------------------

# Configure recording filenames privately before running this manual diagnostic.
TARGET_FILES = []

DEFAULT_PROJECT_ROOT = os.environ.get("FPVS_DEBUG_PROJECT_ROOT")


def _parse_project_root(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        description="Audit missing batch-processing results for a project directory."
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=DEFAULT_PROJECT_ROOT,
        help="Path to the project directory. Defaults to FPVS_DEBUG_PROJECT_ROOT if set.",
    )
    args = parser.parse_args(argv)
    if not args.project_root:
        parser.error(
            "project_root is required. Pass it on the command line or set FPVS_DEBUG_PROJECT_ROOT."
        )
    return Path(args.project_root).expanduser().resolve()


# ---------------------------------------------------------------------------
# Lightweight shims replicating the GUI environment
# ---------------------------------------------------------------------------


class _SettingsShim:
    """Provide ``settings.get(section, key, default)`` used by the loader."""

    def __init__(self, data: Optional[Dict[str, Dict[str, object]]] = None) -> None:
        self._data = data or {}

    def get(self, section: str, key: str, default: object | None = None) -> object | None:
        section_map = self._data.get(section, {})
        return section_map.get(key, default)


@dataclass
class _AppShim:
    """Mimic the minimal interface that :func:`load_eeg_file` expects."""

    project: Optional[Project]
    settings_map: Dict[str, Dict[str, object]]
    logs: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.settings = _SettingsShim(self.settings_map)
        self.currentProject = self.project

    def log(self, message: str) -> None:
        self.logs.append(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_params(project: Project) -> Dict[str, object]:
    """Return preprocessing parameters identical to the GUI pipeline."""

    normalized = normalize_preprocessing_settings(project.preprocessing)
    epoch_start = float(normalized.get("epoch_start_s", -1.0))
    epoch_end = float(normalized.get("epoch_end_s", 125.0))

    params: Dict[str, object] = {
        "low_pass": float(normalized.get("low_pass")),
        "high_pass": float(normalized.get("high_pass")),
        "downsample": int(normalized.get("downsample")),
        "downsample_rate": int(normalized.get("downsample")),
        "reject_thresh": float(normalized.get("rejection_z")),
        "ref_channel1": normalized.get("ref_chan1") or "EXG1",
        "ref_channel2": normalized.get("ref_chan2") or "EXG2",
        "max_idx_keep": int(normalized.get("max_chan_idx_keep")),
        "max_bad_channels_alert_thresh": int(normalized.get("max_bad_chans")),
        "epoch_start": epoch_start,
        "epoch_end": epoch_end,
        "stim_channel": normalized.get("stim_channel"),
        "save_preprocessed_fif": bool(normalized.get("save_preprocessed_fif", False)),
    }
    return params


def _settings_payload(params: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    """Build sections consumed by the loader's ``_resolve_*`` helpers."""

    preprocessing_section = {
        "ref_channel1": params.get("ref_channel1"),
        "ref_channel2": params.get("ref_channel2"),
    }
    stim_section = {"channel": params.get("stim_channel")}
    return {"preprocessing": preprocessing_section, "stim": stim_section}


def _format_traceback_head(tb: str, max_lines: int = 5) -> str:
    lines = [line.rstrip() for line in tb.strip().splitlines()[:max_lines]]
    return " | ".join(lines)


def _summarize_logs(logs: Iterable[str]) -> str:
    for entry in reversed(list(logs)):
        if entry.startswith("!!! Load Error"):
            return entry
    return ""


def _diagnose_file(
    project: Project,
    params: Dict[str, object],
    file_path: Path,
) -> Dict[str, object]:
    """Run load + preprocess for ``file_path`` and capture diagnostics."""

    summary: Dict[str, object] = {
        "file": file_path.name,
        "exists_on_disk": file_path.exists(),
    }
    if not summary["exists_on_disk"]:
        summary.update({"status": "missing", "message": "File not found on disk."})
        return summary

    app = _AppShim(project, _settings_payload(params))
    ref_pair: Tuple[str, str] = (
        str(params.get("ref_channel1") or "EXG1"),
        str(params.get("ref_channel2") or "EXG2"),
    )

    try:
        raw = load_eeg_file(app, str(file_path), ref_pair=ref_pair)
    except Exception as exc:  # pragma: no cover - defensive guard
        tb = traceback.format_exc()
        summary.update(
            {
                "status": "load_failed",
                "loader_error": f"Exception escaped loader: {exc}",
                "traceback_head": _format_traceback_head(tb),
                "logs": list(app.logs),
            }
        )
        return summary

    if raw is None:
        summary.update(
            {
                "status": "load_failed",
                "loader_error": _summarize_logs(app.logs) or "load_eeg_file returned None",
                "logs": list(app.logs),
            }
        )
        return summary

    try:
        processed, n_rejected = perform_preprocessing(
            raw_input=raw,
            params=params,
            log_func=app.log,
            filename_for_log=file_path.name,
        )
    except Exception as exc:
        tb = traceback.format_exc()
        summary.update(
            {
                "status": "preproc_failed",
                "preproc_error": str(exc),
                "traceback_head": _format_traceback_head(tb),
                "logs": list(app.logs),
            }
        )
        return summary

    if processed is None:
        summary.update(
            {
                "status": "preproc_failed",
                "preproc_error": "perform_preprocessing returned None",
                "logs": list(app.logs),
            }
        )
        return summary

    # Success: collect metadata for downstream debugging.
    info = processed.info
    meta = {
        "status": "ok",
        "sfreq": float(info.get("sfreq", 0.0)),
        "n_channels": len(info.get("ch_names", [])),
        "n_rejected": int(n_rejected or 0),
    }
    summary.update(meta)
    summary["logs"] = list(app.logs)
    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    project_root = _parse_project_root(argv)

    if BACKEND_IMPORT_ERROR is not None:
        print("ERROR: Could not import PySide6 backend modules.")
        print(f"Reason: {BACKEND_IMPORT_ERROR}")
        for name in TARGET_FILES:
            print(f"FILE {name}:")
            print("  exists_on_disk: False (dependencies unavailable)")
            print("  status: \"dependency_missing\"")
        return

    print(f"PROJECT_ROOT: {project_root}")
    if not project_root.exists():
        print("WARNING: Project root does not exist.")
        for name in TARGET_FILES:
            print(f"FILE {name}:")
            print("  exists_on_disk: False (project root missing)")
            print("  status: \"project_not_found\"")
        return

    try:
        project = Project.load(project_root)
    except Exception as exc:  # pragma: no cover - defensive guard
        tb = traceback.format_exc()
        print(f"ERROR: Failed to load project at {project_root}: {exc}")
        print(_format_traceback_head(tb))
        return

    params = _build_params(project)
    input_dir = Path(project.input_folder)
    print(f"Input folder: {input_dir}")

    for name in TARGET_FILES:
        path = input_dir / name
        result = _diagnose_file(project, params, path)
        print(f"FILE {name}:")
        print(f"  exists_on_disk: {result.get('exists_on_disk')}")
        print(f"  status: \"{result.get('status', 'unknown')}\"")
        if "loader_error" in result:
            print(f"  loader_error: {result['loader_error']}")
        if "preproc_error" in result:
            print(f"  preproc_error: {result['preproc_error']}")
        if "traceback_head" in result:
            print(f"  traceback_head: {result['traceback_head']}")
        if result.get("status") == "ok":
            print(
                "  metadata: {sfreq:.3f} Hz | {n_channels} channels | "
                "kurtosis_rejected={n_rejected}".format(**result)
            )
        if result.get("logs"):
            print("  log_tail:")
            for line in result["logs"][-3:]:
                print(f"    {line}")


if __name__ == "__main__":
    main()
