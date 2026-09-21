"""Versioned project-local FHC plan preferences, separate from exclusions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ..analysis_plan import AnalysisFamily


ANALYSIS_PLAN_STATE_VERSION = 1
ANALYSIS_PLAN_STATE_FILENAME = "analysis_plan.json"


class AnalysisPlanStateError(ValueError):
    """Saved plan choices cannot be safely read or persisted."""


@dataclass(frozen=True, slots=True)
class AnalysisPlanPreferences:
    """Choices for future runs; completed bundles own their immutable plans."""

    families: tuple[str, ...]
    condition_mode: str = "reference"
    reference_condition: str = ""

    def __post_init__(self) -> None:
        families = tuple(AnalysisFamily(value).value for value in self.families)
        if not families or len(set(families)) != len(families):
            raise ValueError("Choose at least one analysis family, without duplicates.")
        if self.condition_mode not in {"reference", "all_pairs"}:
            raise ValueError("The saved condition-comparison mode is unsupported.")
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "reference_condition", str(self.reference_condition))


def load_analysis_plan_preferences(results_parent: Path) -> AnalysisPlanPreferences | None:
    """Load a saved choice set, failing visibly on unsupported or corrupt state."""

    path = Path(results_parent).expanduser().resolve(strict=False) / ANALYSIS_PLAN_STATE_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != ANALYSIS_PLAN_STATE_VERSION:
            raise ValueError("The saved analysis-plan version is unsupported.")
        if not isinstance(payload.get("families"), list):
            raise ValueError("Saved analysis families must be a list.")
        return AnalysisPlanPreferences(
            families=tuple(payload["families"]),
            condition_mode=payload.get("condition_mode", "reference"),
            reference_condition=payload.get("reference_condition", ""),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise AnalysisPlanStateError(f"Could not load the saved FHC analysis plan: {exc}") from exc


def save_analysis_plan_preferences(results_parent: Path, preferences: AnalysisPlanPreferences) -> Path:
    """Atomically save future-run choices without rewriting exclusion settings."""

    path = Path(results_parent).expanduser().resolve(strict=False) / ANALYSIS_PLAN_STATE_FILENAME
    temporary = path.with_suffix(".json.tmp")
    payload = {
        "schema_version": ANALYSIS_PLAN_STATE_VERSION,
        "families": list(preferences.families),
        "condition_mode": preferences.condition_mode,
        "reference_condition": preferences.reference_condition,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise AnalysisPlanStateError(f"Could not save the FHC analysis plan: {exc}") from exc
    return path
