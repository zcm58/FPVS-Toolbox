"""Plain-language alert summaries for SNR spectral QC findings."""
from __future__ import annotations


BIOSEMI_64_SCALP_CHANNEL_COUNT = 64


def _numeric(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag_count(flag: dict[str, object]) -> int:
    try:
        return int(flag.get("flag_count") or 0)
    except (TypeError, ValueError):
        return 1


def _format_range(low: object, high: object) -> str:
    low_val = _numeric(low)
    high_val = _numeric(high)
    if low_val is None or high_val is None:
        return "unknown frequency range"
    if abs(low_val - high_val) < 1e-9:
        return f"{low_val:.2f} Hz"
    return f"{low_val:.2f}-{high_val:.2f} Hz"


def _format_uv(value: object) -> str:
    value_float = _numeric(value)
    if value_float is None:
        return "unknown FFT amplitude"
    return f"{value_float:.2f} uV"


def _format_snr(value: object) -> str:
    value_float = _numeric(value)
    if value_float is None:
        return "unknown"
    return f"{value_float:.2f}"


def _merge_numeric_field(
    entry: dict[str, object],
    field: str,
    incoming: object,
    chooser,
) -> None:
    incoming_float = _numeric(incoming)
    if incoming_float is None:
        return
    current_float = _numeric(entry.get(field))
    if current_float is None:
        entry[field] = incoming_float
        return
    entry[field] = chooser(current_float, incoming_float)


def _summarize_condition_groups(
    flags: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for flag in flags:
        condition = str(flag.get("condition") or "").strip()
        pid = str(flag.get("pid") or "").strip()
        electrode = str(flag.get("electrode") or "").strip()
        if not condition or not pid:
            continue
        key = (condition, pid)
        entry = grouped.setdefault(
            key,
            {
                "condition": condition,
                "pid": pid,
                "electrodes": set(),
                "flag_count": 0,
                "min_frequency_hz": flag.get("min_frequency_hz"),
                "max_frequency_hz": flag.get("max_frequency_hz"),
                "max_fft_amplitude_uv": flag.get("max_fft_amplitude_uv"),
                "max_snr": flag.get("max_snr"),
                "strongest_electrode": electrode,
                "strongest_electrode_fft": flag.get("max_fft_amplitude_uv"),
            },
        )
        if electrode:
            entry["electrodes"].add(electrode)
        entry["flag_count"] = int(entry["flag_count"]) + _flag_count(flag)
        for field, chooser in (
            ("min_frequency_hz", min),
            ("max_frequency_hz", max),
            ("max_fft_amplitude_uv", max),
            ("max_snr", max),
        ):
            _merge_numeric_field(entry, field, flag.get(field), chooser)
        incoming_fft = _numeric(flag.get("max_fft_amplitude_uv"))
        strongest_fft = _numeric(entry.get("strongest_electrode_fft"))
        if electrode and incoming_fft is not None and (
            strongest_fft is None or incoming_fft > strongest_fft
        ):
            entry["strongest_electrode"] = electrode
            entry["strongest_electrode_fft"] = incoming_fft

    summaries = []
    for entry in grouped.values():
        electrodes = sorted(str(value) for value in entry["electrodes"])
        summaries.append(
            {
                **entry,
                "electrodes": electrodes,
                "electrode_count": len(electrodes),
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            -int(item["flag_count"]),
            -int(item["electrode_count"]),
            str(item["pid"]),
            str(item["condition"]),
        ),
    )


def _is_widespread_group(group: dict[str, object]) -> bool:
    try:
        electrode_count = int(group.get("electrode_count") or 0)
    except (TypeError, ValueError):
        electrode_count = 0
    try:
        flag_count = int(group.get("flag_count") or 0)
    except (TypeError, ValueError):
        flag_count = 0
    return electrode_count >= 12 or (electrode_count >= 8 and flag_count >= 100)


def _is_whole_participant_candidate(group: dict[str, object]) -> bool:
    try:
        electrode_count = int(group.get("electrode_count") or 0)
    except (TypeError, ValueError):
        electrode_count = 0
    return electrode_count >= BIOSEMI_64_SCALP_CHANNEL_COUNT


def _summarize_localized_flags(
    flags: list[dict[str, object]],
    *,
    excluded_condition_pid: set[tuple[str, str]] | None = None,
) -> list[dict[str, object]]:
    excluded_condition_pid = excluded_condition_pid or set()
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for flag in flags:
        condition = str(flag.get("condition") or "").strip()
        pid = str(flag.get("pid") or "").strip()
        electrode = str(flag.get("electrode") or "").strip()
        if (condition, pid) in excluded_condition_pid:
            continue
        if not pid or not electrode:
            continue
        key = (pid, electrode)
        entry = grouped.setdefault(
            key,
            {
                "pid": pid,
                "electrode": electrode,
                "conditions": set(),
                "flag_count": 0,
                "min_frequency_hz": flag.get("min_frequency_hz"),
                "max_frequency_hz": flag.get("max_frequency_hz"),
                "max_fft_amplitude_uv": flag.get("max_fft_amplitude_uv"),
                "max_snr": flag.get("max_snr"),
            },
        )
        if condition:
            entry["conditions"].add(condition)
        entry["flag_count"] = int(entry["flag_count"]) + _flag_count(flag)
        for field, chooser in (
            ("min_frequency_hz", min),
            ("max_frequency_hz", max),
            ("max_fft_amplitude_uv", max),
            ("max_snr", max),
        ):
            _merge_numeric_field(entry, field, flag.get(field), chooser)

    summaries = []
    for entry in grouped.values():
        conditions = sorted(str(value) for value in entry["conditions"])
        summaries.append({**entry, "conditions": conditions})
    return sorted(
        summaries,
        key=lambda item: (
            -int(item["flag_count"]),
            str(item["pid"]),
            str(item["electrode"]),
        ),
    )


def whole_participant_exclusion_candidates(
    flags: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return PIDs with 64-channel spectral QC failures."""

    candidates_by_pid: dict[str, dict[str, object]] = {}
    for group in _summarize_condition_groups(flags):
        if not _is_whole_participant_candidate(group):
            continue
        pid = str(group.get("pid") or "").strip()
        if not pid:
            continue
        entry = candidates_by_pid.setdefault(
            pid,
            {
                "pid": pid,
                "conditions": [],
                "max_electrode_count": 0,
                "flag_count": 0,
            },
        )
        entry["conditions"].append(str(group.get("condition") or "unknown condition"))
        entry["max_electrode_count"] = max(
            int(entry["max_electrode_count"]),
            int(group.get("electrode_count") or 0),
        )
        entry["flag_count"] = int(entry["flag_count"]) + int(
            group.get("flag_count") or 0
        )
    for entry in candidates_by_pid.values():
        entry["conditions"] = sorted(set(entry["conditions"]))
    return sorted(
        candidates_by_pid.values(),
        key=lambda item: (
            str(item["pid"]),
        ),
    )


def build_spectral_qc_alert_message(
    flags: list[dict[str, object]],
    report_paths: list[str],
) -> str:
    """Build the GUI warning text for report-only spectral QC flags."""
    condition_groups = _summarize_condition_groups(flags)
    widespread_groups = [
        group for group in condition_groups if _is_widespread_group(group)
    ]
    widespread_keys = {
        (str(group["condition"]), str(group["pid"])) for group in widespread_groups
    }
    localized_summaries = _summarize_localized_flags(
        flags,
        excluded_condition_pid=widespread_keys,
    )
    if not widespread_groups and not localized_summaries:
        return ""

    total_flags = sum(_flag_count(flag) for flag in flags)
    whole_participant_candidates = whole_participant_exclusion_candidates(flags)
    localized_count = len(localized_summaries)
    lines = [
        "Spectral QC found non-harmonic spectral artifacts.",
        "",
        "Plots and processed data were not changed.",
        "",
        f"Flagged rows: {total_flags}",
    ]

    if whole_participant_candidates:
        lines.extend(["", "Whole-participant exclusion candidate(s):"])
        for item in whole_participant_candidates:
            conditions = ", ".join(item["conditions"])
            lines.append(
                f"- {item['pid']}: all {BIOSEMI_64_SCALP_CHANNEL_COUNT} scalp electrodes "
                f"were flagged in {conditions}."
            )
        lines.extend(
            [
                "",
                "Recommendation: exclude these participant(s), then reprocess the dataset.",
            ]
        )

    review_widespread_groups = [
        group for group in widespread_groups if not _is_whole_participant_candidate(group)
    ]
    if review_widespread_groups:
        widespread_label = (
            "group" if len(review_widespread_groups) == 1 else "groups"
        )
        lines.extend(
            [
                "",
                f"Widespread artifacts needing review: {len(review_widespread_groups)} participant/condition {widespread_label}.",
                "Review these before deciding whether to exclude a participant or a targeted channel.",
            ]
        )
    if localized_count:
        pair_label = "pair" if localized_count == 1 else "pairs"
        lines.extend(
            [
                "",
                f"Localized electrode candidates: {localized_count} participant-electrode {pair_label}.",
                "Review the workbook before adding any channel-level exclusions.",
            ]
        )

    if report_paths:
        first_path = str(report_paths[0])
        from pathlib import Path

        report_dir = str(Path(first_path).parent)
        report_names = [Path(path).name for path in report_paths[:4]]
        lines.extend(
            [
                "",
                f"Full details were saved in: {report_dir}",
                "Reports: " + ", ".join(report_names),
            ]
        )
        if len(report_paths) > 4:
            lines.append(f"Plus {len(report_paths) - 4} additional report(s).")
    return "\n".join(lines)


__all__ = [
    "BIOSEMI_64_SCALP_CHANNEL_COUNT",
    "build_spectral_qc_alert_message",
    "whole_participant_exclusion_candidates",
]
