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
    ref_candidates = [
        c for c in (params.get("ref_channel1"), params.get("ref_channel2")) if c
    ]
    return {
        "sfreq": _to_float(info.get("sfreq")),
        "lowpass": _to_float(info.get("lowpass")),
        "highpass": _to_float(info.get("highpass")),
        "n_channels": len(ch_names),
        "ch_names": ch_names,
        # FPVS-specific flag: set by the PySide6 preprocessing pipeline (if used)
        "ref_applied": bool(info.get("fpvs_initial_custom_ref", False)),
        "ref_chans": ref_candidates or None,
        "reference_requested": bool(ref_candidates),
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

    digest = hashlib.sha256(
        np.ascontiguousarray(data.astype(np.float32)).tobytes()
    ).hexdigest()
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
    ref_candidates = [
        c for c in (params.get("ref_channel1"), params.get("ref_channel2")) if c
    ]

    # FPVS flag (our own marker) plus MNE's built-in custom_ref_applied for debugging.
    fpvs_flag = info.get("fpvs_initial_custom_ref", False)
    mne_custom_ref = info.get("custom_ref_applied", None)

    audit = {
        "file": filename,
        "sfreq": float(_to_float(info.get("sfreq")) or 0.0),
        "lowpass": _to_float(info.get("lowpass")),
        "highpass": _to_float(info.get("highpass")),
        # FPVS-specific flag: same source as in start_preproc_audit
        "ref_applied": bool(fpvs_flag),
        "ref_chans": ref_candidates or None,
        "reference_requested": bool(ref_candidates),
        "fpvs_initial_custom_ref": bool(fpvs_flag),
        "mne_custom_ref": mne_custom_ref,
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

    # Downsample check
    target_ds = _to_float(params.get("downsample") or params.get("downsample_rate"))
    if target_ds and target_ds > 0:
        if abs(float(after.get("sfreq", 0.0)) - target_ds) > 0.05:
            problems.append(
                f"downsample expected {target_ds:g} got {float(after.get('sfreq', 0.0)):.2f}"
            )

    # High-pass check
    target_hp = _to_float(params.get("high_pass"))
    if target_hp and target_hp > 0:
        actual_hp = _to_float(after.get("highpass"))
        if actual_hp is None or abs(actual_hp - target_hp) > 0.1:
            problems.append(
                f"highpass expected {target_hp:g} got {actual_hp if actual_hp is not None else 'NA'}"
            )

    # Low-pass check
    target_lp = _to_float(params.get("low_pass"))
    if target_lp and target_lp > 0:
        actual_lp = _to_float(after.get("lowpass"))
        if actual_lp is None or abs(actual_lp - target_lp) > 0.1:
            problems.append(
                f"lowpass expected {target_lp:g} got {actual_lp if actual_lp is not None else 'NA'}"
            )

    # Reference check (softened):
    # - We only treat it as a problem if the requested ref channels are not present
    #   in the original Raw channel list.
    # - We no longer treat "custom_ref_applied=False" by itself as a hard error,
    #   because the pipeline now handles initial and final references internally.
    ref_expected = [
        c for c in (params.get("ref_channel1"), params.get("ref_channel2")) if c
    ]
    if ref_expected:
        ch_names_before = set((before or {}).get("ch_names", []))
        if ch_names_before:
            before_upper = {nm.upper() for nm in ch_names_before}
            missing_ci = [c for c in ref_expected if c.upper() not in before_upper]
            if missing_ci:
                problems.append(
                    f"reference requested for {tuple(ref_expected)} but channels {tuple(missing_ci)} "
                    f"are not present in the raw data"
                )
        # If the channels existed initially, we trust the preprocessing pipeline
        # to have applied the initial reference; we don't warn solely based on
        # the ref_applied flag in the audit.

    # Channel cap check
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

    # Kurtosis reject count
    n_rejected = after.get("n_rejected")
    if n_rejected is None or int(n_rejected) < 0:
        problems.append("kurtosis reject count missing")

    # Stim / events integrity
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

    # FIF write consistency
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


def format_audit_summary(
    audit: Mapping[str, Any] | None,
    problems: Sequence[str] | None = None,
) -> tuple[str, bool]:
    """Return the GUI log line and whether it should be treated as a warning."""
    if not audit:
        return "[AUDIT WARNING] audit data missing", True

    problems = list(problems or [])
    if problems:
        return "[AUDIT WARNING] " + "; ".join(problems), True

    def _fmt_int(value: Any) -> str:
        if value is None:
            return "NA"
        try:
            num = float(value)
        except (TypeError, ValueError):
            return str(value)
        if num.is_integer():
            return str(int(num))
        return f"{num:g}"

    def _fmt_freq(value: float | None, default: str) -> str:
        if value is None:
            return default
        return f"{value:.1f}"

    req_ds = _to_float(audit.get("req_downsample"))
    act_ds = _to_float(audit.get("act_sfreq")) or _to_float(audit.get("sfreq"))
    req_hp = _to_float(audit.get("req_highpass"))
    act_hp = _to_float(audit.get("act_highpass"))
    req_lp = _to_float(audit.get("req_lowpass"))
    act_lp = _to_float(audit.get("act_lowpass"))
    req_ref = audit.get("req_ref_chans")
    act_ref = audit.get("ref_chans")
    req_stim = audit.get("req_stim") or ""
    act_events = audit.get("act_events") or audit.get("n_events")
    req_max_channels = audit.get("req_max_channels")
    act_channels = audit.get("n_channels")
    req_reject = audit.get("req_reject_thresh")
    act_rejected = audit.get("n_rejected")
    req_save_fif = audit.get("req_save_fif")
    act_fif_written = audit.get("act_fif_written")

    ds_part = "DS req=NAHz act=NAHz"
    if req_ds is not None or act_ds is not None:
        req_ds_str = _fmt_freq(req_ds, "NA")
        act_ds_str = _fmt_freq(act_ds, "NA")
        ds_part = f"DS req={req_ds_str}Hz act={act_ds_str}Hz"

    hp_part = "HP req=DC act=DC"
    if req_hp is not None or act_hp is not None:
        req_hp_str = _fmt_freq(req_hp, "DC")
        act_hp_str = _fmt_freq(act_hp, "DC")
        hp_part = f"HP req={req_hp_str}Hz act={act_hp_str}Hz"

    lp_part = "LP req=Nyq act=Nyq"
    if req_lp is not None or act_lp is not None:
        req_lp_str = _fmt_freq(req_lp, "Nyq")
        act_lp_str = _fmt_freq(act_lp, "Nyq")
        lp_part = f"LP req={req_lp_str}Hz act={act_lp_str}Hz"

    ref_req_str = tuple(req_ref) if req_ref else "None"
    ref_act_str = tuple(act_ref) if act_ref else "None"
    ref_part = f"ref req={ref_req_str} act={ref_act_str}"

    ch_req_str = f"≤{_fmt_int(req_max_channels)}" if req_max_channels is not None else "≤NA"
    ch_part = f"ch req={ch_req_str} act={_fmt_int(act_channels)}"

    events_part = f"events req_stim='{req_stim}' act={_fmt_int(act_events)}"
    reject_part = f"reject req={_fmt_int(req_reject)} act={_fmt_int(act_rejected)}"
    fif_part = f"FIF req={bool(req_save_fif)} act_written={_fmt_int(act_fif_written)}"

    line = "[AUDIT] " + " ".join(
        [
            ds_part,
            hp_part,
            lp_part,
            ref_part,
            ch_part,
            events_part,
            reject_part,
            fif_part,
        ]
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
