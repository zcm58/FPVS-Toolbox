"""Pure worker-outcome normalization and completion-summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class NormalizedWorkerOutcome:
    """Validated collection values from one Plot Generator worker payload."""

    generated_paths: tuple[str, ...]
    qc_report_paths: tuple[str, ...]
    spectral_qc_flags: tuple[dict[str, object], ...]
    failed_items: tuple[dict[str, str], ...]
    warning_items: tuple[dict[str, str], ...]


def normalize_worker_outcome(
    payload: Mapping[str, object],
) -> NormalizedWorkerOutcome:
    """Return only well-formed values that the GUI can safely aggregate."""

    return NormalizedWorkerOutcome(
        generated_paths=tuple(
            str(path)
            for path in _payload_list(payload, "generated_paths")
            if isinstance(path, str) and path
        ),
        qc_report_paths=tuple(
            str(path)
            for path in _payload_list(payload, "qc_report_paths")
            if isinstance(path, str) and path
        ),
        spectral_qc_flags=tuple(
            dict(item)
            for item in _payload_list(payload, "spectral_qc_flags")
            if isinstance(item, dict)
        ),
        failed_items=tuple(
            {
                "item": str(item.get("item", "")),
                "error": str(item.get("error", "")),
            }
            for item in _payload_list(payload, "failed_items")
            if isinstance(item, dict)
        ),
        warning_items=tuple(
            {
                "code": str(item.get("code", "")),
                "item": str(item.get("item", "")),
                "message": str(item.get("message", "")),
            }
            for item in _payload_list(payload, "warning_items")
            if isinstance(item, dict)
        ),
    )


def format_completion_summary(
    *,
    generated_count: int,
    warning_count: int,
    failed_count: int,
) -> str:
    """Return a concise, grammatically correct run summary."""

    parts = [
        f"Generated {generated_count} "
        f"{_pluralized(generated_count, 'figure file', 'figure files')}"
    ]
    if warning_count:
        parts.append(
            f"{warning_count} "
            f"{_pluralized(warning_count, 'warning', 'warnings')}"
        )
    if failed_count:
        parts.append(
            f"{failed_count} "
            f"{_pluralized(failed_count, 'failed item', 'failed items')}"
        )
    return "; ".join(parts) + "."


def format_no_plots_message(*, warning_count: int) -> str:
    """Return the no-output message with an optional warning count."""

    message = "No plots were generated. Please check the log for errors."
    if not warning_count:
        return message
    warning_label = _pluralized(warning_count, "warning was", "warnings were")
    return f"{message} {warning_count} {warning_label} reported."


def _payload_list(
    payload: Mapping[str, object],
    key: str,
) -> tuple[object, ...]:
    value = payload.get(key, [])
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _pluralized(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural
