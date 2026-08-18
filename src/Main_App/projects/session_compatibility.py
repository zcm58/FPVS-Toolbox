"""Explicit compatibility gates for tools not yet recording-aware."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .recordings import load_project_recording_context


def repeated_session_tool_block_reason(
    project_root: str | Path | None,
    *,
    tool_name: str,
) -> str | None:
    """Return a protective block reason for a repeated-session project.

    Invalid project recording metadata is allowed to raise so callers cannot
    silently treat a malformed repeated project as a flat project.
    """

    if project_root is None:
        return None
    root = Path(project_root).expanduser().resolve(strict=False)
    manifest_path = root / "project.json"
    if not manifest_path.is_file():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and not any(
        payload.get(field)
        for field in ("sessions", "recording_sources", "recordings")
    ):
        # Preserve exact legacy-tool behavior for flat projects. Their unrelated
        # historical metadata need not pass the stricter v2.2 normalizers merely
        # to establish that no repeated recordings can be collapsed.
        return None
    context = load_project_recording_context(root)
    if not context.is_repeated_session:
        return None
    label = str(tool_name).strip() or "This tool"
    return (
        f"{label} is not yet recording-aware and is disabled for repeated-session "
        "projects. This protective gate prevents multiple visits from being "
        "collapsed or treated as independent participants. Use the session-aware "
        "SNR Plot Generator, Scalp Maps, repeated-session Stats workflow, or the "
        "session-aware long-format export instead."
    )


__all__ = ["repeated_session_tool_block_reason"]
