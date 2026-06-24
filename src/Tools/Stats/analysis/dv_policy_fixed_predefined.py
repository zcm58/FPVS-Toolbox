"""Fixed predefined harmonic-list Summed BCA DV policy helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    FIXED_PREDEFINED_POLICY_ID,
    FIXED_PREDEFINED_POLICY_LABEL,
    LOCKED_ODDBALL_FREQUENCY_HZ,
)
from Tools.Stats.analysis.stats_analysis import _current_rois_map
from Tools.Stats.io.xlsx_selected_reader import (
    MissingXlsxColumnsError,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
)


@dataclass(frozen=True)
class FixedHarmonicRow:
    requested_frequency_hz: float
    matched_frequency_hz: float | None
    matched_column: str | None
    matched_bin_index: int | None
    included: bool
    exclusion_reason: str
    warning: str


@dataclass(frozen=True)
class FixedHarmonicSelection:
    requested_values: list[float]
    requested_frequencies_hz: list[float]
    matched_frequencies_hz: list[float]
    matched_columns: list[str]
    matched_bin_indices: list[int]
    included_frequencies_hz: list[float]
    included_columns: list[str]
    included_bin_indices: list[int]
    excluded_base_overlap_frequencies_hz: list[float]
    duplicate_frequencies_hz: list[float]
    oddball_frequency_hz: float
    base_frequency_hz: float
    base_overlap_exclusion_enabled: bool
    base_overlap_tolerance_hz: float
    matching_tolerance_hz: float
    frequency_resolution_hz: float | None
    validation_status: str
    warnings: list[str]
    rows: list[FixedHarmonicRow]

    def to_metadata(self) -> dict[str, object]:
        return {
            "harmonic_policy": FIXED_PREDEFINED_POLICY_ID,
            "harmonic_policy_label": FIXED_PREDEFINED_POLICY_LABEL,
            "dependent_variable": "summed_bca",
            "fixed_harmonic_input_mode": "frequency_hz",
            "fixed_harmonic_requested_values": list(self.requested_values),
            "fixed_harmonic_requested_frequencies_hz": list(self.requested_frequencies_hz),
            "fixed_harmonic_matched_frequencies_hz": list(self.matched_frequencies_hz),
            "fixed_harmonic_matched_columns": list(self.matched_columns),
            "fixed_harmonic_bin_indices": list(self.matched_bin_indices),
            "fixed_harmonic_included_frequencies_hz": list(self.included_frequencies_hz),
            "fixed_harmonic_included_columns": list(self.included_columns),
            "fixed_harmonic_included_bin_indices": list(self.included_bin_indices),
            "fixed_harmonic_indices": [
                _harmonic_index(freq, self.oddball_frequency_hz)
                for freq in self.included_frequencies_hz
            ],
            "base_frequency_hz": float(self.base_frequency_hz),
            "oddball_frequency_hz": float(self.oddball_frequency_hz),
            "base_overlap_exclusion_enabled": bool(self.base_overlap_exclusion_enabled),
            "excluded_base_overlap_frequencies_hz": list(self.excluded_base_overlap_frequencies_hz),
            "duplicate_frequencies_hz": list(self.duplicate_frequencies_hz),
            "base_overlap_tolerance_hz": float(self.base_overlap_tolerance_hz),
            "matching_tolerance_hz": float(self.matching_tolerance_hz),
            "frequency_resolution_hz": self.frequency_resolution_hz,
            "validation_status": self.validation_status,
            "warnings": list(self.warnings),
            "applied_uniformly_across_participants": True,
            "applied_uniformly_across_conditions": True,
            "applied_uniformly_across_rois": True,
            "snr_used_for_statistics": False,
            "bca_negative_values_retained": True,
            "bca_near_zero_values_retained": True,
            "selection_rows": [
                {
                    "requested_frequency_hz": row.requested_frequency_hz,
                    "matched_frequency_hz": row.matched_frequency_hz,
                    "matched_column": row.matched_column,
                    "matched_bin_index": row.matched_bin_index,
                    "included": row.included,
                    "exclusion_reason": row.exclusion_reason,
                    "warning": row.warning,
                }
                for row in self.rows
            ],
            "methods_summary": _methods_summary(self),
        }


def parse_fixed_harmonic_frequency_list(value: object) -> list[float]:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Enter at least one harmonic frequency in Hz.")
    out: list[float] = []
    for part in text.replace(";", ",").split(","):
        item = part.strip()
        if not item:
            continue
        if item.lower().endswith("hz"):
            item = item[:-2].strip()
        try:
            freq = float(item)
        except ValueError as exc:
            raise ValueError(f"Invalid harmonic frequency: {part!r}") from exc
        if not np.isfinite(freq) or freq <= 0:
            raise ValueError(f"Harmonic frequencies must be positive finite values: {part!r}")
        out.append(float(freq))
    if not out:
        raise ValueError("Enter at least one harmonic frequency in Hz.")
    return out


def build_fixed_harmonic_selection(
    *,
    requested_values: object,
    bca_columns: Sequence[object],
    base_frequency_hz: float,
    auto_exclude_base_overlaps: bool = True,
    base_overlap_tolerance_hz: float = 0.01,
    matching_tolerance_hz: float = 0.01,
) -> FixedHarmonicSelection:
    requested_raw = parse_fixed_harmonic_frequency_list(requested_values)
    base = float(base_frequency_hz)
    oddball = float(LOCKED_ODDBALL_FREQUENCY_HZ)
    bca_freqs = _parse_bca_frequency_columns(bca_columns)
    if not bca_freqs:
        raise RuntimeError("No frequency columns found in the BCA (uV) sheet.")

    frequency_resolution = _frequency_resolution([freq for freq, _column, _idx in bca_freqs])
    warnings: list[str] = []
    rows: list[FixedHarmonicRow] = []
    seen_requested: set[float] = set()
    seen_columns: set[str] = set()
    requested_unique: list[float] = []
    duplicate_freqs: list[float] = []
    excluded_base: list[float] = []
    included_freqs: list[float] = []
    included_columns: list[str] = []
    included_indices: list[int] = []
    matched_freqs: list[float] = []
    matched_columns: list[str] = []
    matched_indices: list[int] = []
    validation_errors: list[str] = []

    for freq in requested_raw:
        rounded = round(float(freq), 6)
        if rounded in seen_requested:
            duplicate_freqs.append(float(freq))
            warnings.append(f"Duplicate requested frequency ignored: {freq:g} Hz")
            rows.append(
                FixedHarmonicRow(
                    requested_frequency_hz=float(freq),
                    matched_frequency_hz=None,
                    matched_column=None,
                    matched_bin_index=None,
                    included=False,
                    exclusion_reason="duplicate_request",
                    warning="Duplicate requested frequency ignored.",
                )
            )
            continue
        seen_requested.add(rounded)
        requested_unique.append(float(freq))

        if _is_base_overlap(freq, base, base_overlap_tolerance_hz):
            excluded_base.append(float(freq))
            warning = "Base-rate overlap excluded."
            if not auto_exclude_base_overlaps:
                warning = "Base-rate overlap retained because auto-exclusion is disabled."
                warnings.append(f"Base-rate overlap retained: {freq:g} Hz")
            else:
                warnings.append(f"Base-rate overlap excluded: {freq:g} Hz")
                rows.append(
                    FixedHarmonicRow(
                        requested_frequency_hz=float(freq),
                        matched_frequency_hz=None,
                        matched_column=None,
                        matched_bin_index=None,
                        included=False,
                        exclusion_reason="base_rate_overlap",
                        warning=warning,
                    )
                )
                continue

        exact_match = _exact_bca_frequency(bca_freqs, freq)
        if exact_match is None:
            validation_errors.append(
                f"{freq:g} Hz requires exact BCA column {float(freq):.4f}_Hz."
            )
            rows.append(
                FixedHarmonicRow(
                    requested_frequency_hz=float(freq),
                    matched_frequency_hz=None,
                    matched_column=None,
                    matched_bin_index=None,
                    included=False,
                    exclusion_reason="missing_exact_bca_column",
                    warning=(
                        f"Exact BCA column {float(freq):.4f}_Hz is missing. "
                        "Nearest-column fallback is disabled."
                    ),
                )
            )
            continue
        matched_freq, matched_column, matched_index = exact_match

        if matched_column in seen_columns:
            warnings.append(f"Duplicate matched BCA column ignored: {matched_column}")
            rows.append(
                FixedHarmonicRow(
                    requested_frequency_hz=float(freq),
                    matched_frequency_hz=matched_freq,
                    matched_column=matched_column,
                    matched_bin_index=matched_index,
                    included=False,
                    exclusion_reason="duplicate_matched_column",
                    warning="Duplicate matched BCA column ignored.",
                )
            )
            continue

        seen_columns.add(matched_column)
        matched_freqs.append(float(matched_freq))
        matched_columns.append(str(matched_column))
        matched_indices.append(int(matched_index))
        included_freqs.append(float(matched_freq))
        included_columns.append(str(matched_column))
        included_indices.append(int(matched_index))
        rows.append(
            FixedHarmonicRow(
                requested_frequency_hz=float(freq),
                matched_frequency_hz=float(matched_freq),
                matched_column=str(matched_column),
                matched_bin_index=int(matched_index),
                included=True,
                exclusion_reason="",
                warning="",
            )
        )

    validation_status = "ok" if included_freqs and not validation_errors else "error"
    if validation_errors:
        raise RuntimeError(
            "Fixed predefined harmonic list validation failed: "
            + " ".join(validation_errors)
        )
    if not included_freqs:
        raise RuntimeError(
            "Fixed predefined harmonic list produced no included BCA harmonics. "
            "Check the requested frequencies, base-overlap option, and source workbook columns."
        )

    return FixedHarmonicSelection(
        requested_values=requested_raw,
        requested_frequencies_hz=requested_unique,
        matched_frequencies_hz=matched_freqs,
        matched_columns=matched_columns,
        matched_bin_indices=matched_indices,
        included_frequencies_hz=included_freqs,
        included_columns=included_columns,
        included_bin_indices=included_indices,
        excluded_base_overlap_frequencies_hz=excluded_base,
        duplicate_frequencies_hz=duplicate_freqs,
        oddball_frequency_hz=float(oddball),
        base_frequency_hz=float(base),
        base_overlap_exclusion_enabled=bool(auto_exclude_base_overlaps),
        base_overlap_tolerance_hz=float(base_overlap_tolerance_hz),
        matching_tolerance_hz=float(matching_tolerance_hz),
        frequency_resolution_hz=frequency_resolution,
        validation_status=validation_status,
        warnings=warnings,
        rows=rows,
    )


def build_fixed_predefined_preview_payload(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    dv_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = DVPolicySettings() if dv_policy is None else _settings_from_policy(dv_policy)
    columns = _find_first_bca_columns(subjects, conditions, subject_data, base_freq, log_func)
    if columns is None:
        raise RuntimeError("Unable to read any BCA columns to validate fixed harmonics.")
    selection = build_fixed_harmonic_selection(
        requested_values=settings.fixed_harmonic_frequencies_hz,
        bca_columns=columns,
        base_frequency_hz=base_freq,
        auto_exclude_base_overlaps=settings.fixed_harmonic_auto_exclude_base,
        base_overlap_tolerance_hz=settings.fixed_harmonic_base_tolerance_hz,
        matching_tolerance_hz=settings.fixed_harmonic_matching_tolerance_hz,
    )
    return selection.to_metadata()


def _prepare_fixed_predefined_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    settings: DVPolicySettings,
    dv_metadata: Optional[dict[str, object]] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    columns = _find_first_bca_columns(subjects, conditions, subject_data, base_freq, log_func)
    if columns is None:
        log_func("Unable to read any BCA columns to validate fixed harmonics.")
        return None

    selection = build_fixed_harmonic_selection(
        requested_values=settings.fixed_harmonic_frequencies_hz,
        bca_columns=columns,
        base_frequency_hz=base_freq,
        auto_exclude_base_overlaps=settings.fixed_harmonic_auto_exclude_base,
        base_overlap_tolerance_hz=settings.fixed_harmonic_base_tolerance_hz,
        matching_tolerance_hz=settings.fixed_harmonic_matching_tolerance_hz,
    )
    log_func(
        "Fixed predefined harmonics selected: "
        + ", ".join(f"{freq:g} Hz" for freq in selection.included_frequencies_hz)
    )

    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            roi_values = {roi_name: np.nan for roi_name in rois_map.keys()}
            roi_provenance: dict[str, dict[str, object]] = {}
            if file_path and Path(file_path).exists():
                roi_values, roi_provenance = _aggregate_bca_sum_harmonics_for_all_rois(
                    file_path=file_path,
                    rois=rois_map,
                    log_func=log_func,
                    harmonic_freqs=list(selection.included_frequencies_hz),
                    provenance_enabled=provenance_map is not None,
                )
            else:
                log_func(f"Missing file for {pid} {cond_name}: {file_path}")
            for roi_name in rois_map.keys():
                sum_val = roi_values.get(roi_name, np.nan)
                all_subject_data[pid][cond_name][roi_name] = sum_val
                if provenance_map is not None:
                    provenance = {
                        "source_file": file_path,
                        "sheet": "BCA (uV)",
                        "row_label": None,
                        "col_label": list(selection.included_columns),
                        "raw_cell": None,
                        "harmonic_policy": FIXED_PREDEFINED_POLICY_ID,
                    }
                    if roi_name in roi_provenance:
                        provenance.update(roi_provenance[roi_name])
                    provenance["col_label"] = list(selection.included_columns)
                    provenance_map[(pid, cond_name, roi_name)] = provenance

    if dv_metadata is not None:
        dv_metadata.update(
            settings.to_metadata(base_freq=base_freq, selected_conditions=conditions)
        )
        dv_metadata["policy_name"] = settings.name
        dv_metadata["fixed_predefined_harmonics"] = selection.to_metadata()

    total = 0
    finite = 0
    for pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")
    log_func("Summed BCA data prep complete.")
    return all_subject_data


def _settings_from_policy(dv_policy: dict[str, object]) -> DVPolicySettings:
    from Tools.Stats.analysis.dv_policy_settings import normalize_dv_policy

    return normalize_dv_policy(dv_policy)


def _find_first_bca_columns(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    _base_freq: float,
    log_func: Callable[[str], None],
) -> Optional[pd.Index]:
    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path:
                continue
            try:
                header = read_xlsx_sheet_header(
                    file_path,
                    sheet_name="BCA (uV)",
                )
                return pd.Index(column for column in header if column != "Electrode")
            except Exception as exc:  # noqa: BLE001
                log_func(f"Failed to read BCA columns from {file_path}: {exc}")
    return None


def _aggregate_bca_sum_harmonics(
    file_path: str,
    roi_name: str,
    log_func: Callable[[str], None],
    harmonic_freqs: List[float],
    rois: Optional[Dict[str, List[str]]] = None,
    diag_meta: Optional[dict[str, object]] = None,
) -> float:
    try:
        if diag_meta is not None:
            diag_meta.setdefault("source_file", file_path)
            diag_meta.setdefault("sheet", "BCA (uV)")
            diag_meta.setdefault("row_label", None)
            diag_meta.setdefault("col_label", None)
            diag_meta.setdefault("raw_cell", None)

        roi_map = rois if rois is not None else _current_rois_map()
        values, provenance = _aggregate_bca_sum_harmonics_for_all_rois(
            file_path=file_path,
            rois={roi_name: list(roi_map.get(roi_name, []))},
            log_func=log_func,
            harmonic_freqs=harmonic_freqs,
            provenance_enabled=diag_meta is not None,
        )
        if diag_meta is not None and roi_name in provenance:
            diag_meta.update(provenance[roi_name])
        return values.get(roi_name, np.nan)

    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, RuntimeError):
            raise
        log_func(f"Error aggregating fixed predefined BCA for {file_path}, ROI {roi_name}: {exc}")
        return np.nan


def _aggregate_bca_sum_harmonics_for_all_rois(
    *,
    file_path: str,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    harmonic_freqs: List[float],
    provenance_enabled: bool,
) -> tuple[dict[str, float], dict[str, dict[str, object]]]:
    values = {roi_name: np.nan for roi_name in rois.keys()}
    provenance: dict[str, dict[str, object]] = {}
    cols_to_sum = [f"{float(freq_val):.4f}_Hz" for freq_val in harmonic_freqs]
    try:
        df_bca = read_xlsx_sheet_selected_columns(
            file_path,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", *cols_to_sum],
        )
    except MissingXlsxColumnsError as exc:
        missing_columns = [column for column in cols_to_sum if column in exc.missing_columns]
        if missing_columns:
            raise RuntimeError(
                "Fixed predefined harmonic summation requires exact BCA harmonic "
                f"columns in every included workbook. Missing columns in {file_path}: "
                f"{missing_columns[:8]}"
            ) from exc
        log_func(f"Error reading BCA sheet for {file_path}: {exc}")
        return values, provenance
    except Exception as exc:  # noqa: BLE001
        log_func(f"Error reading BCA sheet for {file_path}: {exc}")
        return values, provenance

    if "Electrode" not in df_bca.columns:
        log_func(f"Error reading BCA sheet for {file_path}: missing Electrode column")
        return values, provenance

    df_bca = df_bca.set_index("Electrode")
    df_bca.index = df_bca.index.astype(str).str.upper().str.strip()
    missing_columns = [column for column in cols_to_sum if column not in df_bca.columns]
    if missing_columns:
        raise RuntimeError(
            "Fixed predefined harmonic summation requires exact BCA harmonic "
            f"columns in every included workbook. Missing columns in {file_path}: "
            f"{missing_columns[:8]}"
        )

    numeric_bca = (
        df_bca[cols_to_sum]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    for roi_name, roi_channels in rois.items():
        roi_channel_names = [
            str(ch).strip().upper()
            for ch in (roi_channels or [])
        ]
        if not roi_channel_names:
            log_func(f"ROI {roi_name} not defined.")
            continue

        roi_chans = [ch for ch in roi_channel_names if ch in numeric_bca.index]
        if not roi_chans:
            log_func(f"No overlapping BCA data for ROI {roi_name} in {file_path}.")
            continue
        df_bca_roi = numeric_bca.loc[roi_chans].dropna(how="all")
        if df_bca_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            if provenance_enabled:
                provenance[roi_name] = _empty_fixed_provenance(
                    file_path,
                    row_label=roi_chans,
                    col_label=cols_to_sum,
                )
            continue

        if provenance_enabled:
            provenance[roi_name] = {
                "source_file": file_path,
                "sheet": "BCA (uV)",
                "row_label": roi_chans,
                "col_label": cols_to_sum,
                "raw_cell": df_bca_roi[cols_to_sum].to_dict(orient="index"),
                "harmonic_policy": FIXED_PREDEFINED_POLICY_ID,
            }

        bca_vals = df_bca_roi.sum(axis=1, min_count=1)
        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        if not bca_vals.notna().any():
            log_func(
                f"Warning: All-NaN BCA values after summation for ROI {roi_name} "
                f"({file_path})."
            )
            continue

        out = float(bca_vals.mean(skipna=True))
        values[roi_name] = out if np.isfinite(out) else np.nan
    return values, provenance


def _empty_fixed_provenance(
    file_path: str | None,
    *,
    row_label: list[str],
    col_label: list[str],
) -> dict[str, object]:
    return {
        "source_file": file_path,
        "sheet": "BCA (uV)",
        "row_label": row_label,
        "col_label": col_label,
        "raw_cell": None,
        "harmonic_policy": FIXED_PREDEFINED_POLICY_ID,
    }


def _parse_bca_frequency_columns(columns: Sequence[object]) -> list[tuple[float, str, int]]:
    out: list[tuple[float, str, int]] = []
    for idx, col_name in enumerate(columns):
        if not isinstance(col_name, str) or not col_name.endswith("_Hz"):
            continue
        try:
            out.append((float(col_name[:-3]), col_name, idx))
        except ValueError:
            continue
    return sorted(out, key=lambda item: item[0])


def _exact_bca_frequency(
    bca_freqs: Sequence[tuple[float, str, int]],
    requested_freq: float,
) -> tuple[float, str, int] | None:
    required_column = f"{float(requested_freq):.4f}_Hz"
    for matched_freq, matched_column, matched_index in bca_freqs:
        if str(matched_column) == required_column and abs(float(matched_freq) - float(requested_freq)) <= 1e-9:
            return float(matched_freq), str(matched_column), int(matched_index)
    return None


def _frequency_resolution(freqs: Sequence[float]) -> float | None:
    unique = sorted(set(float(freq) for freq in freqs))
    if len(unique) < 2:
        return None
    diffs = np.diff(np.asarray(unique, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return None
    return float(np.median(diffs))


def _is_base_overlap(freq: float, base: float, tolerance_hz: float) -> bool:
    if base <= 0:
        return False
    multiple = round(float(freq) / float(base))
    if multiple <= 0:
        return False
    return abs(float(freq) - multiple * float(base)) < float(tolerance_hz)


def _harmonic_index(freq: float, oddball: float) -> int | None:
    if oddball <= 0:
        return None
    return int(round(float(freq) / float(oddball)))


def _methods_summary(selection: FixedHarmonicSelection) -> str:
    harmonics = ", ".join(f"{freq:g}" for freq in selection.included_frequencies_hz)
    return (
        "Baseline-corrected amplitudes were summed across a fixed predefined set "
        f"of oddball harmonics ({harmonics} Hz) to create the response amplitude "
        "used for statistical analysis. Frequencies overlapping with the base "
        "stimulation frequency and its harmonics were excluded when the "
        "base-overlap option was enabled. The same selected harmonic set was "
        "applied to each participant, condition, and ROI. SNR values were not "
        "used as the primary dependent variable."
    )
