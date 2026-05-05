"""Shared helper functions for Stats summary reporting."""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


def _pick_column(df: pd.DataFrame, preferred: str, fallbacks: Iterable[str]) -> Optional[str]:
    """Return the first available column from a preferred/fallback list."""

    for name in (preferred, *fallbacks):
        if name in df.columns:
            return name
    return None
