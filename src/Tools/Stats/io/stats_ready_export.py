"""Stats-ready Summed BCA workbook export helpers."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from Tools.Stats.analysis.dv_policies import normalize_dv_policy, prepare_summed_bca_data

STATS_READY_WORKBOOK_NAME = "Stats_Ready_Summed_BCA.xlsx"
SINGLE_GROUP_LABEL = "single_group"

RSTUDIO_LONG_SHEET = "RStudio_Long"
SAS_LONG_SHEET = "SAS_Long"
JASP_RM_ANOVA_SHEET = "JASP_RM_ANOVA"
JASP_LONG_MIXED_SHEET = "JASP_Long_Mixed"
DATA_DICTIONARY_SHEET = "Data_Dictionary"
ANALYSIS_RECIPES_SHEET = "Analysis_Recipes"


@dataclass(frozen=True)
class StatsReadyExport:
    """Prepared workbook frames and lightweight export metadata."""

    frames: dict[str, pd.DataFrame]
    workbook_path: Path | None
    row_count: int


def _safe_text(value: object, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _numeric_or_nan(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _parse_frequency(value: object) -> float | None:
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if text.endswith("_Hz"):
        text = text[:-3]
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _format_harmonics(freqs: list[float]) -> str:
    return ";".join(f"{freq:g}" for freq in freqs)


def _format_z_scores(z_by_harmonic: Mapping[object, object]) -> str:
    pairs: list[tuple[float, float]] = []
    for raw_freq, raw_z in (z_by_harmonic or {}).items():
        freq = _parse_frequency(raw_freq)
        z_val = _numeric_or_nan(raw_z)
        if freq is not None and math.isfinite(z_val):
            pairs.append((freq, z_val))
    return ";".join(f"{freq:g}:{z_val:.4g}" for freq, z_val in sorted(pairs))


def _harmonics_from_provenance(provenance: Mapping[str, object]) -> list[float]:
    labels = provenance.get("col_label")
    if labels is None:
        return []
    if not isinstance(labels, (list, tuple, set)):
        labels = [labels]
    freqs: list[float] = []
    for label in labels:
        freq = _parse_frequency(label)
        if freq is not None:
            freqs.append(freq)
    return sorted(set(freqs))


def _harmonics_for_roi(
    roi: str,
    *,
    dv_metadata: Mapping[str, object],
    provenance: Mapping[str, object],
) -> list[float]:
    rossion_meta = dv_metadata.get("rossion_method")
    if isinstance(rossion_meta, Mapping):
        union_map = rossion_meta.get("union_harmonics_by_roi")
        if isinstance(union_map, Mapping):
            roi_freqs = union_map.get(roi)
            if isinstance(roi_freqs, (list, tuple, set)):
                freqs = [_parse_frequency(freq) for freq in roi_freqs]
                return sorted(freq for freq in freqs if freq is not None)
    return _harmonics_from_provenance(provenance)


def _common_rossion_meta(dv_metadata: Mapping[str, object]) -> Mapping[str, object]:
    rossion_meta = dv_metadata.get("rossion_method")
    return rossion_meta if isinstance(rossion_meta, Mapping) else {}


def _fallback_info_for_roi(
    roi: str,
    *,
    dv_metadata: Mapping[str, object],
    default_policy: str,
) -> tuple[str, bool]:
    rossion_meta = dv_metadata.get("rossion_method")
    if isinstance(rossion_meta, Mapping):
        fallback_map = rossion_meta.get("fallback_info_by_roi")
        if isinstance(fallback_map, Mapping):
            roi_info = fallback_map.get(roi)
            if isinstance(roi_info, Mapping):
                policy = _safe_text(roi_info.get("policy"), default=default_policy)
                return policy, bool(roi_info.get("fallback_used", False))
    return default_policy, False


def _resolve_group_labels(
    subjects: list[str],
    group_map: Mapping[str, object] | None,
) -> dict[str, str]:
    if not group_map:
        return {subject: SINGLE_GROUP_LABEL for subject in subjects}

    labels: dict[str, str | None] = {}
    has_known_group = False
    for subject in subjects:
        group_value = group_map.get(subject)
        if group_value is None:
            group_value = group_map.get(subject.upper())
        group = _safe_text(group_value)
        if group:
            has_known_group = True
            labels[subject] = group
        else:
            labels[subject] = None

    if not has_known_group:
        return {subject: SINGLE_GROUP_LABEL for subject in subjects}

    missing = [subject for subject, group in labels.items() if not group]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Group labels are missing for exported subject(s): "
            f"{joined}. Fix project participant metadata before exporting stats-ready data."
        )
    return {subject: str(group) for subject, group in labels.items()}


def _subject_uids(subjects: list[str], group_labels: Mapping[str, str]) -> dict[str, str]:
    counts = Counter(subjects)
    out: dict[str, str] = {}
    for subject in subjects:
        if counts[subject] <= 1:
            out[subject] = subject
            continue
        out[subject] = f"{_safe_identifier(group_labels[subject])}__{_safe_identifier(subject)}"
    return out


def _safe_identifier(value: object) -> str:
    text = re.sub(r"[^0-9A-Za-z_]+", "_", _safe_text(value, default="value"))
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "value"
    if text[0].isdigit():
        text = f"v_{text}"
    return text


def _wide_column_names(conditions: list[str], rois: list[str]) -> dict[tuple[str, str], str]:
    raw_names = {
        (condition, roi): f"{_safe_identifier(condition)}__{_safe_identifier(roi)}"
        for condition in conditions
        for roi in rois
    }
    counts: Counter[str] = Counter()
    out: dict[tuple[str, str], str] = {}
    for key, raw in raw_names.items():
        counts[raw] += 1
        out[key] = raw if counts[raw] == 1 else f"{raw}_{counts[raw]}"
    return out


def _build_long_frame(
    *,
    subjects: list[str],
    conditions: list[str],
    rois: list[str],
    subject_data: Mapping[str, Mapping[str, str]],
    summed_bca: Mapping[str, Mapping[str, Mapping[str, object]]],
    provenance_map: Mapping[tuple[str, str, str], Mapping[str, object]],
    dv_metadata: Mapping[str, object],
    dv_policy: Mapping[str, object] | None,
    group_map: Mapping[str, object] | None,
) -> pd.DataFrame:
    settings = normalize_dv_policy(dict(dv_policy or {}))
    policy_name = _safe_text(dv_metadata.get("policy_name"), default=settings.name)
    default_empty_policy = _safe_text(
        dv_metadata.get("empty_list_policy"),
        default=settings.empty_list_policy,
    )
    rossion_meta = _common_rossion_meta(dv_metadata)
    selection_scope = _safe_text(rossion_meta.get("selection_scope"))
    z_scores = _format_z_scores(rossion_meta.get("selection_z_by_harmonic", {}))
    excluded_base = []
    raw_excluded = rossion_meta.get("excluded_base_harmonics_hz")
    if isinstance(raw_excluded, (list, tuple, set)):
        excluded_base = [_parse_frequency(freq) for freq in raw_excluded]
    excluded_base_text = _format_harmonics([freq for freq in excluded_base if freq is not None])
    group_labels = _resolve_group_labels(subjects, group_map)
    uid_map = _subject_uids(subjects, group_labels)

    rows: list[dict[str, object]] = []
    for subject in subjects:
        for condition_order, condition in enumerate(conditions, start=1):
            condition_data = summed_bca.get(subject, {}).get(condition, {})
            source_file = subject_data.get(subject, {}).get(condition, "")
            for roi_order, roi in enumerate(rois, start=1):
                provenance = provenance_map.get((subject, condition, roi), {})
                harmonics = _harmonics_for_roi(
                    roi,
                    dv_metadata=dv_metadata,
                    provenance=provenance,
                )
                empty_policy, fallback_used = _fallback_info_for_roi(
                    roi,
                    dv_metadata=dv_metadata,
                    default_policy=default_empty_policy,
                )
                source_workbook = _safe_text(
                    provenance.get("source_file"),
                    default=_safe_text(source_file),
                )
                rows.append(
                    {
                        "subject_uid": uid_map[subject],
                        "subject_id": subject,
                        "group_id": group_labels[subject],
                        "condition": condition,
                        "roi": roi,
                        "summed_bca_uv": _numeric_or_nan(condition_data.get(roi)),
                        "condition_order": condition_order,
                        "roi_order": roi_order,
                        "metric": "summed_bca",
                        "value_units": "uV",
                        "dv_policy": policy_name,
                        "selected_harmonics_hz": _format_harmonics(harmonics),
                        "harmonic_count": len(harmonics),
                        "selection_scope": selection_scope,
                        "selection_z_scores": z_scores,
                        "excluded_base_harmonics_hz": excluded_base_text,
                        "empty_harmonic_policy": empty_policy,
                        "fallback_used": fallback_used,
                        "source_workbook": source_workbook,
                    }
                )

    columns = [
        "subject_uid",
        "subject_id",
        "group_id",
        "condition",
        "roi",
        "summed_bca_uv",
        "condition_order",
        "roi_order",
        "metric",
        "value_units",
        "dv_policy",
        "selected_harmonics_hz",
        "harmonic_count",
        "selection_scope",
        "selection_z_scores",
        "excluded_base_harmonics_hz",
        "empty_harmonic_policy",
        "fallback_used",
        "source_workbook",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        raise RuntimeError("Stats-ready export produced no subject x condition x ROI rows.")
    if not frame["summed_bca_uv"].notna().any():
        raise RuntimeError(
            "Stats-ready export produced no finite Summed BCA values. "
            "Check source workbooks, selected ROIs, and harmonic policy settings."
        )
    return frame


def _build_sas_long_frame(long_df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "condition_order": "condition_n",
        "roi_order": "roi_n",
        "selected_harmonics_hz": "harmonics_hz",
        "harmonic_count": "harmonic_n",
        "selection_z_scores": "z_scores",
        "excluded_base_harmonics_hz": "excluded_base_hz",
        "empty_harmonic_policy": "empty_policy",
        "source_workbook": "source_file",
    }
    columns = [
        "subject_uid",
        "subject_id",
        "group_id",
        "condition",
        "roi",
        "summed_bca_uv",
        "condition_n",
        "roi_n",
        "dv_policy",
        "harmonics_hz",
        "harmonic_n",
        "selection_scope",
        "z_scores",
        "excluded_base_hz",
        "empty_policy",
        "fallback_used",
        "source_file",
    ]
    return long_df.rename(columns=rename).loc[:, columns].copy()


def _build_jasp_wide_frame(
    long_df: pd.DataFrame,
    *,
    conditions: list[str],
    rois: list[str],
) -> tuple[pd.DataFrame, dict[tuple[str, str], str]]:
    column_map = _wide_column_names(conditions, rois)
    id_columns = ["subject_uid", "subject_id", "group_id"]
    subjects_df = long_df.loc[:, id_columns].drop_duplicates().reset_index(drop=True)

    wide = subjects_df.copy()
    for condition in conditions:
        for roi in rois:
            column = column_map[(condition, roi)]
            values = long_df[
                (long_df["condition"] == condition) & (long_df["roi"] == roi)
            ].loc[:, ["subject_uid", "summed_bca_uv"]]
            values = values.rename(columns={"summed_bca_uv": column})
            wide = wide.merge(values, on="subject_uid", how="left")
    return wide, column_map


def _build_data_dictionary(
    *,
    wide_column_map: Mapping[tuple[str, str], str],
    long_df: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "subject_uid",
            "description": "Unique subject key for analysis.",
            "units": "",
        },
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "group_id",
            "description": "Between-subject experimental group label.",
            "units": "",
        },
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "summed_bca_uv",
            "description": "Baseline-corrected amplitude summed across selected harmonics and averaged within ROI electrodes.",
            "units": "uV",
        },
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "selected_harmonics_hz",
            "description": "Semicolon-delimited harmonic frequencies selected by the active DV policy.",
            "units": "Hz",
        },
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "selection_z_scores",
            "description": "Semicolon-delimited frequency:z-score pairs from the group-level harmonic-selection spectrum.",
            "units": "",
        },
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "excluded_base_harmonics_hz",
            "description": "Base-rate harmonics excluded from oddball summation.",
            "units": "Hz",
        },
        {
            "sheet": RSTUDIO_LONG_SHEET,
            "column": "fallback_used",
            "description": "True when the active policy used an explicit empty-harmonic fallback for that ROI.",
            "units": "",
        },
    ]
    harmonic_lookup = (
        long_df.groupby(["condition", "roi"], dropna=False)["selected_harmonics_hz"]
        .first()
        .to_dict()
    )
    for (condition, roi), column in wide_column_map.items():
        rows.append(
            {
                "sheet": JASP_RM_ANOVA_SHEET,
                "column": column,
                "description": "Wide repeated-measures cell for one condition x ROI.",
                "units": "uV",
                "original_condition": condition,
                "original_roi": roi,
                "selected_harmonics_hz": harmonic_lookup.get((condition, roi), ""),
            }
        )
    return pd.DataFrame(rows)


def _build_analysis_recipes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "software": "RStudio",
                "data_sheet": RSTUDIO_LONG_SHEET,
                "analysis": "RM-ANOVA",
                "recipe": "Import with readxl, treat subject_uid as the subject id, condition and roi as within-subject factors, and group_id as a between-subject factor when groups are present.",
            },
            {
                "software": "RStudio",
                "data_sheet": RSTUDIO_LONG_SHEET,
                "analysis": "Linear mixed model",
                "recipe": "Fit summed_bca_uv from group_id, condition, roi, and their interactions with a subject_uid random effect appropriate for the study design.",
            },
            {
                "software": "SAS",
                "data_sheet": SAS_LONG_SHEET,
                "analysis": "PROC MIXED",
                "recipe": "Import the sheet, declare subject_uid, group_id, condition, and roi as CLASS variables, then model summed_bca_uv with within- and between-subject terms.",
            },
            {
                "software": "JASP",
                "data_sheet": JASP_RM_ANOVA_SHEET,
                "analysis": "Repeated-measures ANOVA",
                "recipe": "Open the workbook, choose this wide sheet, assign condition x ROI columns to repeated-measures cells, and use group_id as the between-subject factor when groups are present.",
            },
            {
                "software": "JASP",
                "data_sheet": JASP_LONG_MIXED_SHEET,
                "analysis": "Mixed model",
                "recipe": "Use the long sheet for mixed-model workflows with subject_uid as the participant identifier and summed_bca_uv as the dependent variable.",
            },
        ]
    )


def build_stats_ready_frames(
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: Mapping[str, Mapping[str, str]],
    rois: Mapping[str, list[str]],
    summed_bca: Mapping[str, Mapping[str, Mapping[str, object]]],
    provenance_map: Mapping[tuple[str, str, str], Mapping[str, object]],
    dv_metadata: Mapping[str, object],
    dv_policy: Mapping[str, object] | None = None,
    group_map: Mapping[str, object] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build all stats-ready workbook sheets from canonical Summed BCA data."""

    subject_list = [str(subject) for subject in subjects]
    condition_list = [str(condition) for condition in conditions]
    roi_names = [str(roi) for roi in rois.keys()]
    if not subject_list:
        raise RuntimeError("Stats-ready export requires at least one subject.")
    if len(condition_list) < 2:
        raise RuntimeError("Stats-ready export requires at least two selected conditions.")
    if not roi_names:
        raise RuntimeError("Stats-ready export requires at least one ROI.")

    long_df = _build_long_frame(
        subjects=subject_list,
        conditions=condition_list,
        rois=roi_names,
        subject_data=subject_data,
        summed_bca=summed_bca,
        provenance_map=provenance_map,
        dv_metadata=dv_metadata,
        dv_policy=dv_policy,
        group_map=group_map,
    )
    sas_df = _build_sas_long_frame(long_df)
    jasp_wide_df, wide_column_map = _build_jasp_wide_frame(
        long_df,
        conditions=condition_list,
        rois=roi_names,
    )
    dictionary_df = _build_data_dictionary(
        wide_column_map=wide_column_map,
        long_df=long_df,
    )
    recipes_df = _build_analysis_recipes()
    return {
        RSTUDIO_LONG_SHEET: long_df,
        SAS_LONG_SHEET: sas_df,
        JASP_RM_ANOVA_SHEET: jasp_wide_df,
        JASP_LONG_MIXED_SHEET: long_df.copy(),
        DATA_DICTIONARY_SHEET: dictionary_df,
        ANALYSIS_RECIPES_SHEET: recipes_df,
        "Harmonic_Selection": _build_harmonic_selection_frame(dv_metadata),
    }


def _build_harmonic_selection_frame(dv_metadata: Mapping[str, object]) -> pd.DataFrame:
    rossion_meta = _common_rossion_meta(dv_metadata)
    if not rossion_meta:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    _append_selection_rows(
        rows,
        selection_scope=_safe_text(rossion_meta.get("selection_scope")),
        z_map=rossion_meta.get("selection_z_by_harmonic"),
        selected_harmonics=rossion_meta.get("common_harmonics_hz"),
        excluded_harmonics=rossion_meta.get("excluded_base_harmonics_hz"),
        sensitivity=False,
    )
    sensitivity_meta = rossion_meta.get("sensitivity_union_roi_electrodes")
    if isinstance(sensitivity_meta, Mapping):
        _append_selection_rows(
            rows,
            selection_scope=_safe_text(sensitivity_meta.get("selection_scope")),
            z_map=sensitivity_meta.get("selection_z_by_harmonic"),
            selected_harmonics=sensitivity_meta.get("harmonics_hz"),
            excluded_harmonics=sensitivity_meta.get("excluded_base_harmonics_hz"),
            sensitivity=True,
        )
    return pd.DataFrame(rows).sort_values(["sensitivity", "harmonic_hz"]) if rows else pd.DataFrame()


def _append_selection_rows(
    rows: list[dict[str, object]],
    *,
    selection_scope: str,
    z_map: object,
    selected_harmonics: object,
    excluded_harmonics: object,
    sensitivity: bool,
) -> None:
    selected = {
        float(freq)
        for freq in (selected_harmonics if isinstance(selected_harmonics, (list, tuple, set)) else [])
    }
    excluded = {
        float(freq)
        for freq in (excluded_harmonics if isinstance(excluded_harmonics, (list, tuple, set)) else [])
    }
    seen_harmonics: set[float] = set()
    if isinstance(z_map, Mapping):
        for raw_freq, raw_z in z_map.items():
            freq = _parse_frequency(raw_freq)
            if freq is None:
                continue
            seen_harmonics.add(freq)
            rows.append(
                {
                    "selection_scope": selection_scope,
                    "harmonic_hz": freq,
                    "z_score": _numeric_or_nan(raw_z),
                    "selected": freq in selected,
                    "excluded_base_rate": freq in excluded,
                    "sensitivity": sensitivity,
                }
            )
    for freq in sorted(excluded.difference(seen_harmonics)):
        rows.append(
            {
                "selection_scope": selection_scope,
                "harmonic_hz": freq,
                "z_score": math.nan,
                "selected": False,
                "excluded_base_rate": True,
                "sensitivity": sensitivity,
            }
        )


def write_stats_ready_workbook(
    save_path: str | Path,
    frames: Mapping[str, pd.DataFrame],
) -> Path:
    """Write the stats-ready workbook as plain rectangular Excel sheets."""

    target = Path(save_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet_name, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return target


def prepare_stats_ready_export(
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: Mapping[str, Mapping[str, str]],
    base_freq: float,
    rois: Mapping[str, list[str]],
    dv_policy: Mapping[str, object] | None,
    group_map: Mapping[str, object] | None,
    log_func: Callable[[str], None],
    save_path: str | Path | None = None,
    max_freq: float | None = None,
    selection_conditions: list[str] | None = None,
) -> StatsReadyExport:
    """Prepare and optionally write the external-statistics Summed BCA export."""

    provenance_map: dict[tuple[str, str, str], dict[str, object]] = {}
    dv_metadata: dict[str, object] = {}
    summed_bca = prepare_summed_bca_data(
        subjects=list(subjects),
        conditions=list(conditions),
        subject_data=dict(subject_data),
        base_freq=float(base_freq),
        log_func=log_func,
        rois=dict(rois),
        provenance_map=provenance_map,
        dv_policy=dict(dv_policy or {}),
        dv_metadata=dv_metadata,
        max_freq=max_freq,
        selection_conditions=selection_conditions,
    )
    if not summed_bca:
        raise RuntimeError("Stats-ready export could not prepare Summed BCA data.")

    frames = build_stats_ready_frames(
        subjects=list(subjects),
        conditions=list(conditions),
        subject_data=subject_data,
        rois=rois,
        summed_bca=summed_bca,
        provenance_map=provenance_map,
        dv_metadata=dv_metadata,
        dv_policy=dv_policy,
        group_map=group_map,
    )
    workbook_path = write_stats_ready_workbook(save_path, frames) if save_path else None
    return StatsReadyExport(
        frames=frames,
        workbook_path=workbook_path,
        row_count=len(frames[RSTUDIO_LONG_SHEET]),
    )
