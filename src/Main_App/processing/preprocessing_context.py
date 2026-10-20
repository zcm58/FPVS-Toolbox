"""Runtime state shared by fixed-order numerical preprocessing methods."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable

import mne
import numpy as np

from Main_App.io.pipeline_events import canonical_recording_events
from Main_App.io.recording_contract import RecordingContract
from Main_App.processing.pipeline_plan import PipelineCancelled, PipelineExecutionError

if TYPE_CHECKING:
    from Main_App.processing.pipeline_plan import PipelinePlan


@dataclass
class PreprocessingContext:
    """One owned Raw and its explicit method inputs/results, never GUI state."""

    raw: Any
    params: dict[str, Any]
    policy: RecordingContract
    plan: PipelinePlan
    log_func: Callable[[str], None]
    filename_for_log: str
    debug_enabled: bool = False
    orig_ch_names: list[str] = field(default_factory=list)
    orig_sfreq: float = 0.0
    fingerprint_in: str = ""
    checkpoint: Any = None
    downsample_rate: Any = None
    high_pass: Any = None
    low_pass: Any = None
    line_noise_filter_enabled: bool = True
    line_noise_frequency_hz: Any = 60
    stim_ch: str = ""
    filter_info_to_preserve: dict[str, float] = field(default_factory=dict)
    effective_low_pass_for_notch: float | None = None
    interpolation_description: str = "bads"
    average_reference_applied: bool = False
    condition_branch: bool = False

    def for_condition(self, raw: Any) -> PreprocessingContext:
        """Apply the same selected methods to a validated interval branch."""
        return replace(self, raw=raw, condition_branch=True, average_reference_applied=False)


def execute_preprocessing_stage(
    stage_id: str, builtin: Callable[[PreprocessingContext], None], context: PreprocessingContext,
) -> None:
    """Keep method-owned numerical changes inside the fixed stage's contract.

    Historical methods retain their exact execution path. Registered methods
    mutate the one owned Raw and return None; channel removal belongs only to
    its dedicated slots, and only resampling may change the time grid.
    """
    plan, policy, raw = context.plan, context.policy, context.raw
    method = next(method for method in plan.methods if method.stage_id == stage_id)
    if method.implementation is None:
        plan.execute(stage_id, builtin, context)
        return
    try:
        if not isinstance(raw, mne.io.BaseRaw):
            raise TypeError("Preprocessing methods require an owned MNE Raw.")
        grid = (float(raw.info["sfreq"]), int(raw.n_times), int(raw.first_samp))
        names, kinds = tuple(raw.ch_names), tuple(raw.get_channel_types())
        locations = {name: channel["loc"].copy() for name, channel in zip(names, raw.info["chs"], strict=True)}
        events = canonical_recording_events(raw, recording_contract=policy)
        stim_names = [name for name, kind in zip(names, kinds, strict=True) if kind == "stim"]
        stim_data = raw.get_data(picks=stim_names) if stim_names else None
        if stage_id == "interpolation" and not policy.interpolation_allowed and raw.info["bads"]:
            raise ValueError("Interpolation is unavailable for this recording.")
        result = plan.execute(stage_id, builtin, context)
        if result is not None or context.raw is not raw:
            raise TypeError("Context methods must mutate the owned MNE Raw and return None.")
        if context.plan is not plan or context.policy is not policy:
            raise ValueError("Methods cannot replace the resolved pipeline or recording contract.")
        after_grid = (float(raw.info["sfreq"]), int(raw.n_times), int(raw.first_samp))
        if stage_id != "resample" or not policy.resampling_allowed or events is not None:
            if after_grid != grid:
                raise ValueError("This method must preserve the recording's native sampling grid.")
        else:
            target = context.downsample_rate
            target = grid[0] if target is None else float(target)
            if after_grid[0] != target:
                raise ValueError("Resampling must use the project's configured sampling rate.")
        if policy.required_sfreq is not None and after_grid[0] != policy.required_sfreq:
            raise ValueError("This recording requires its native sampling grid.")
        removed = set(names) - set(raw.ch_names)
        if stage_id in {"reference_channel_drop", "channel_selection"}:
            if any(name not in names for name in raw.ch_names):
                raise ValueError("Channel selection cannot introduce or rename channels.")
            if stage_id == "reference_channel_drop" and not removed.issubset(policy.initial_reference_channels):
                raise ValueError("Reference removal can remove only the resolved reference channels.")
            if tuple(name for name in names if name in raw.ch_names) != tuple(raw.ch_names):
                raise ValueError("Channel removal must preserve the admitted channel order.")
            if any(name not in raw.ch_names for name in stim_names):
                raise ValueError("Channel removal must preserve stimulus channels.")
        elif tuple(raw.ch_names) != names:
            raise ValueError("This method must preserve the admitted channels and their order.")
        expected_kinds = dict(zip(names, kinds, strict=True))
        for name, kind, channel in zip(raw.ch_names, raw.get_channel_types(), raw.info["chs"], strict=True):
            if kind != expected_kinds[name] or not np.array_equal(channel["loc"], locations[name], equal_nan=True):
                raise ValueError("Methods must preserve admitted channel roles and coordinates.")
        if len(mne.pick_types(raw.info, eeg=True, exclude=[])) < 2:
            raise ValueError("Average-reference processing requires at least two retained EEG channels.")
        after_events = canonical_recording_events(raw, recording_contract=policy)
        if (events is None) != (after_events is None) or (
            events is not None and not np.array_equal(events, after_events)
        ):
            raise ValueError("Methods must preserve canonical event samples and codes.")
        if stim_data is not None and (stage_id != "resample" or after_grid == grid):
            if not np.array_equal(raw.get_data(picks=stim_names), stim_data, equal_nan=True):
                raise ValueError("This method must preserve stimulus channel samples.")
        if stage_id not in {"initial_reference", "reference_channel_drop", "channel_selection"} and not context.condition_branch:
            policy.validate(raw, context.params)
        if stage_id == "final_reference" and not context.average_reference_applied:
            raise ValueError("The final reference method did not confirm successful referencing.")
    except (PipelineExecutionError, PipelineCancelled):
        raise
    except Exception as exc:
        raise PipelineExecutionError(
            f"Processing method {method.method_id!r} violated the contract for step {stage_id!r}: {exc}"
        ) from exc
