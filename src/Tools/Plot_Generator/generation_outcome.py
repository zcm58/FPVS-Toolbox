"""Pure worker-outcome normalization and completion-summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


MANAGED_ANALYSIS_SOURCE_KIND = "managed_full_fft_provenance"


@dataclass(frozen=True)
class NormalizedWorkerOutcome:
    """Validated collection values from one Plot Generator worker payload."""

    generated_paths: tuple[str, ...]
    spectral_qc_flags: tuple[dict[str, object], ...]
    failed_items: tuple[dict[str, str], ...]
    warning_items: tuple[dict[str, str], ...]
    cancelled: bool
    analysis_source_kind: str | None
    analysis_project_root: str | None
    post_processing_required_reason: str | None


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
        cancelled=payload.get("cancelled") is True,
        analysis_source_kind=_optional_payload_string(
            payload,
            "analysis_source_kind",
        ),
        analysis_project_root=_optional_payload_string(
            payload,
            "analysis_project_root",
        ),
        post_processing_required_reason=_optional_payload_string(
            payload,
            "post_processing_required_reason",
        ),
    )


def managed_analysis_matches_active_project(
    *,
    analysis_source_kind: str | None,
    analysis_project_root: str | Path | None,
    active_project_root: str | Path | None,
) -> bool:
    """Return whether a run may update the active project's exclusions."""

    if analysis_source_kind != MANAGED_ANALYSIS_SOURCE_KIND:
        return False
    resolved_analysis_root = _resolved_nonempty_path(analysis_project_root)
    resolved_active_root = _resolved_nonempty_path(active_project_root)
    return (
        resolved_analysis_root is not None
        and resolved_active_root is not None
        and resolved_analysis_root == resolved_active_root
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


def _optional_payload_string(
    payload: Mapping[str, object],
    key: str,
) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _resolved_nonempty_path(value: str | Path | None) -> Path | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return Path(value).resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _pluralized(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural
