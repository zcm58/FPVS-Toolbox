#!/usr/bin/env python3
"""

Example for a script to process the data from Dylan's Experiment.

This file is designed to run directly from your editor with one click.

To use:
1) Edit values in USER_CONFIG below.
2) Save this file.
3) Run this file (F5 / Run button / `python ...`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import mne
import numpy as np
from mne.time_frequency import psd_welch
from scipy.stats import kurtosis, zscore


# --------------------------
# Beginner-friendly config block.
# --------------------------
# Edit only this block before running.
USER_CONFIG: Dict[str, Any] = {
    "input_path": "C:/path/to/your/session.bdf",
    "output_dir": "C:/path/to/outputs/session_run",
    "triggers": [
        {
            "code": 1,
            "name": "Condition_1",
            "epoch_seconds": 15.0,
            "break_seconds": 5.0,
            "min_epochs": 3,
            "max_epochs": None,
        },
        {
            "code": 2,
            "name": "Condition_2",
            "epoch_seconds": 15.0,
            "break_seconds": 5.0,
            "min_epochs": 3,
            "max_epochs": None,
        },
    ],
    "steps": {
        "initial_reference": "average",
        "keep_eeg_channels": [],
        "max_eeg_channels": None,
        "downsample_hz": 256.0,
        "notch_freqs": [50.0, 60.0],
        "highpass_hz": 0.1,
        "lowpass_hz": 50.0,
        "kurtosis_z_threshold": 6.0,
        "interpolate_bad_channels": True,
        "final_reference": "average",
    },
    "ica": {
        "enabled": False,
        "method": "fastica",
        "n_components": "auto",
        "random_state": 97,
        "max_iter": "auto",
        "exclude_components": [],
    },
    "fft": {
        "fmin": 1.0,
        "fmax": 50.0,
        "x_min": 1.0,
        "x_max": 50.0,
        "n_fft": None,
        "n_overlap": None,
        "n_per_seg": None,
        "log_scale": False,
    },
    "enforce_block_timing": True,
    "strict_timing": True,
    "save_averaged_epochs": False,
    "log_level": "INFO",
}

@dataclass
class TriggerBlockConfig:
    """One trigger definition from your config file.

    Think of each trigger block as one task condition:
    - ``code`` is the integer marker in your EEG file
    - ``name`` is the human-friendly label used in plot filenames and logs
    - ``epoch_seconds`` is how long each segment should last after the trigger
    - ``break_seconds`` is the expected pause before the next trigger should start
    - ``min_epochs`` and ``max_epochs`` let you handle any number of repeats
    """

    code: int
    name: str
    epoch_seconds: float
    break_seconds: float = 0.0
    min_epochs: int = 1
    max_epochs: Optional[int] = None


@dataclass
class PreprocessStepConfig:
    """
    Settings for processing the data

    These are the same knobs we use in the NERD Lab for processing FPVS data like
    mastoid references, channel handling, downsampling, filtering, simple bad-channel
    handling, and a final reference.
    """

    initial_reference: Optional[Any] = "average"
    keep_eeg_channels: List[str] = field(default_factory=list)
    max_eeg_channels: Optional[int] = None
    downsample_hz: Optional[float] = 250.0
    notch_freqs: List[float] = field(default_factory=lambda: [50.0, 60.0])
    highpass_hz: Optional[float] = 0.1
    lowpass_hz: Optional[float] = 40.0
    kurtosis_z_threshold: Optional[float] = 6.0
    interpolate_bad_channels: bool = True
    final_reference: Optional[Any] = "average"


@dataclass
class ICAConfig:
    """Settings for optional independent component analysis.

    ICA is used to isolate non-brain activity (eye blinks, muscle bursts, etc.).
    If enabled, the selected component indices are removed from the signal.
    """

    enabled: bool = False
    method: str = "fastica"
    n_components: str | int = "auto"
    random_state: int = 97
    max_iter: int | str = "auto"
    exclude_components: List[int] = field(default_factory=list)


@dataclass
class FFTConfig:
    """Settings for frequency analysis and plotting limits."""

    fmin: float = 1.0
    fmax: float = 40.0
    x_min: float = 1.0
    x_max: float = 40.0
    n_fft: Optional[int] = None
    n_overlap: Optional[int] = None
    n_per_seg: Optional[int] = None
    log_scale: bool = False


@dataclass
class PipelineConfig:
    """Complete script configuration assembled from JSON."""

    input_path: str
    output_dir: str
    triggers: List[TriggerBlockConfig]
    steps: PreprocessStepConfig = field(default_factory=PreprocessStepConfig)
    ica: ICAConfig = field(default_factory=ICAConfig)
    fft: FFTConfig = field(default_factory=FFTConfig)
    enforce_block_timing: bool = True
    strict_timing: bool = True
    save_averaged_epochs: bool = False
    log_level: str = "INFO"


def setup_logger(level: str = "INFO") -> logging.Logger:
    """Create one logger used everywhere.

    A beginner-friendly runbook:
    - If the script does something important, it writes a short message.
    - If something goes wrong, you can see exactly what happened and where.
    """

    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    return logging.getLogger("DylansScript")


def parse_reference(value: Any) -> Optional[Any]:
    """Turn plain text like ``\"none\"`` into actual Python ``None``.

    MNE accepts `None` as “no reference”, so we normalize here before calling.
    """

    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"", "none", "null", "nan"}:
            return None
    return value


def safe_name(value: str) -> str:
    """Sanitize trigger names so they can be used in filenames.

    This avoids spaces/symbols breaking your operating system file writing step.
    """

    base = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in value.strip())
    return (base or "trigger").replace("__", "_")[:80]


def seconds_to_samples(seconds: float, sfreq: float) -> int:
    """Convert seconds to integer samples using current sampling rate."""

    return max(int(round(float(seconds) * float(sfreq))), 1)


def ensure_output_dir(output_dir: str) -> Path:
    """Create output folder if missing and return an absolute Path."""

    path = Path(output_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_config(payload: Dict[str, Any]) -> PipelineConfig:
    """Validate config structure and convert it to typed dataclasses.

    This is where we catch mistakes early:
    missing trigger names, missing durations, invalid numbers, etc.
    """

    trigger_payload = payload.get("triggers", [])
    if not isinstance(trigger_payload, list) or not trigger_payload:
        raise ValueError("Config must contain a non-empty `triggers` list.")

    trigger_cfg: List[TriggerBlockConfig] = []
    for entry in trigger_payload:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid trigger block: {entry!r}")
        code = int(entry["code"])
        name = str(entry["name"]).strip()
        if not name:
            raise ValueError(f"Trigger code {code} has empty name.")
        epoch_seconds = float(entry["epoch_seconds"])
        break_seconds = float(entry.get("break_seconds", 0.0))
        min_epochs = int(entry.get("min_epochs", 1))
        max_epochs = entry.get("max_epochs", None)
        if max_epochs is not None:
            max_epochs = None if int(max_epochs) <= 0 else int(max_epochs)

        trigger_cfg.append(
            TriggerBlockConfig(
                code=code,
                name=name,
                epoch_seconds=epoch_seconds,
                break_seconds=break_seconds,
                min_epochs=min_epochs,
                max_epochs=max_epochs,
            )
        )

    steps = payload.get("steps", {})
    ica = payload.get("ica", {})
    fft = payload.get("fft", {})

    return PipelineConfig(
        input_path=str(payload["input_path"]),
        output_dir=str(payload.get("output_dir", "dylans_script_output")),
        triggers=trigger_cfg,
        steps=PreprocessStepConfig(
            initial_reference=parse_reference(steps.get("initial_reference", "average")),
            keep_eeg_channels=list(steps.get("keep_eeg_channels", [])),
            max_eeg_channels=steps.get("max_eeg_channels"),
            downsample_hz=steps.get("downsample_hz", 250.0),
            notch_freqs=list(steps.get("notch_freqs", [50.0, 60.0])),
            highpass_hz=steps.get("highpass_hz", 0.1),
            lowpass_hz=steps.get("lowpass_hz", 40.0),
            kurtosis_z_threshold=steps.get("kurtosis_z_threshold", 6.0),
            interpolate_bad_channels=bool(steps.get("interpolate_bad_channels", True)),
            final_reference=parse_reference(steps.get("final_reference", "average")),
        ),
        ica=ICAConfig(
            enabled=bool(ica.get("enabled", False)),
            method=str(ica.get("method", "fastica")),
            n_components=ica.get("n_components", "auto"),
            random_state=int(ica.get("random_state", 97)),
            max_iter=ica.get("max_iter", "auto"),
            exclude_components=list(ica.get("exclude_components", [])),
        ),
        fft=FFTConfig(
            fmin=float(fft.get("fmin", 1.0)),
            fmax=float(fft.get("fmax", 40.0)),
            x_min=float(fft.get("x_min", 1.0)),
            x_max=float(fft.get("x_max", 40.0)),
            n_fft=fft.get("n_fft"),
            n_overlap=fft.get("n_overlap"),
            n_per_seg=fft.get("n_per_seg"),
            log_scale=bool(fft.get("log_scale", False)),
        ),
        enforce_block_timing=bool(payload.get("enforce_block_timing", True)),
        strict_timing=bool(payload.get("strict_timing", True)),
        save_averaged_epochs=bool(payload.get("save_averaged_epochs", False)),
        log_level=str(payload.get("log_level", "INFO")),
    )


def read_raw_file(input_path: str, logger: logging.Logger) -> mne.io.BaseRaw:
    """Load raw data and return an MNE object.

    We keep this separate from processing so we can add one clear failure message
    if the file is missing or unreadable.
    """

    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    raw = mne.io.read_raw(str(path), preload=True, verbose="ERROR")
    logger.info("Loaded raw file: %s", path)
    logger.info("Initial sampling rate: %.3f Hz | Channels: %d", raw.info["sfreq"], raw.info["nchan"])
    return raw


def step_1_initial_reference(raw: mne.io.BaseRaw, reference: Optional[Any], logger: logging.Logger) -> mne.io.BaseRaw:
    """Step 1: apply an initial reference before heavy cleaning.

    Think of reference as the baseline electrode you subtract from every channel.
    """

    if reference is None:
        logger.info("Step 1 skipped (initial_reference=None)")
        return raw
    raw.set_eeg_reference(ref_channels=reference, projection=False, verbose="ERROR")
    logger.info("Step 1 applied: initial_reference=%s", reference)
    return raw


def step_2_and_3_channels(raw: mne.io.BaseRaw, cfg: PreprocessStepConfig, logger: logging.Logger) -> mne.io.BaseRaw:
    """Steps 2 and 3:
    - keep only EEG channels (or a user list),
    - optionally cap to a maximum number of EEG channels.

    This prevents extra non-brain channels (like triggers or EKG) from polluting
    epoch calculations.
    """

    if cfg.keep_eeg_channels:
        raw.pick_channels(cfg.keep_eeg_channels, ordered=True, on_missing="warn")
        logger.info("Step 2 kept provided channel list (%d channels).", len(cfg.keep_eeg_channels))
    else:
        raw.pick_types(eeg=True)
        logger.info("Step 2 kept all EEG channels automatically.")

    if cfg.max_eeg_channels is not None and raw.nchan > cfg.max_eeg_channels:
        selected = raw.ch_names[: int(cfg.max_eeg_channels)]
        raw.pick_channels(selected, ordered=True)
        logger.info("Step 3 applied: truncated to %d EEG channels.", cfg.max_eeg_channels)
    return raw


def step_4_downsample(raw: mne.io.BaseRaw, target_hz: Optional[float], logger: logging.Logger) -> mne.io.BaseRaw:
    """Step 4: downsample to reduce processing cost.

    If the incoming recording already has equal or lower sampling, no change is made.
    """

    if target_hz is None:
        logger.info("Step 4 skipped (downsample_hz=None)")
        return raw

    if raw.info["sfreq"] <= target_hz:
        logger.info("Step 4 skipped (%s <= %s)", raw.info["sfreq"], target_hz)
        return raw

    raw.resample(target_hz, npad="auto")
    logger.info("Step 4 applied. New sampling rate: %.3f Hz", raw.info["sfreq"])
    return raw


def step_5_filter(raw: mne.io.BaseRaw, cfg: PreprocessStepConfig, logger: logging.Logger) -> mne.io.BaseRaw:
    """Step 5: remove known noise bands and keep a clean frequency range.

    The default is notch for power line + bandpass to keep brain-relevant frequencies.
    """

    if cfg.notch_freqs:
        raw.notch_filter(freqs=cfg.notch_freqs, picks="eeg", verbose="ERROR")
        logger.info("Step 5 notch filter applied: %s Hz", cfg.notch_freqs)

    if cfg.highpass_hz is not None or cfg.lowpass_hz is not None:
        raw.filter(l_freq=cfg.highpass_hz, h_freq=cfg.lowpass_hz, picks="eeg", verbose="ERROR")
        logger.info("Step 5 band filter applied: l_freq=%s, h_freq=%s", cfg.highpass_hz, cfg.lowpass_hz)
    return raw


def step_6_artifact_cleanup(raw: mne.io.BaseRaw, cfg: PreprocessStepConfig, logger: logging.Logger) -> mne.io.BaseRaw:
    """Step 6: simple artifact cleanup using channel kurtosis.

    Kurtosis looks for channels whose value distribution has unusual spikes.
    Those channels are flagged as bad and optionally interpolated.
    """

    if cfg.kurtosis_z_threshold is None:
        logger.info("Step 6 skipped (kurtosis_z_threshold=None)")
        return raw

    data = raw.get_data(picks="eeg")
    if data.size == 0:
        logger.warning("Step 6 skipped: no EEG samples found.")
        return raw

    k = kurtosis(data, axis=1, fisher=True, bias=False)
    z = zscore(k, nan_policy="omit")
    bad_idx = np.where(np.abs(z) > cfg.kurtosis_z_threshold)[0]
    bad_names = [raw.ch_names[i] for i in bad_idx if i < len(raw.ch_names)]
    raw.info["bads"] = list(dict.fromkeys(list(raw.info.get("bads", [])) + bad_names))
    logger.info("Step 6 flagged %d bad channels: %s", len(bad_names), bad_names)

    if cfg.interpolate_bad_channels and bad_names:
        raw.interpolate_bads(reset_bads=True, verbose="ERROR")
        logger.info("Step 6 interpolated %d bad channels.", len(bad_names))

    return raw


def step_7_final_reference(raw: mne.io.BaseRaw, reference: Optional[Any], logger: logging.Logger) -> mne.io.BaseRaw:
    """Step 7: apply final reference for consistency before epoching."""

    if reference is None:
        logger.info("Step 7 skipped (final_reference=None)")
        return raw
    raw.set_eeg_reference(ref_channels=reference, projection=False, verbose="ERROR")
    logger.info("Step 7 applied: final_reference=%s", reference)
    return raw


def run_steps_1_to_7(raw: mne.io.BaseRaw, cfg: PreprocessStepConfig, logger: logging.Logger) -> mne.io.BaseRaw:
    """Run preprocessing in the required toolbox order (1,2,3,4,5,6,7)."""

    raw = step_1_initial_reference(raw, cfg.initial_reference, logger)
    raw = step_2_and_3_channels(raw, cfg, logger)
    raw = step_4_downsample(raw, cfg.downsample_hz, logger)
    raw = step_5_filter(raw, cfg, logger)
    raw = step_6_artifact_cleanup(raw, cfg, logger)
    raw = step_7_final_reference(raw, cfg.final_reference, logger)
    return raw


def run_optional_ica(raw: mne.io.BaseRaw, cfg: ICAConfig, logger: logging.Logger) -> mne.io.BaseRaw:
    """Fit and apply ICA if enabled.

    Beginner note: ICA can help remove pattern-like artifacts, but it is optional.
    If it fails, we continue without stopping the whole script.
    """

    if not cfg.enabled:
        logger.info("ICA disabled.")
        return raw

    try:
        ica = mne.preprocessing.ICA(
            n_components=cfg.n_components,
            method=cfg.method,
            random_state=cfg.random_state,
            max_iter=cfg.max_iter,
            verbose="ERROR",
        )
        ica.fit(raw, picks="eeg")
        ica.exclude = sorted(set(int(c) for c in cfg.exclude_components))
        logger.info("ICA fit complete. Excluding components: %s", ica.exclude)
        return ica.apply(raw.copy(), verbose="ERROR")
    except Exception as exc:
        logger.warning("ICA failed; continuing without ICA: %s", exc)
        return raw


def extract_events(raw: mne.io.BaseRaw, logger: logging.Logger) -> np.ndarray:
    """Find event markers from annotations or stimulation channels.

    We return an array shaped (N, 3): sample index, 0, event code.
    """

    try:
        events, _ = mne.events_from_annotations(raw, verbose="ERROR")
        events = np.asarray(events, dtype=int)
        if events.size:
            logger.info("Loaded %d events from annotations.", len(events))
            return events[np.argsort(events[:, 0])]
    except Exception:
        pass

    stim_candidates = [name for name in raw.ch_names if "STI" in name.upper() or "TRIG" in name.upper() or "STATUS" in name.upper()]
    if not stim_candidates and raw.ch_names:
        stim_candidates = [raw.ch_names[0]]

    last_exc: Optional[Exception] = None
    for stim in stim_candidates:
        try:
            events = mne.find_events(raw, stim_channel=stim, shortest_event=1, consecutive=True, verbose="ERROR")
            events = np.asarray(events, dtype=int)
            if len(events):
                logger.info("Loaded %d events from stim channel '%s'.", len(events), stim)
                return events[np.argsort(events[:, 0])]
        except Exception as exc:
            last_exc = exc
            continue

    raise RuntimeError(f"No events could be extracted from the file. Last reason: {last_exc}")


def is_epoch_valid(
    start_sample: int,
    all_trigger_starts: np.ndarray,
    cfg: TriggerBlockConfig,
    sfreq: float,
    n_times: int,
    enforce_block_timing: bool,
    strict_timing: bool,
) -> Tuple[bool, Optional[str]]:
    """Validate one epoch candidate against expected timing rules.

    Rules used here:
    - Epoch must fit inside the recording.
    - If timing enforcement is enabled and strict mode is on:
      - next trigger must not begin before epoch end
      - next trigger should respect epoch + break unless last trigger.
    """

    epoch_samps = seconds_to_samples(cfg.epoch_seconds, sfreq)
    epoch_end = start_sample + epoch_samps

    if epoch_end >= n_times:
        return False, "epoch_out_of_recording"

    if not enforce_block_timing:
        return True, None

    if not strict_timing:
        return True, None

    all_sorted = np.sort(all_trigger_starts.astype(int))
    idx = int(np.searchsorted(all_sorted, start_sample, side="left"))
    if idx >= len(all_sorted) - 1:
        return True, None

    next_start = int(all_sorted[idx + 1])
    if next_start < epoch_end:
        return False, "next_trigger_early_overlap"
    if cfg.break_seconds > 0 and next_start < epoch_end + seconds_to_samples(cfg.break_seconds, sfreq):
        return False, "next_trigger_before_expected_break"
    return True, None


def average_epochs_for_trigger(
    raw: mne.io.BaseRaw,
    events: np.ndarray,
    block: TriggerBlockConfig,
    enforce_block_timing: bool,
    strict_timing: bool,
    logger: logging.Logger,
) -> Tuple[Optional[mne.Evoked], Dict[str, Any]]:
    """Extract all valid occurrences of one trigger code and average them.

    Returned summary is always populated so you can inspect how many were used,
    skipped, and any rejection reasons.
    """

    sfreq = raw.info["sfreq"]
    all_starts = np.sort(np.unique(events[:, 0].astype(int)))
    this_starts = np.sort(np.unique(events[events[:, 2] == block.code, 0].astype(int)))

    if len(this_starts) == 0:
        return None, {
            "code": block.code,
            "name": block.name,
            "accepted_epochs": 0,
            "requested_min_epochs": block.min_epochs,
            "requested_max_epochs": block.max_epochs,
            "skipped_epochs": 0,
            "rejections": [{"reason": "no_matching_trigger_found"}],
        }

    accepted: List[int] = []
    rejections: List[Dict[str, Any]] = []

    for s in this_starts:
        ok, reason = is_epoch_valid(
            start_sample=int(s),
            all_trigger_starts=all_starts,
            cfg=block,
            sfreq=sfreq,
            n_times=raw.n_times,
            enforce_block_timing=enforce_block_timing,
            strict_timing=strict_timing,
        )
        if ok:
            accepted.append(int(s))
        else:
            rejections.append({"start_sample": int(s), "reason": reason})

    if block.max_epochs is not None and block.max_epochs > 0:
        accepted = accepted[: block.max_epochs]

    summary = {
        "code": block.code,
        "name": block.name,
        "accepted_epochs": 0,
        "requested_min_epochs": block.min_epochs,
        "requested_max_epochs": block.max_epochs,
        "skipped_epochs": len(rejections),
        "rejections": rejections,
        "epoch_seconds": block.epoch_seconds,
        "break_seconds": block.break_seconds,
    }

    if not accepted:
        logger.warning("No valid epochs accepted for trigger '%s' (code %s).", block.name, block.code)
        return None, summary

    events_for_epochs = np.column_stack(
        [np.array(accepted, dtype=int), np.zeros(len(accepted), dtype=int), np.ones(len(accepted), dtype=int)]
    )
    tmax = seconds_to_samples(block.epoch_seconds, sfreq) - 1
    tmax = tmax / sfreq

    epochs = mne.Epochs(
        raw,
        events=events_for_epochs,
        event_id={"target": 1},
        tmin=0.0,
        tmax=tmax,
        baseline=None,
        preload=True,
        on_missing="ignore",
        reject_by_annotation=True,
        verbose="ERROR",
    )

    if len(epochs) == 0:
        logger.warning("MNE created zero valid epochs for '%s' (code %s).", block.name, block.code)
        return None, summary

    evoked = epochs.average()
    summary["accepted_epochs"] = int(len(epochs))
    return evoked, summary


def compute_fft(evoked: mne.Evoked, cfg: FFTConfig, logger: logging.Logger) -> Tuple[np.ndarray, np.ndarray]:
    """Compute power spectrum (Welch method) from averaged data.

    This converts each waveform into frequency power values that are easier to inspect
    visually and compare across triggers.
    """

    psds, freqs = psd_welch(
        evoked,
        fmin=cfg.fmin,
        fmax=cfg.fmax,
        n_fft=cfg.n_fft,
        n_overlap=cfg.n_overlap,
        n_per_seg=cfg.n_per_seg,
        average="mean",
        verbose="ERROR",
    )
    logger.info("Computed FFT with %d frequency points.", len(freqs))
    return np.asarray(freqs), np.asarray(psds)


def make_fft_plot(
    freqs: np.ndarray,
    psds: np.ndarray,
    block: TriggerBlockConfig,
    cfg: FFTConfig,
    out_dir: Path,
    logger: logging.Logger,
) -> str:
    """Create and save one FFT plot for one trigger name.

    It averages across channels so each condition has one clean line on the chart.
    """

    if cfg.x_min >= cfg.x_max:
        raise ValueError("fft.x_min must be smaller than fft.x_max")

    channel_mean = np.mean(psds, axis=0)
    y = 10 * np.log10(channel_mean) if cfg.log_scale else channel_mean
    x_mask = (freqs >= cfg.x_min) & (freqs <= cfg.x_max)
    if not np.any(x_mask):
        raise ValueError(
            f"FFT x-axis range [{cfg.x_min}, {cfg.x_max}] contains no frequencies "
            f"from available data [{float(freqs.min()):.3f}, {float(freqs.max()):.3f}]"
        )

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(freqs[x_mask], y[x_mask], linewidth=1.8)
    ax.set_title(f"{block.name} (code {block.code}) FFT")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Power (dB)" if cfg.log_scale else "Power")
    ax.set_xlim(cfg.x_min, cfg.x_max)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    out_path = out_dir / f"fft_{safe_name(block.name)}.png"
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    logger.info("Saved FFT plot: %s", out_path)
    return str(out_path)


def run_pipeline(cfg: PipelineConfig) -> Dict[str, Any]:
    """Run the full pipeline from file load through FFT charts.

    Return value is a dictionary summarizing everything that was done.
    """

    logger = setup_logger(cfg.log_level)
    out_dir = ensure_output_dir(cfg.output_dir)
    logger.info("Output directory: %s", out_dir)

    raw = read_raw_file(cfg.input_path, logger)
    raw = run_steps_1_to_7(raw, cfg.steps, logger)
    raw = run_optional_ica(raw, cfg.ica, logger)

    events = extract_events(raw, logger)
    if len(events) == 0:
        raise RuntimeError("No events found in raw file.")

    trigger_summaries: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    for block in cfg.triggers:
        logger.info("Processing trigger block '%s' (code=%s)", block.name, block.code)
        evoked, summary = average_epochs_for_trigger(
            raw=raw,
            events=events,
            block=block,
            enforce_block_timing=cfg.enforce_block_timing,
            strict_timing=cfg.strict_timing,
            logger=logger,
        )

        if summary["accepted_epochs"] < summary["requested_min_epochs"]:
            logger.warning(
                "Trigger '%s': only %d accepted epochs (minimum requested %d).",
                block.name,
                summary["accepted_epochs"],
                summary["requested_min_epochs"],
            )

        trigger_summaries.append(summary)
        if evoked is None:
            results.append({"name": block.name, "code": block.code, "status": "skipped"})
            continue

        if cfg.save_averaged_epochs:
            avg_path = out_dir / f"avg_{safe_name(block.name)}.fif"
            evoked.save(str(avg_path), overwrite=True)
        else:
            avg_path = None

        freqs, psds = compute_fft(evoked, cfg.fft, logger)
        fft_npz = out_dir / f"fft_{safe_name(block.name)}.npz"
        np.savez(fft_npz, freqs=freqs, psd=psds, trigger_code=np.array([block.code]), trigger_name=np.array([block.name]))
        plot_path = make_fft_plot(freqs, psds, block, cfg.fft, out_dir, logger)

        results.append(
            {
                "name": block.name,
                "code": block.code,
                "status": "ok",
                "accepted_epochs": summary["accepted_epochs"],
                "fft_plot": plot_path,
                "fft_npz": str(fft_npz),
                "averaged_epoch_fif": str(avg_path) if avg_path else None,
            }
        )

    final_summary = {
        "input_path": str(Path(cfg.input_path).resolve()),
        "output_dir": str(out_dir),
        "sampling_rate_hz": raw.info["sfreq"],
        "n_channels": raw.info["nchan"],
        "steps": asdict(cfg.steps),
        "ica": asdict(cfg.ica),
        "fft": asdict(cfg.fft),
        "triggers": trigger_summaries,
        "results": results,
    }

    with (out_dir / "pipeline_summary.json").open("w", encoding="utf-8") as f:
        json.dump(final_summary, f, indent=2)
    logger.info("Pipeline summary written: %s", out_dir / "pipeline_summary.json")

    return final_summary


def main() -> None:
    """Run script directly with USER_CONFIG.

    This script was written to be beginner-friendly:
    - change USER_CONFIG only,
    - save,
    - run.
    """
    cfg = parse_config(USER_CONFIG)
    run_pipeline(cfg)


if __name__ == "__main__":
    main()
