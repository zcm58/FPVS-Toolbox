# src/Main_App/PySide6_App/adapters/post_export_adapter.py
from __future__ import annotations
from dataclasses import dataclass
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from Main_App.Legacy_App.post_process import post_process as _legacy_post_process

logger = logging.getLogger(__name__)


@dataclass
class LegacyCtx:
    """Data-only context for legacy post_process (no QWidget, no Qt)."""
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


def _extract_setting(settings: Any, key: str, default: Any = None) -> Any:
    """
    Helper to safely extract settings from dict, object with .get(), or attribute.
    """
    if settings is None:
        return default

    # 1. Try dict access
    if isinstance(settings, dict):
        return settings.get(key, default)

    # 2. Try .get() method
    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except (TypeError, KeyError):
            pass

    # 3. Try direct attribute access
    if hasattr(settings, key):
        return getattr(settings, key)

    return default


def _build_legacy_shim(ctx: LegacyCtx) -> Any:
    """
    Build minimal 'self' object expected by Legacy post_process.
    Guarantees FIF-saving toggles exist and are ON.
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

    # Use helper to get preference, force defaults
    save_pref = _coerce_bool(
        _extract_setting(ctx.settings, "save_preprocessed_fif"),
        default=False
    )

    settings_dict["save_preprocessed_fif"] = save_pref
    settings_dict["save_condition_fif"] = save_pref

    # FIF toggles some legacy branches check
    shim.save_fif_var = SimpleNamespace(get=lambda val=save_pref: val)
    shim.save_condition_fif_var = SimpleNamespace(get=lambda val=save_pref: val)
    shim.save_condition_fif = save_pref

    # Other common knobs
    if not hasattr(shim, "run_loreta_var") or not hasattr(getattr(shim, "run_loreta_var"), "get"):
        shim.run_loreta_var = SimpleNamespace(get=lambda: False)
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


def _legacy_like_fname(base_stem: str, label: str) -> str:
    """
    Match legacy naming: <base>_<label_sanitized>-epo.fif
    Uses regex to remove all illegal characters for Windows/Linux/Mac compatibility.
    """
    safe_label = label.replace(" ", "_")
    # Remove invalid chars: \ / : * ? " < > |
    safe_label = re.sub(r'[\\/*?:"<>|]', '_', safe_label)
    return f"{base_stem}_{safe_label}-epo.fif"


def _write_missing_fifs(ctx: LegacyCtx, save_root: Path, labels: List[str]) -> int:
    """
    Per-file fallback: for each expected FIF path, write it only if missing.
    Preserves legacy structure:
      <save_root>/.fif files/<Label>/<base>_<Label_underscored>-epo.fif
    """
    try:
        import mne  # noqa: F401  # local import in worker
    except Exception:
        logger.debug(
            "post_export_write_missing_fifs_mne_import_failed",
            extra={"save_root": str(save_root)},
        )
        return 0

    written = 0

    # Use helper for robust extraction
    save_pref = _coerce_bool(
        _extract_setting(ctx.settings, "save_preprocessed_fif"),
        default=False
    )

    # Robust base_stem extraction
    data_paths = ctx.data_paths or ["unknown"]
    if not data_paths:
        data_paths = ["unknown"]
    base_stem = Path(str(data_paths[0])).stem

    logger.debug(
        "post_export_write_missing_fifs_start",
        extra={
            "save_root": str(save_root),
            "base_stem": base_stem,
            "labels": labels,
            "save_pref": save_pref,
        },
    )

    for label in labels:
        ep_list = ctx.preprocessed_data.get(label, [])
        if not ep_list:
            continue

        # Assuming ep_list[0] exists per upstream guarantees
        epochs = ep_list[0]
        if not hasattr(epochs, "save"):
            continue

        out_dir = save_root / ".fif files" / label
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(
                "post_export_write_missing_fifs_mkdir_failed",
                extra={"dir": str(out_dir), "error": str(e)},
            )
            continue

        out_path = out_dir / _legacy_like_fname(base_stem, label)

        if not out_path.exists():
            if not save_pref:
                message = (
                    f"[AUDIT WARNING] FIF write forced (required for export) despite 'save_preprocessed_fif=False'. "
                    f"Target: {out_path.name}"
                )
                logger.warning(message)
                if ctx.log:
                    try:
                        ctx.log(message)
                    except Exception:
                        pass
            try:
                logger.debug(
                    "post_export_write_missing_fif_saving",
                    extra={"label": label, "out_path": str(out_path)},
                )
                epochs.save(str(out_path), overwrite=True, split_size=2 * 1024 ** 3)
                written += 1
            except Exception as e:
                # Log failure instead of silent pass
                err_msg = f"Failed to save fallback FIF for '{label}': {e}"
                logger.error(
                    "post_export_write_missing_fif_failed",
                    extra={"label": label, "out_path": str(out_path), "error": str(e)},
                )
                if ctx.log:
                    try:
                        ctx.log(err_msg)
                    except Exception:
                        pass

    logger.debug(
        "post_export_write_missing_fifs_done",
        extra={"save_root": str(save_root), "written": written},
    )
    return written


def run_post_export(ctx: LegacyCtx, labels: List[str]) -> int:
    """
    Execute legacy export. Then, for this specific file and labels,
    write any missing -epo.fif files (per-file fallback).
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

    # Run legacy (Excel, etc.)
    try:
        logger.debug(
            "post_export_call_legacy",
            extra={"save_root": str(save_root), "labels": labels},
        )
        _legacy_post_process(shim, labels)
    except Exception as e:
        shim.log(f"[adapter] legacy post_process failed: {e}")
        logger.error(
            "post_export_legacy_failed",
            extra={"error": str(e)},
        )
        raise

    # Per-file FIF fallback (only writes files that are missing)
    written = _write_missing_fifs(ctx, save_root, labels)

    try:
        logger.info(
            "post_export_done",
            extra={
                "save_root": str(save_root),
                "labels": labels,
                "fallback_fifs_written": written,
            },
        )
    except Exception:
        logger.debug(
            "post_export_done_logging_failed",
            extra={"save_root": str(save_root), "written": written},
        )

    return written


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default
