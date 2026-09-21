"""Versioned scientific questions and correction families for planned FHC runs.

Comparison identity describes a calculation; correction membership is separate.
The plan is frozen before spectra are read and never inferred from observed p's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Sequence

from Main_App.projects import load_project_dataset_index

from .models import AnalysisDesign, FreeHarmonicInputError, RecordingExclusionRequest

ANALYSIS_PLAN_VERSION = "fhc_analysis_families_v2"


class AnalysisFamily(str, Enum):
    BETWEEN_GROUPS = "between_groups"
    BETWEEN_CONDITIONS = "between_conditions"
    WITHIN_GROUP_VISITS = "within_group_visits"
    GROUP_VISIT_CHANGE = "group_visit_change"


FAMILY_LABELS = {
    AnalysisFamily.BETWEEN_GROUPS: "Between-group differences",
    AnalysisFamily.BETWEEN_CONDITIONS: "Between-condition differences",
    AnalysisFamily.WITHIN_GROUP_VISITS: "Within-group visit changes",
    AnalysisFamily.GROUP_VISIT_CHANGE: "Between-group differences in visit change",
}


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PlannedComparison:
    comparison_id: str
    family_id: str
    family_label: str
    label: str
    kind: AnalysisFamily
    design: AnalysisDesign
    condition_a: str
    condition_b: str | None
    group_ids: tuple[str, ...]
    session_ids: tuple[str, ...]

    @property
    def condition(self) -> str:
        if self.condition_b and self.condition_b != self.condition_a:
            return f"{self.condition_a} - {self.condition_b}"
        return self.condition_a

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "family_id": self.family_id,
            "family_label": self.family_label,
            "label": self.label,
            "kind": self.kind.value,
            "design": self.design.value,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "group_ids": list(self.group_ids),
            "session_ids": list(self.session_ids),
        }


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    project_root: Path
    group_ids: tuple[str, ...]
    conditions: tuple[str, ...]
    session_ids: tuple[str, ...]
    families: tuple[AnalysisFamily, ...]
    condition_pairs: tuple[tuple[str, str], ...]
    recording_exclusions: tuple[RecordingExclusionRequest, ...]
    comparisons: tuple[PlannedComparison, ...]
    group_labels: tuple[str, ...]
    session_labels: tuple[str, ...]
    version: str = ANALYSIS_PLAN_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root).expanduser().resolve(strict=False))
        if self.version != ANALYSIS_PLAN_VERSION:
            raise ValueError("Unsupported FHC analysis-plan version.")
        if not self.comparisons:
            raise FreeHarmonicInputError("Select at least one applicable analysis family.")
        ids = [row.comparison_id for row in self.comparisons]
        if len(set(ids)) != len(ids):
            raise ValueError("Planned comparison identities must be unique.")
        if any(not row.family_id.strip() for row in self.comparisons):
            raise ValueError("Every planned comparison requires a correction family.")

    @property
    def fingerprint(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        # The managed root is a storage location, not scientific plan identity.
        return {
            "version": self.version,
            "group_ids": list(self.group_ids),
            "group_labels": list(self.group_labels),
            "conditions": list(self.conditions),
            "session_ids": list(self.session_ids),
            "session_labels": list(self.session_labels),
            "families": [family.value for family in self.families],
            "condition_pairs": [list(pair) for pair in self.condition_pairs],
            "recording_exclusions": [
                {"recording_id": row.recording_id, "reason": row.reason} for row in self.recording_exclusions
            ],
            "comparisons": [row.to_dict() for row in self.comparisons],
            "multiplicity": "Holm across run-global two-sided p values within each planned family; full-plan Holm reported separately",
            "unavailable_comparison_policy": "fail_complete_plan",
            "visit_direction": "session_ids[0] minus session_ids[1]",
            "seed_strategy": "comparison identity only, fpvs-fhc-planned-comparison-seed-v2",
        }


def _unique(values: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(str(value).strip() for value in values)
    if any(not value for value in result) or len({value.casefold() for value in result}) != len(result):
        raise FreeHarmonicInputError(f"{label} must contain distinct non-empty values.")
    return result


def build_analysis_plan(
    project_root: str | Path,
    *,
    group_ids: Sequence[str],
    conditions: Sequence[str],
    session_ids: Sequence[str] = (),
    families: Sequence[AnalysisFamily | str] | None = None,
    condition_pairs: Sequence[tuple[str, str]] = (),
    recording_exclusions: Sequence[RecordingExclusionRequest] = (),
    project_options: object | None = None,
) -> AnalysisPlan:
    """Resolve canonical project identities and enumerate every planned test.

    Repeated defaults are between groups, within-group visits, and group change.
    Flat multi-group defaults are between groups. A single-group flat design
    defaults to paired condition comparisons. Condition pairs are all pairwise
    unless an explicit ordered list (for example condition minus reference) is given.
    """
    root = Path(project_root).expanduser().resolve(strict=False)
    if project_options is None and (not root.is_dir() or not (root / "project.json").is_file()):
        raise FreeHarmonicInputError("Analysis plans require an existing managed project.json.")
    index = load_project_dataset_index(root) if project_options is None else project_options
    if index.project_root.resolve(strict=False) != root:
        raise FreeHarmonicInputError("The dataset index resolved to a different project root.")
    group_lookup = {
        row.group_id.casefold(): row for row in (index.ordered_groups if project_options is None else index.groups)
    }
    session_lookup = {
        row.session_id.casefold(): row
        for row in (index.ordered_sessions if project_options is None else index.sessions)
    }
    condition_lookup = {value.casefold(): value for value in index.conditions}
    try:
        groups = tuple(group_lookup[value.casefold()] for value in _unique(group_ids, "group_ids"))
        sessions = tuple(session_lookup[value.casefold()] for value in _unique(session_ids, "session_ids"))
        selected_conditions = tuple(condition_lookup[value.casefold()] for value in _unique(conditions, "conditions"))
    except KeyError as exc:
        raise FreeHarmonicInputError(f"Unknown canonical group, session, or condition: {exc.args[0]!r}.") from exc
    if not selected_conditions:
        raise FreeHarmonicInputError("Select at least one condition.")
    if bool(getattr(index, "is_repeated_session", bool(index.sessions))) != bool(sessions):
        raise FreeHarmonicInputError(
            "Repeated-session projects require two explicitly ordered sessions; flat projects do not use sessions."
        )
    if sessions and len(sessions) != 2:
        raise FreeHarmonicInputError("Planned visit comparisons require exactly two ordered sessions.")
    if not groups and group_lookup:
        raise FreeHarmonicInputError("Select at least one canonical group.")
    if sessions and not groups:
        raise FreeHarmonicInputError("Repeated-session plans require canonical group metadata.")
    ids = tuple(row.group_id for row in groups)
    visits = tuple(row.session_id for row in sessions)
    defaults: list[AnalysisFamily] = []
    if len(groups) >= 2:
        defaults.append(AnalysisFamily.BETWEEN_GROUPS)
    if sessions:
        defaults.append(AnalysisFamily.WITHIN_GROUP_VISITS)
        if len(groups) >= 2:
            defaults.append(AnalysisFamily.GROUP_VISIT_CHANGE)
    elif len(groups) < 2:
        defaults.append(AnalysisFamily.BETWEEN_CONDITIONS)
    enabled = tuple(defaults if families is None else (AnalysisFamily(value) for value in families))
    if len(set(enabled)) != len(enabled):
        raise FreeHarmonicInputError("Analysis families must be selected once.")
    for family in enabled:
        if family in (AnalysisFamily.BETWEEN_GROUPS, AnalysisFamily.GROUP_VISIT_CHANGE) and len(groups) < 2:
            raise FreeHarmonicInputError("Between-group comparisons require at least two selected groups.")
        if family in (AnalysisFamily.WITHIN_GROUP_VISITS, AnalysisFamily.GROUP_VISIT_CHANGE) and not sessions:
            raise FreeHarmonicInputError("Visit comparisons require two ordered sessions.")
        if family is AnalysisFamily.BETWEEN_CONDITIONS and len(selected_conditions) < 2:
            raise FreeHarmonicInputError("Between-condition comparisons require at least two conditions.")
    pairs: list[tuple[str, str]] = []
    if AnalysisFamily.BETWEEN_CONDITIONS in enabled:
        for pair in condition_pairs or tuple(combinations(selected_conditions, 2)):
            if len(pair) != 2:
                raise FreeHarmonicInputError("Each condition pair requires two ordered conditions.")
            lookup = {value.casefold(): value for value in selected_conditions}
            try:
                a, b = (lookup[str(value).strip().casefold()] for value in pair)
            except KeyError as exc:
                raise FreeHarmonicInputError("Condition pairs must use selected conditions.") from exc
            if a == b or frozenset((a, b)) in {frozenset(row) for row in pairs}:
                raise FreeHarmonicInputError(
                    "Condition pairs must be distinct; reversed duplicates are not additional tests."
                )
            pairs.append((a, b))
    elif condition_pairs:
        raise FreeHarmonicInputError("Condition pairs require the between-condition family.")
    exclusions = tuple(recording_exclusions)
    if any(not isinstance(row, RecordingExclusionRequest) for row in exclusions):
        raise TypeError("recording_exclusions must contain RecordingExclusionRequest values.")
    if len({row.recording_id.casefold() for row in exclusions}) != len(exclusions):
        raise FreeHarmonicInputError("Analysis recording exclusions must be unique.")
    known_recordings = (
        {str(value).casefold() for value in index.recordings}
        if project_options is None
        else {row.recording_id.casefold() for row in index.recordings}
    )
    if any(row.recording_id.casefold() not in known_recordings for row in exclusions):
        raise FreeHarmonicInputError("Analysis exclusions reference an unknown canonical recording.")
    rows: list[PlannedComparison] = []
    labels = {row.group_id: row.label for row in groups}
    visit_label = " - ".join(row.label for row in sessions)

    def append(family: AnalysisFamily, group_pair: tuple[str, ...], a: str, b: str | None, label: str) -> None:
        design = (
            AnalysisDesign.INDEPENDENT_GROUPS
            if family in (AnalysisFamily.BETWEEN_GROUPS, AnalysisFamily.GROUP_VISIT_CHANGE)
            else AnalysisDesign.PAIRED_CONDITIONS
        )
        recipe = [
            family.value,
            [value.casefold() for value in group_pair],
            a.casefold(),
            None if b is None else b.casefold(),
            [value.casefold() for value in visits],
        ]
        rows.append(
            PlannedComparison(
                comparison_id="comparison_" + _digest(recipe),
                family_id=family.value,
                family_label=FAMILY_LABELS[family],
                label=label,
                kind=family,
                design=design,
                condition_a=a,
                condition_b=b,
                group_ids=group_pair,
                session_ids=visits,
            )
        )

    for family in enabled:
        if family in (AnalysisFamily.BETWEEN_GROUPS, AnalysisFamily.GROUP_VISIT_CHANGE):
            for pair in combinations(ids, 2):
                for condition in selected_conditions:
                    suffix = (
                        f"; change in {visit_label}"
                        if family is AnalysisFamily.GROUP_VISIT_CHANGE
                        else ("; session average" if visits else "")
                    )
                    append(family, pair, condition, None, f"{labels[pair[0]]} - {labels[pair[1]]}: {condition}{suffix}")
        elif family is AnalysisFamily.WITHIN_GROUP_VISITS:
            for group in ids:
                for condition in selected_conditions:
                    append(family, (group,), condition, condition, f"{labels[group]}: {visit_label}; {condition}")
        else:
            for group in ids or ("",):
                for a, b in pairs:
                    append(
                        family,
                        (group,) if group else (),
                        a,
                        b,
                        f"{labels.get(group, 'All participants')}: {a} - {b}" + ("; session average" if visits else ""),
                    )
    used_conditions = {value for row in rows for value in (row.condition_a, row.condition_b) if value}
    return AnalysisPlan(
        project_root=root,
        group_ids=ids,
        conditions=tuple(value for value in selected_conditions if value in used_conditions),
        session_ids=visits,
        families=enabled,
        condition_pairs=tuple(pairs),
        recording_exclusions=exclusions,
        comparisons=tuple(rows),
        group_labels=tuple(row.label for row in groups),
        session_labels=tuple(row.label for row in sessions),
    )
