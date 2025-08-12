from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Callable

from Main_App.Legacy_App.post_process import post_process


@dataclass
class LegacyCtx:
    preprocessed_data: Dict[str, Any]
    save_folder_path: SimpleNamespace
    data_paths: List[str]
    log: Callable[[str], None]
    pid_for_group: str | None = None
    group_name_for_output: str | None = None


def run_post_export(ctx: LegacyCtx, labels: List[str]) -> None:
    """Delegate to the legacy post_process function."""
    post_process(ctx, labels)
