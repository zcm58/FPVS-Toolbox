# src/Main_App/PySide6_App/adapters/post_export_adapter.py
from __future__ import annotations
from dataclasses import dataclass
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from Main_App.Legacy_App.post_process import post_process as _legacy_post_process


logger = logging.getLogger(__name__)


@dataclass
class LegacyCtx:
    """Data-only context for legacy post_process (no QWidget, no Qt)."""
    preprocessed_data: Dict[str, Any]
    save_folder_path: Any | None = None   # may expose .get()
    data_paths: List[str] | None = None
    settings: Optional[Any] = None
    log: Optional[Callable[[str], None]] = None


def _normalize_save_folder(save_folder_path: Any) -> Any:
    """
    Ensure adapter exposes save_folder_path.get() -> str path.
    Accepts an object with .get(), a raw str/Path, or raises if missing.
    """
    if hasattr(save_folder_path, "get") and callable(getattr(save_folder_path, "get")):
        root = Path(str(save_folder_path.get())).resolve()
    elif save_folder_path is not None:
        root = Path(str(save_folder_path)).resolve()
    else:
        raise RuntimeError("Adapter missing save_folder_path; cannot export outputs.")
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(get=lambda r=root: str(r))


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
    save_pref = _coerce_bool(settings_dict.get("save_preprocessed_fif"), default=False)
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
    return shim


def _legacy_like_fname(base_stem: str, label: str) -> str:
    """
    Match legacy naming: <base>_<label_with_underscores>-epo.fif
    """
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")
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
        return 0

    written = 0
    settings_obj = ctx.settings or {}
    save_pref_raw: Any = None
    if isinstance(settings_obj, dict):
        save_pref_raw = settings_obj.get("save_preprocessed_fif")
    else:
        getter = getattr(settings_obj, "get", None)
        if callable(getter):
            try:
                save_pref_raw = getter("save_preprocessed_fif")
            except TypeError:
                save_pref_raw = None
        if save_pref_raw is None and hasattr(settings_obj, "save_preprocessed_fif"):
            save_pref_raw = getattr(settings_obj, "save_preprocessed_fif")
    save_pref = _coerce_bool(save_pref_raw, default=False)
    base_stem = Path(str((ctx.data_paths or ["unknown"])[0])).stem
    for label in labels:
        ep_list = ctx.preprocessed_data.get(label, [])
        if not ep_list:
            continue
        epochs = ep_list[0]
        if not hasattr(epochs, "save"):
            continue
        out_dir = save_root / ".fif files" / label
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / _legacy_like_fname(base_stem, label)
        if not out_path.exists():
            if not save_pref:
                frame = inspect.currentframe()
                line_no = frame.f_lineno + 1 if frame else -1
                if frame:
                    del frame
                call_site = f"{__name__}:{line_no}"
                message = (
                    "[AUDIT WARNING] FIF write attempted while save_preprocessed_fif=False "
                    f"→ {out_path} (call_site={call_site})"
                )
                logger.warning(message)
                if ctx.log:
                    try:
                        ctx.log(message)
                    except Exception:
                        pass
            try:
                epochs.save(str(out_path), overwrite=True, split_size=2 * 1024 ** 3)
                written += 1
            except Exception:
                # Keep quiet; Excel export may still succeed
                pass
    return written


def run_post_export(ctx: LegacyCtx, labels: List[str]) -> int:
    """
    Execute legacy export. Then, for this specific file and labels,
    write any missing -epo.fif files (per-file fallback).
    """
    shim = _build_legacy_shim(ctx)
    save_root = Path(shim.save_folder_path.get()).resolve()

    # Run legacy (Excel, etc.)
    try:
        _legacy_post_process(shim, labels)
    except Exception as e:
        shim.log(f"[adapter] legacy post_process failed: {e}")
        raise

    # Per-file FIF fallback (only writes files that are missing)
    return _write_missing_fifs(ctx, save_root, labels)


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

