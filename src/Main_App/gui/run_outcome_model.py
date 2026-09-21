"""Presentation-only summaries of existing processing outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence


@dataclass(frozen=True)
class RunOutcome:
    completed: int = 0
    skipped: int = 0
    excluded: int = 0
    failed: int = 0
    interrupted: int = 0
    condition_warnings: int = 0

    def text(self, *, cancelled: bool, failure_reason: str, success: bool) -> str:
        if cancelled:
            state = "Cancelled"
        elif failure_reason or not success or self.failed or self.interrupted:
            state = "Incomplete"
        elif self.excluded or self.condition_warnings:
            state = "Finished with review notes"
        else:
            state = "Complete"
        counts = (f"{self.completed} completed · {self.skipped} reused · "
                  f"{self.excluded} excluded · {self.failed} failed")
        if self.interrupted:
            counts += f" · {self.interrupted} unfinished"
        if self.condition_warnings:
            counts += f" · {self.condition_warnings} with missing conditions"
        readiness = " Analysis outputs are not ready." if failure_reason else ""
        return f"Last run: {state}. {counts}.{readiness}"


def summarize_run(
    *, results: Sequence[dict], failures: Sequence[dict], exclusions: Sequence[dict],
    reused_files: Sequence[str] = (), previously_excluded: Sequence[str] = (),
    interrupted_files: Sequence[str] = (), condition_warnings: Sequence[dict] = (),
) -> RunOutcome:
    """Count recording identities once, preferring final failures over success."""
    def key(value) -> str:
        return str(Path(str(value)).resolve())

    def keys(rows) -> set[str]:
        return {key(row["file"]) for row in rows if row.get("file")}

    interrupted = {key(path) for path in interrupted_files}
    excluded = keys(exclusions) | {key(path) for path in previously_excluded}
    failed = keys(failures) - excluded - interrupted
    completed = keys([row for row in results if str(row.get("status", "")).lower()
                      in {"ok", "completed", "success"}]) - failed - excluded - interrupted
    reused = {key(path) for path in reused_files} - completed - failed - excluded - interrupted
    return RunOutcome(len(completed), len(reused), len(excluded), len(failed),
                      len(interrupted), len(keys(condition_warnings)))
