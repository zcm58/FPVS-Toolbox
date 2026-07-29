"""Immutable, GUI-neutral preparation boundary for native Stats inference.

The design audit is intentionally performed once.  Downstream workers receive
the resulting :class:`PreparedAnalysisPayload` and must not rediscover project
files, repeat QC decisions, or recompute the complete-condition intersection.
Dataframe-valued properties return defensive copies so callers cannot mutate
the stored analysis cohort accidentally.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import json
from typing import Mapping, Sequence
from uuid import uuid4

import pandas as pd

from Tools.Stats.analysis.design_audit import (
    DesignAuditResult,
    DesignStatus,
    audit_complete_core_design,
)
from Tools.Stats.analysis.inference_contracts import (
    AnalysisResultMetadata,
    AnalysisRunSpec,
)


PREPARED_ANALYSIS_SCHEMA_VERSION = 1


class PreparedAnalysisError(ValueError):
    """Raised when an analysis cannot be prepared unambiguously."""


class AnalysisMode(str, Enum):
    """Supported native inference modes."""

    SINGLE = "single"
    MULTI = "multi"

    @classmethod
    def coerce(cls, value: "AnalysisMode | str") -> "AnalysisMode":
        """Normalize user/controller spellings to a stable mode."""

        if isinstance(value, cls):
            return value
        normalized = (
            str(value).strip().casefold().replace("-", "_").replace(" ", "_")
        )
        aliases = {
            "single": cls.SINGLE,
            "single_group": cls.SINGLE,
            "singlegroup": cls.SINGLE,
            "multi": cls.MULTI,
            "multi_group": cls.MULTI,
            "multigroup": cls.MULTI,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise PreparedAnalysisError(
                "mode must be 'single' or 'multi'."
            ) from exc


def _copy_frames(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    return {str(name): frame.copy(deep=True) for name, frame in frames.items()}


def _copy_mapping(mapping: Mapping[object, object] | None) -> dict[str, object]:
    if mapping is None:
        return {}
    return {
        str(key).strip(): deepcopy(value)
        for key, value in mapping.items()
        if str(key).strip()
    }


def _normalize_pair(
    group_pair: Sequence[object] | None,
) -> tuple[str, str] | None:
    if group_pair is None:
        return None
    if isinstance(group_pair, (str, bytes)) or len(group_pair) != 2:
        raise PreparedAnalysisError(
            "selected_group_pair must contain exactly two group IDs."
        )
    group_a, group_b = (str(value).strip() for value in group_pair)
    if not group_a or not group_b or group_a.casefold() == group_b.casefold():
        raise PreparedAnalysisError(
            "selected_group_pair must contain two distinct, non-empty group IDs."
        )
    return group_a, group_b


def _validate_distinct_columns(
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    group_col: str,
) -> tuple[str, str, str, str, str]:
    columns = tuple(
        str(column).strip()
        for column in (
            dv_col,
            subject_col,
            condition_col,
            roi_col,
            group_col,
        )
    )
    if any(not column for column in columns):
        raise PreparedAnalysisError("Analysis column names must be non-empty.")
    core = columns[:4]
    if len(set(core)) != len(core):
        raise PreparedAnalysisError(
            "DV, participant, condition, and ROI columns must be distinct."
        )
    if columns[4] in core:
        raise PreparedAnalysisError(
            "The canonical group column must be distinct from the core columns."
        )
    return columns


def _canonical_assignments(
    audit: DesignAuditResult,
) -> dict[str, str]:
    assignments: dict[str, str] = {}
    if audit.group_assignments.empty:
        return assignments
    for row in audit.group_assignments.itertuples(index=False):
        participant = str(getattr(row, "participant_id")).strip()
        group_id = getattr(row, "group_id")
        status = str(getattr(row, "assignment_status")).strip()
        if participant and status == "assigned" and not pd.isna(group_id):
            assignments[participant] = str(group_id).strip()
    return assignments


def _json_safe_setting(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


@dataclass(frozen=True, slots=True)
class PreparedAnalysisPayload:
    """One audited, immutable input shared by all native inference steps."""

    preparation_id: str
    mode: AnalysisMode
    run_spec: AnalysisRunSpec
    dv_col: str
    subject_col: str
    condition_col: str
    roi_col: str
    group_col: str
    status: DesignStatus
    status_code: str
    message: str
    frozen_participants: tuple[str, ...]
    requested_conditions: tuple[str, ...]
    selected_rois: tuple[str, ...]
    complete_conditions: tuple[str, ...]
    excluded_conditions: tuple[str, ...]
    selected_group_pair: tuple[str, str] | None
    _canonical_group_ids: dict[str, str]
    _group_display_labels: dict[str, object]
    _participant_display_labels: dict[str, object]
    _settings: dict[str, object]
    _primary_data: pd.DataFrame
    _design_frames: dict[str, pd.DataFrame]

    @property
    def ready(self) -> bool:
        """Return whether downstream inference is permitted."""

        return self.status is DesignStatus.READY

    @property
    def audit_status(self) -> str:
        """Return the string-valued audit status for controller code."""

        return self.status.value

    @property
    def primary_data(self) -> pd.DataFrame:
        """Return a defensive copy of the frozen complete-core rows."""

        return self._primary_data.copy(deep=True)

    @property
    def canonical_group_ids(self) -> dict[str, str]:
        """Return participant-to-canonical-group assignments."""

        return dict(self._canonical_group_ids)

    @property
    def group_display_labels(self) -> dict[str, object]:
        """Return canonical-group display labels, when supplied."""

        return deepcopy(self._group_display_labels)

    @property
    def participant_display_labels(self) -> dict[str, object]:
        """Return participant-to-display-group labels, when supplied."""

        return deepcopy(self._participant_display_labels)

    @property
    def settings(self) -> dict[str, object]:
        """Return a defensive copy of retained analysis settings."""

        return deepcopy(self._settings)

    @property
    def design_frames(self) -> dict[str, pd.DataFrame]:
        """Return defensive copies of the one-time audit frames."""

        return _copy_frames(self._design_frames)

    @property
    def canonical_group_levels(self) -> tuple[str, ...]:
        """Return stable unique canonical group IDs in the frozen cohort."""

        return tuple(
            sorted(set(self._canonical_group_ids.values()), key=str.casefold)
        )

    def metadata_frame(self) -> pd.DataFrame:
        """Return one export-ready preparation metadata row."""

        return pd.DataFrame(
            [
                {
                    "prepared_analysis_schema_version": (
                        PREPARED_ANALYSIS_SCHEMA_VERSION
                    ),
                    "preparation_id": self.preparation_id,
                    "mode": self.mode.value,
                    "audit_status": self.status.value,
                    "status_code": self.status_code,
                    "message": self.message,
                    "dv_col": self.dv_col,
                    "subject_col": self.subject_col,
                    "condition_col": self.condition_col,
                    "roi_col": self.roi_col,
                    "group_col": self.group_col,
                    "n_frozen_participants": len(self.frozen_participants),
                    "frozen_participants": "; ".join(
                        self.frozen_participants
                    ),
                    "requested_conditions": "; ".join(
                        self.requested_conditions
                    ),
                    "complete_conditions": "; ".join(
                        self.complete_conditions
                    ),
                    "excluded_conditions": "; ".join(
                        self.excluded_conditions
                    ),
                    "selected_rois": "; ".join(self.selected_rois),
                    "selected_group_pair": (
                        ""
                        if self.selected_group_pair is None
                        else " versus ".join(self.selected_group_pair)
                    ),
                }
            ]
        )

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return all preparation and run-contract frames for export."""

        frames = self.design_frames
        frames["Primary Data"] = self.primary_data
        frames["Prepared Analysis"] = self.metadata_frame()
        frames["Group Display Labels"] = pd.DataFrame(
            [
                {"group_id": group_id, "display_label": display_label}
                for group_id, display_label in self._group_display_labels.items()
            ],
            columns=["group_id", "display_label"],
        )
        frames["Participant Display Labels"] = pd.DataFrame(
            [
                {
                    "participant_id": participant_id,
                    "display_label": display_label,
                }
                for participant_id, display_label in (
                    self._participant_display_labels.items()
                )
            ],
            columns=["participant_id", "display_label"],
        )
        frames["Analysis Settings"] = pd.DataFrame(
            [
                {"setting": key, "value": _json_safe_setting(value)}
                for key, value in self._settings.items()
            ],
            columns=["setting", "value"],
        )
        frames.update(AnalysisResultMetadata(self.run_spec).to_frames())
        return frames


def prepare_analysis_payload(
    data: pd.DataFrame,
    *,
    mode: AnalysisMode | str,
    run_spec: AnalysisRunSpec,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    group_col: str = "group_id",
    frozen_participants: Sequence[object] | None = None,
    selected_conditions: Sequence[object] | None = None,
    selected_rois: Sequence[object] | None = None,
    canonical_group_ids: Mapping[object, object] | None = None,
    group_display_labels: Mapping[object, object] | None = None,
    participant_display_labels: Mapping[object, object] | None = None,
    selected_group_pair: Sequence[object] | None = None,
    settings: Mapping[object, object] | None = None,
    preparation_id: str | None = None,
) -> PreparedAnalysisPayload:
    """Audit ``data`` once and freeze the complete-core analysis boundary."""

    if not isinstance(run_spec, AnalysisRunSpec):
        raise TypeError("run_spec must be an AnalysisRunSpec.")
    (
        dv_name,
        subject_name,
        condition_name,
        roi_name,
        group_name,
    ) = _validate_distinct_columns(
        dv_col=dv_col,
        subject_col=subject_col,
        condition_col=condition_col,
        roi_col=roi_col,
        group_col=group_col,
    )
    resolved_mode = AnalysisMode.coerce(mode)
    resolved_pair = _normalize_pair(selected_group_pair)
    copied_group_map = {
        str(participant).strip(): str(group_id).strip()
        for participant, group_id in _copy_mapping(
            canonical_group_ids
        ).items()
    }
    audit = audit_complete_core_design(
        data,
        dv_col=dv_name,
        subject_col=subject_name,
        condition_col=condition_name,
        roi_col=roi_name,
        frozen_participants=frozen_participants,
        selected_conditions=selected_conditions,
        selected_rois=selected_rois,
        canonical_group_ids=copied_group_map or None,
        require_groups=resolved_mode is AnalysisMode.MULTI,
    )
    canonical_assignments = _canonical_assignments(audit)
    primary = audit.primary_data.copy(deep=True)
    if "group_id" in primary.columns and group_name != "group_id":
        primary = primary.rename(columns={"group_id": group_name})
    elif canonical_assignments and group_name not in primary.columns:
        by_participant = {
            participant.casefold(): group_id
            for participant, group_id in canonical_assignments.items()
        }
        primary[group_name] = primary[subject_name].map(
            lambda participant: by_participant.get(
                str(participant).strip().casefold()
            )
        )

    if resolved_pair is not None and canonical_assignments:
        observed_by_key = {
            group.casefold(): group
            for group in canonical_assignments.values()
        }
        missing_pair = [
            group
            for group in resolved_pair
            if group.casefold() not in observed_by_key
        ]
        if missing_pair:
            raise PreparedAnalysisError(
                "Selected group IDs are not in the frozen cohort: "
                + ", ".join(missing_pair)
            )
        resolved_pair = tuple(
            observed_by_key[group.casefold()] for group in resolved_pair
        )

    identifier = str(preparation_id or uuid4().hex).strip()
    if not identifier:
        raise PreparedAnalysisError("preparation_id must be non-empty.")
    design_frames = audit.to_frames()
    design_frames["Primary Data"] = primary.copy(deep=True)
    return PreparedAnalysisPayload(
        preparation_id=identifier,
        mode=resolved_mode,
        run_spec=run_spec,
        dv_col=dv_name,
        subject_col=subject_name,
        condition_col=condition_name,
        roi_col=roi_name,
        group_col=group_name,
        status=audit.status,
        status_code=audit.status_code,
        message=audit.message,
        frozen_participants=tuple(audit.frozen_participants),
        requested_conditions=tuple(audit.requested_conditions),
        selected_rois=tuple(audit.selected_rois),
        complete_conditions=tuple(audit.complete_conditions),
        excluded_conditions=tuple(audit.excluded_conditions),
        selected_group_pair=resolved_pair,
        _canonical_group_ids=dict(canonical_assignments),
        _group_display_labels=_copy_mapping(group_display_labels),
        _participant_display_labels=_copy_mapping(
            participant_display_labels
        ),
        _settings=_copy_mapping(settings),
        _primary_data=primary.copy(deep=True),
        _design_frames=_copy_frames(design_frames),
    )


build_prepared_analysis_payload = prepare_analysis_payload


__all__ = [
    "AnalysisMode",
    "PREPARED_ANALYSIS_SCHEMA_VERSION",
    "PreparedAnalysisError",
    "PreparedAnalysisPayload",
    "build_prepared_analysis_payload",
    "prepare_analysis_payload",
]
