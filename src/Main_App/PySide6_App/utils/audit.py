"""Preprocessing audit helpers for the PySide6 application."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

K_EEG = 8
N_SAMPLES = 100_000


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        val = float(value)
        if np.isnan(val):  # type: ignore[arg-type]
            return None
        return val
    except (TypeError, ValueError):
        return None


def start_preproc_audit(raw: Any, params: Mapping[str, Any]) -> Dict[str, Any]:
    """Capture the initial Raw metadata before preprocessing mutates it."""
    info = getattr(raw, "info", {})
    ch_names = list(getattr(raw, "ch_names", []))
    return {
        "sfreq": _to_float(info.get("sfreq")),
        "lowpass": _to_float(info.get("lowpass")),
        "highpass": _to_float(info.get("highpass")),
        "n_channels": len(ch_names),
        "ch_names": ch_names,
        "ref_applied": bool(info.get("fpvs_initial_custom_ref", False)),
        "params_snapshot": dict(params),
    }


def fingerprint(raw: Any) -> str:
    """Return a SHA256 digest of the first EEG channels and samples."""
    try:
        channel_types = list(raw.get_channel_types())  # type: ignore[attr-defined]
        eeg_indices = [idx for idx, kind in enumerate(channel_types) if kind == "eeg"]
    except Exception:
        return "NA"

    if not eeg_indices:
        return "NA"

    picks = eeg_indices[:K_EEG]
    try:
        n_times = int(getattr(raw, "n_times", 0))
    except Exception:
        n_times = 0
    stop = min(N_SAMPLES, max(0, n_times))
    if stop <= 0:
        return "NA"

    try:
        data = raw.get_data(picks=picks, start=0, stop=stop)  # type: ignore[attr-defined]
    except Exception:
        return "NA"

    if data.size == 0:
        return "NA"

    digest = hashlib.sha256(np.ascontiguousarray(data.astype(np.float32)).tobytes()).hexdigest()
    return digest


def end_preproc_audit(
    raw: Any,
    params: Mapping[str, Any],
    *,
    filename: str,
    events_info: Mapping[str, Any] | None = None,
    fif_written: int = 0,
    n_rejected: int = 0,
) -> Dict[str, Any]:
    """Capture the final state after preprocessing is complete."""
    info = getattr(raw, "info", {})
    stim_channel = str(
        (events_info or {}).get("stim_channel")
        or params.get("stim_channel")
        or ""
    )
    n_events = int((events_info or {}).get("n_events", 0))
    ref_candidates = [c for c in (params.get("ref_channel1"), params.get("ref_channel2")) if c]
    audit = {
        "file": filename,
        "sfreq": float(_to_float(info.get("sfreq")) or 0.0),
        "lowpass": _to_float(info.get("lowpass")),
        "highpass": _to_float(info.get("highpass")),
        "ref_applied": bool(info.get("fpvs_initial_custom_ref", False)),
        "ref_chans": ref_candidates or None,
        "n_channels": int(len(getattr(raw, "ch_names", []))),
        "ch_names": list(getattr(raw, "ch_names", [])),
        "n_events": n_events,
        "n_rejected": int(n_rejected),
        "stim_channel": stim_channel,
        "save_preprocessed_fif": bool(params.get("save_preprocessed_fif", False)),
        "fif_written": int(fif_written),
        "sha256_head": fingerprint(raw),
    }
    return audit


def compare_preproc(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    params: Mapping[str, Any],
    *,
    events_info: Mapping[str, Any] | None = None,
) -> List[str]:
    """Return human-readable mismatches between requested and observed settings."""
    problems: List[str] = []

    target_ds = _to_float(params.get("downsample") or params.get("downsample_rate"))
    if target_ds and target_ds > 0:
        if abs(float(after.get("sfreq", 0.0)) - target_ds) > 0.05:
            problems.append(
                f"downsample expected {target_ds:g} got {float(after.get('sfreq', 0.0)):.2f}"
            )

    target_hp = _to_float(params.get("low_pass"))
    if target_hp and target_hp > 0:
        actual_hp = _to_float(after.get("highpass"))
        if actual_hp is None or abs(actual_hp - target_hp) > 0.1:
            problems.append(
                f"highpass expected {target_hp:g} got {actual_hp if actual_hp is not None else 'NA'}"
            )

    target_lp = _to_float(params.get("high_pass"))
    if target_lp and target_lp > 0:
        actual_lp = _to_float(after.get("lowpass"))
        if actual_lp is None or abs(actual_lp - target_lp) > 0.1:
            problems.append(
                f"lowpass expected {target_lp:g} got {actual_lp if actual_lp is not None else 'NA'}"
            )

    ref_expected = [c for c in (params.get("ref_channel1"), params.get("ref_channel2")) if c]
    if ref_expected:
        if not after.get("ref_applied"):
            problems.append("reference requested but custom_ref_applied=False")
        else:
            applied = after.get("ref_chans") or []
            if set(applied) != set(ref_expected):
                problems.append(
                    f"reference channels expected {tuple(ref_expected)} got {tuple(applied)}"
                )

    max_keep = params.get("max_idx_keep")
    if max_keep not in (None, "", 0):
        try:
            max_keep_int = int(max_keep)
        except (TypeError, ValueError):
            max_keep_int = None
        if max_keep_int and max_keep_int > 0:
            actual_ch = int(after.get("n_channels", 0))
            stim_channel = after.get("stim_channel")
            ch_names_before = set((before or {}).get("ch_names", []))
            if actual_ch > max_keep_int:
                allowed = max_keep_int
                stim_exception = (
                    stim_channel
                    and stim_channel in ch_names_before
                    and actual_ch == allowed + 1
                )
                if not stim_exception:
                    problems.append(
                        f"channel cap {max_keep_int} but {actual_ch} channels remain"
                    )

    n_rejected = after.get("n_rejected")
    if n_rejected is None or int(n_rejected) < 0:
        problems.append("kurtosis reject count missing")

    stim_channel = after.get("stim_channel")
    if stim_channel:
        ch_names_after = set((after.get("ch_names") or []))
        ch_names_before = set((before or {}).get("ch_names", []))
        stim_found_initial = stim_channel in ch_names_before or stim_channel in ch_names_after
        if not stim_found_initial:
            problems.append(f"stim '{stim_channel}' not found in channels")
        n_events = int(after.get("n_events", 0))
        if n_events <= 0:
            problems.append(f"stim '{stim_channel}' produced 0 events")
        if events_info and events_info.get("source") == "annotations":
            problems.append(f"stim '{stim_channel}' fallback to annotations")

    fif_flag = bool(after.get("save_preprocessed_fif"))
    fif_written = int(after.get("fif_written", 0))
    if fif_flag:
        if fif_written <= 0:
            problems.append("save_preprocessed_fif=True but no FIF outputs recorded")
    else:
        if fif_written > 0:
            problems.append("save_preprocessed_fif=False but FIF outputs were written")

    return problems


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_audit_json(
    root: Path,
    *,
    basename: str,
    audit: Mapping[str, Any],
    params: Mapping[str, Any],
    problems: Sequence[str],
) -> Path:
    """Write the audit payload to disk and return the file path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    safe = basename.replace(" ", "_") if basename else "unknown"
    safe = safe.replace("/", "_").replace("\\", "_")
    out_path = root / f"preproc_{timestamp}_{safe}.json"
    payload = {
        "file": audit.get("file") or basename,
        "params": _json_safe(dict(params)),
        "audit": _json_safe(dict(audit)),
        "problems": list(problems),
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out_path


def format_audit_summary(audit: Mapping[str, Any] | None, problems: Sequence[str] | None) -> tuple[str, bool]:
    """Return the GUI log line and whether it should be treated as a warning."""
    if not audit:
        return "[AUDIT WARNING] audit data missing", True

    problems = list(problems or [])
    if problems:
        return "[AUDIT WARNING] " + "; ".join(problems), True

    sfreq = _to_float(audit.get("sfreq")) or 0.0
    hp = _to_float(audit.get("highpass"))
    lp = _to_float(audit.get("lowpass"))
    ref = audit.get("ref_chans")
    stim = audit.get("stim_channel") or ""
    hp_str = f"{hp:g}" if hp is not None else "DC"
    lp_str = f"{lp:g}" if lp is not None else "Nyq"

    line = (
        "[AUDIT] "
        f"DS={sfreq:.1f}Hz "
        f"HP={hp_str} "
        f"LP={lp_str} "
        f"ref={tuple(ref) if ref else 'None'} "
        f"ch={audit.get('n_channels', 'NA')} "
        f"events={audit.get('n_events', 'NA')} "
        f"reject={audit.get('n_rejected', 'NA')} "
        f"stim='{stim}' "
        f"FIF={bool(audit.get('save_preprocessed_fif'))}"
    )
    return line, False


__all__ = [
    "start_preproc_audit",
    "end_preproc_audit",
    "compare_preproc",
    "fingerprint",
    "write_audit_json",
    "format_audit_summary",
]
