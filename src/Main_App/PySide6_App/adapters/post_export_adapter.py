# src/Main_App/PySide6_App/adapters/post_export_adapter.py
from __future__ import annotations
from dataclasses import dataclass
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from Main_App.Shared.post_process import post_process as _shared_post_process

logger = logging.getLogger(__name__)


@dataclass
class LegacyCtx:
    """Data-only context for shared post_process (no QWidget, no Qt)."""
    preprocessed_data: Dict[str, Any]
    save_folder_path: Any | None = None  # may expose .get()
    data_paths: List[str] | None = None
    settings: Optional[Any] = None
    log: Optional[Callable[[str], None]] = None


def _normalize_save_folder(save_folder_path: Any) -> Any:
    """
    Ensure adapter exposes save_folder_path.get() -> str path.
    Accepts an object with .get(), a raw str/Path, or raises if missing.
    """
    path_str = ""
    if hasattr(save_folder_path, "get") and callable(getattr(save_folder_path, "get")):
        path_str = str(save_folder_path.get())
    elif save_folder_path is not None:
        path_str = str(save_folder_path)
    else:
        raise RuntimeError("Adapter missing save_folder_path; cannot export outputs.")

    root = Path(path_str).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(
            "post_export_normalize_save_folder_failed",
            extra={"root": str(root), "error": str(e)},
        )
        raise

    logger.debug(
        "post_export_normalize_save_folder",
        extra={"root": str(root)},
    )
    return SimpleNamespace(get=lambda r=root: str(r))


def _build_legacy_shim(ctx: LegacyCtx) -> Any:
    """
    Build minimal 'self' object expected by Legacy post_process.
    Ensures legacy code receives a stable, data-only context.
    """
    log = ctx.log or (lambda _m: None)

    if isinstance(ctx.settings, dict):
        settings_dict: Dict[str, Any] = dict(ctx.settings)
    else:
        settings_dict = {}

    shim = SimpleNamespace(
        preprocessed_data=ctx.preprocessed_data,
        save_folder_path=_normalize_save_folder(ctx.save_folder_path),
        data_paths=list(ctx.data_paths or []),
        settings=settings_dict,
        log=log,
    )

    # Exporting preprocessed FIF files is no longer supported, but legacy
    # branches still expect these attributes to exist.
    settings_dict["save_preprocessed_fif"] = False
    settings_dict["save_condition_fif"] = False
    shim.save_fif_var = SimpleNamespace(get=lambda: False)
    shim.save_condition_fif_var = SimpleNamespace(get=lambda: False)
    shim.save_condition_fif = False

    # Other common knobs
    if not hasattr(shim, "file_mode"):
        shim.file_mode = SimpleNamespace(get=lambda: "Batch")
    if not hasattr(shim, "file_type"):
        shim.file_type = SimpleNamespace(set=lambda _v: None)

    try:
        first_data = shim.data_paths[0] if shim.data_paths else None
        logger.debug(
            "post_export_build_shim",
            extra={
                "save_pref": save_pref,
                "save_folder": shim.save_folder_path.get(),
                "n_labels": len(ctx.preprocessed_data or {}),
                "first_data_path": first_data,
            },
        )
    except Exception:
        logger.debug(
            "post_export_build_shim_logging_failed",
            extra={"data_paths_len": len(shim.data_paths or [])},
        )

    return shim


def run_post_export(ctx: LegacyCtx, labels: List[str]) -> int:
    """
    Execute post-processing exports through the shared migration bridge.
    """
    try:
        logger.info(
            "post_export_start",
            extra={
                "labels": labels,
                "n_labels": len(labels),
                "data_paths": list(ctx.data_paths or []),
            },
        )
    except Exception:
        logger.debug("post_export_start_logging_failed")

    shim = _build_legacy_shim(ctx)

    try:
        save_root_str = shim.save_folder_path.get()
        save_root = Path(save_root_str).resolve()
    except Exception as e:
        # Should not happen given _normalize_save_folder checks, but good for robustness
        shim.log(f"[adapter] Invalid save path: {e}")
        logger.error(
            "post_export_invalid_save_path",
            extra={"error": str(e)},
        )
        raise

    # Run shared post-processing (Excel, etc.)
    try:
        logger.debug(
            "post_export_call_shared",
            extra={"save_root": str(save_root), "labels": labels},
        )
        _shared_post_process(shim, labels)
    except Exception as e:
        shim.log(f"[adapter] post_process failed: {e}")
        logger.error(
            "post_export_failed",
            extra={"error": str(e)},
        )
        raise

    try:
        logger.info(
            "post_export_done",
            extra={
                "save_root": str(save_root),
                "labels": labels,
            },
        )
    except Exception:
        logger.debug(
            "post_export_done_logging_failed",
            extra={"save_root": str(save_root)},
        )

    return 0
