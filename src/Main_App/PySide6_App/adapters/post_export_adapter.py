from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
from Main_App.Legacy_App.post_process import post_process as _legacy_post_process


@dataclass
class LegacyCtx:
    """Data-only context for legacy post_process (no QWidget, no Qt)."""
    preprocessed_data: Dict[str, Any]
    save_folder_path: Any | None = None   # may expose .get()
    data_paths: List[str] | None = None
    settings: Optional[Any] = None
    log: Optional[Callable[[str], None]] = None


def run_post_export(ctx: LegacyCtx, labels: List[str]) -> None:
    """Execute the legacy export routine with a pure context."""
    _legacy_post_process(ctx, labels)
