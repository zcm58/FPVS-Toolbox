#!/usr/bin/env python3
"""
roi_sig_electrodes_report.py

Generate an Excel report of *significant* electrodes restricted to two ROIs:
  - Central ROI: FCz, Cz, CPz, CP1, C1, FC1
  - Left Occipito-Temporal (LOT) ROI: P7, P9, PO7, PO3, O1

The script processes exactly two conditions:
  - "Semantic" condition
  - "Color response 1" condition

It expects each participant Excel file to contain a sheet named "Z Score" with:
  - A column "Electrode"
  - Frequency columns named like "1.2000_Hz" (case-insensitive)

Significance logic (matches your detectability script):
  1) Combine oddball-harmonic Z scores per electrode:
       Z_comb = sum(Z_harmonics) / sqrt(K)
  2) Threshold: Z_comb >= z_threshold
  3) Optional one-tailed Benjamini–Hochberg FDR across electrodes (default ON)

How to run (no arguments):
  1) Edit the USER CONFIG section at the top of this file (ROOT is required).
  2) Click Run in your IDE, or run the script directly.

Output:
  - WideCounts: one row per participant with ROI counts per condition
  - LongCounts: tidy/long format table (participant x condition x ROI)
  - Errors: any files that failed parsing/processing
  - Metadata: settings, ROI definitions, matched condition folders
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
from typing import Sequence

import numpy as np
import pandas as pd

# =============================================================================
# USER CONFIG (edit these; no command-line arguments needed)
# =============================================================================

# Root folder containing condition folders (or .xlsx files).
# Example (Windows):
#   ROOT = r"C:\path\to\results"
# Example (relative to this script):
#   ROOT = str(Path(__file__).resolve().parents[2] / "results")
ROOT = r"C:\Users\zcm58\OneDrive - Mississippi State University\Office Desktop\FPVS Toolbox Project Root\Semantic Categories 3\1 - Excel Data Files"

# Output .xlsx path. If blank, defaults to: <ROOT>/roi_sig_electrodes_report.xlsx
OUT_XLSX = r"C:\Users\zcm58\OneDrive - Mississippi State University\Office Desktop\FPVS Toolbox Project Root\Semantic Categories 3\newreport.xlsx"

# Regex patterns to match the two condition folder names under ROOT
SEMANTIC_PATTERN = r"\bsemantic\b"
COLOR1_PATTERN = r"\bcolor\b.*\bresponse\b.*\b1\b|\bcolor\b.*\b1\b|\bresponse\b.*\b1\b"

# ROI definitions
ROI_DEFS: dict[str, list[str]] = {
    "Central": ["FCz", "Cz", "CPz", "CP1", "C1", "FC1"],
    "LOT": ["P7", "P9", "PO7", "PO3", "O1"],
}

# Oddball harmonics to combine (Hz). Do NOT include the base frequency (e.g., 6 Hz)
ODDBALL_HARMONICS_HZ = [1.2, 2.4, 3.6, 4.8, 7.2]

# Significance settings
Z_THRESHOLD = 1.64
USE_BH_FDR = True
FDR_ALPHA = 0.05
FDR_SCOPE = "global"  # one of: "global", "roi", "both"

# =============================================================================
# Input expectations
# =============================================================================
SHEET_Z = "Z Score"
ELECTRODE_COL = "Electrode"

# Frequency columns (expects "1.2000_Hz" style)
_FREQ_COL_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*_Hz\s*$", re.IGNORECASE)

# Participant ID parsing
_PID_SCP_RE = re.compile(r"SCP0*(\d+)", re.IGNORECASE)
_PID_P_RE = re.compile(r"(?<![A-Z0-9])P0*(\d+)(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class ConditionInfo:
    name: str
    path: Path
    files: list[Path]


def parse_participant_id(filename: str) -> str | None:
    """
    Accepts e.g.:
      - SCP07, SCP007, SCP0007 -> P7
      - P7, P07, etc. -> P7
    """
    m = _PID_SCP_RE.search(filename)
    if m:
        return f"P{int(m.group(1))}"
    m = _PID_P_RE.search(filename)
    if m:
        return f"P{int(m.group(1))}"
    return None


def pid_sort_key(pid: str) -> tuple[int, str]:
    m = re.match(r"(?i)P(\d+)$", pid.strip())
    if m:
        return int(m.group(1)), pid
    return 10**9, pid


def normalize_electrode_name(name: str) -> str:
    s = str(name).strip().upper()
    s = s.replace(" ", "").replace(".", "").replace("-", "")
    return s


def discover_conditions(root: Path) -> list[ConditionInfo]:
    """
    Matches prior behavior:
      - If root has subfolders with .xlsx files, each subfolder is a condition.
      - Else, root itself is treated as one condition containing .xlsx files.
    """
    if not root.exists():
        return []

    subfolders = sorted([p for p in root.iterdir() if p.is_dir()])
    conditions: list[ConditionInfo] = []
    for sub in subfolders:
        files = sorted([p for p in sub.glob("*.xlsx") if p.is_file()])
        if files:
            conditions.append(ConditionInfo(name=sub.name, path=sub, files=files))

    if conditions:
        return conditions

    files = sorted([p for p in root.glob("*.xlsx") if p.is_file()])
    if files:
        return [ConditionInfo(name=root.name, path=root, files=files)]

    return []


def _parse_freq_columns(columns: Sequence[object]) -> dict[float, str]:
    """
    Returns mapping: rounded_frequency -> original_column_name
    """
    out: dict[float, str] = {}
    for c in columns:
        if not isinstance(c, str):
            continue
        m = _FREQ_COL_RE.match(c)
        if not m:
            continue
        try:
            f = float(m.group(1))
        except ValueError:
            continue
        out[round(f, 4)] = c
    return out


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    """
    Normal(0,1) CDF without SciPy, vectorized.
    """
    x = np.asarray(x, dtype=float)
    erf = np.vectorize(math.erf, otypes=[float])
    return 0.5 * (1.0 + erf(x / math.sqrt(2.0)))


def _bh_fdr_reject(pvals: np.ndarray, alpha: float) -> np.ndarray:
    """
    Benjamini–Hochberg reject decisions for p-values.
    """
    p = np.asarray(pvals, dtype=float)
    n = p.size
    if n == 0:
        return np.zeros((0,), dtype=bool)

    order = np.argsort(p)
    ranked = p[order]
    thresh = alpha * (np.arange(1, n + 1) / n)

    passed = ranked <= thresh
    if not np.any(passed):
        return np.zeros((n,), dtype=bool)

    kmax = int(np.max(np.where(passed)[0]))
    cutoff = float(ranked[kmax])
    return p <= cutoff


def load_and_score_z_sheet(
    excel_path: Path,
    *,
    oddball_harmonics_hz: list[float],
    z_threshold: float,
    use_bh_fdr: bool,
    fdr_alpha: float,
) -> pd.DataFrame:
    """
    Returns a per-electrode table with:
      Electrode, el_norm, z_comb, p_one, reject_fdr, sig_global

    Notes:
      - Drops duplicate electrodes by keeping the row with the largest z_comb.
      - FDR (if enabled) is applied across the remaining unique electrodes (global, full-sheet).
    """
    xl = pd.ExcelFile(excel_path)

    if SHEET_Z not in xl.sheet_names:
        raise ValueError(f"Missing required sheet '{SHEET_Z}'.")

    head = xl.parse(SHEET_Z, nrows=0)
    if ELECTRODE_COL not in head.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_Z}'.")

    freq_cols = _parse_freq_columns(head.columns)
    needed = [round(float(f), 4) for f in oddball_harmonics_hz]
    missing = [f for f in needed if f not in freq_cols]
    if missing:
        miss_str = ", ".join([f"{f:.4f}_Hz" for f in missing])
        raise ValueError(f"Missing harmonic column(s) in '{SHEET_Z}': {miss_str}")

    z_cols = [freq_cols[round(float(f), 4)] for f in oddball_harmonics_hz]
    df = xl.parse(SHEET_Z, usecols=[ELECTRODE_COL] + z_cols)

    # Ensure numeric
    for c in z_cols:
        df[c] = pd.to_numeric(df[c], errors="raise")

    # Build combined z
    k = len(z_cols)
    if k <= 0:
        raise ValueError("No oddball harmonic columns selected.")

    z_mat = df[z_cols].to_numpy(dtype=float)
    if np.isnan(z_mat).any():
        raise ValueError("Found NaNs in Z Score harmonic columns.")

    z_comb = z_mat.sum(axis=1) / math.sqrt(k)
    out = pd.DataFrame(
        {
            "Electrode": df[ELECTRODE_COL].astype(str),
            "z_comb": z_comb.astype(float),
        }
    )
    out["el_norm"] = out["Electrode"].map(normalize_electrode_name)

    # De-duplicate electrodes if needed (keep max z)
    out = out.sort_values("z_comb", ascending=False).drop_duplicates(subset=["el_norm"], keep="first")
    out = out.reset_index(drop=True)

    # One-tailed p-values (positive direction)
    out["p_one"] = (1.0 - _norm_cdf(out["z_comb"].to_numpy(dtype=float))).astype(float)

    # Threshold
    sig = out["z_comb"].to_numpy(dtype=float) >= float(z_threshold)

    # Optional BH-FDR across all electrodes
    if use_bh_fdr:
        reject = _bh_fdr_reject(out["p_one"].to_numpy(dtype=float), alpha=float(fdr_alpha))
        out["reject_fdr"] = reject.astype(bool)
        sig = sig & reject.astype(bool)
    else:
        out["reject_fdr"] = np.full((out.shape[0],), False, dtype=bool)

    out["sig_global"] = sig.astype(bool)
    return out


def summarize_rois(
    scored: pd.DataFrame,
    *,
    rois: dict[str, list[str]],
    z_threshold: float,
    use_bh_fdr: bool,
    fdr_alpha: float,
    fdr_scope: str,
) -> dict[str, dict[str, object]]:
    """
    For each ROI returns:
      {
        "n_roi_defined": int,
        "n_roi_found": int,
        "missing": str,
        "sig_electrodes_global": str,
        "n_sig_global": int,
        # optionally (scope=roi or both):
        "sig_electrodes_roiFDR": str,
        "n_sig_roiFDR": int
      }
    """
    if fdr_scope not in {"global", "roi", "both"}:
        raise ValueError("fdr_scope must be one of: global, roi, both")

    res: dict[str, dict[str, object]] = {}

    for roi_name, roi_electrodes in rois.items():
        roi_norms = [normalize_electrode_name(e) for e in roi_electrodes]
        roi_set = set(roi_norms)

        roi_df = scored[scored["el_norm"].isin(roi_set)].copy()
        found_set = set(roi_df["el_norm"].tolist())
        missing = [roi_electrodes[i] for i, nrm in enumerate(roi_norms) if nrm not in found_set]

        sig_global_norm = set(roi_df.loc[roi_df["sig_global"].astype(bool), "el_norm"].tolist())
        sig_global_list = [roi_electrodes[i] for i, nrm in enumerate(roi_norms) if nrm in sig_global_norm]

        roi_out: dict[str, object] = {
            "n_roi_defined": int(len(roi_electrodes)),
            "n_roi_found": int(len(found_set)),
            "missing": ", ".join(missing),
            "sig_electrodes_global": ", ".join(sig_global_list),
            "n_sig_global": int(len(sig_global_list)),
        }

        # Optional ROI-only FDR (applied only among electrodes within the ROI)
        if fdr_scope in {"roi", "both"}:
            if roi_df.shape[0] == 0:
                roi_out["sig_electrodes_roiFDR"] = ""
                roi_out["n_sig_roiFDR"] = 0
            else:
                # Threshold first, then (optional) BH-FDR restricted to ROI
                z_vals = roi_df["z_comb"].to_numpy(dtype=float)
                sig_roi = z_vals >= float(z_threshold)

                if use_bh_fdr:
                    pvals_roi = roi_df["p_one"].to_numpy(dtype=float)
                    reject_roi = _bh_fdr_reject(pvals_roi, alpha=float(fdr_alpha))
                    sig_roi = sig_roi & reject_roi

                sig_roi_norm = set(roi_df.loc[sig_roi, "el_norm"].tolist())
                sig_roi_list = [roi_electrodes[i] for i, nrm in enumerate(roi_norms) if nrm in sig_roi_norm]
                roi_out["sig_electrodes_roiFDR"] = ", ".join(sig_roi_list)
                roi_out["n_sig_roiFDR"] = int(len(sig_roi_list))

        res[roi_name] = roi_out

    return res


def _match_condition(conditions: list[ConditionInfo], pattern: str) -> ConditionInfo | None:
    """
    Returns the best matching condition by case-insensitive regex search on condition.name.
    If multiple match, chooses the shortest name (usually the most specific).
    """
    rx = re.compile(pattern, re.IGNORECASE)
    matches = [c for c in conditions if rx.search(c.name)]
    if not matches:
        return None
    matches.sort(key=lambda c: (len(c.name), c.name.lower()))
    return matches[0]


def main() -> int:
    # -----------------------------
    # Validate USER CONFIG
    # -----------------------------
    if not str(ROOT).strip():
        raise SystemExit(
            "ROOT is not set.\n"
            "Edit the USER CONFIG section at the top of roi_sig_electrodes_report.py and set:\n"
            "  ROOT = r\"C:\\\\path\\\\to\\\\results\""
        )

    root = Path(ROOT).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"ROOT folder does not exist: {root}")

    out_path = Path(OUT_XLSX).expanduser().resolve() if str(OUT_XLSX).strip() else (root / "roi_sig_electrodes_report.xlsx")

    harmonics = [float(x) for x in ODDBALL_HARMONICS_HZ]
    if not harmonics:
        raise SystemExit("ODDBALL_HARMONICS_HZ is empty in USER CONFIG.")

    use_bh_fdr = bool(USE_BH_FDR)
    z_threshold = float(Z_THRESHOLD)
    fdr_alpha = float(FDR_ALPHA)
    fdr_scope = str(FDR_SCOPE).strip().lower()

    if fdr_scope not in {"global", "roi", "both"}:
        raise SystemExit("FDR_SCOPE must be one of: 'global', 'roi', 'both' (see USER CONFIG).")

    conditions = discover_conditions(root)
    if not conditions:
        raise SystemExit(f"No conditions found under: {root}")

    sem_cond = _match_condition(conditions, SEMANTIC_PATTERN)
    col_cond = _match_condition(conditions, COLOR1_PATTERN)

    if sem_cond is None:
        raise SystemExit(
            f"Could not find a condition folder matching SEMANTIC_PATTERN={SEMANTIC_PATTERN!r} under {root}.\n"
            f"Found condition folders: {[c.name for c in conditions]}"
        )
    if col_cond is None:
        raise SystemExit(
            f"Could not find a condition folder matching COLOR1_PATTERN={COLOR1_PATTERN!r} under {root}.\n"
            f"Found condition folders: {[c.name for c in conditions]}"
        )

    targets: list[tuple[str, ConditionInfo]] = [
        ("Semantic", sem_cond),
        ("Color_Response1", col_cond),
    ]

    # Wide table accumulator: pid -> dict
    wide: dict[str, dict[str, object]] = {}
    long_rows: list[dict[str, object]] = []
    err_rows: list[dict[str, object]] = []

    for cond_key, cond in targets:
        for excel_path in cond.files:
            pid = parse_participant_id(excel_path.stem)
            if not pid:
                err_rows.append(
                    {
                        "Condition": cond_key,
                        "File": str(excel_path),
                        "Participant": "",
                        "Error": "Could not parse participant ID from filename.",
                    }
                )
                continue

            try:
                scored = load_and_score_z_sheet(
                    excel_path,
                    oddball_harmonics_hz=harmonics,
                    z_threshold=z_threshold,
                    use_bh_fdr=use_bh_fdr,
                    fdr_alpha=fdr_alpha,
                )
                roi_summary = summarize_rois(
                    scored,
                    rois=ROI_DEFS,
                    z_threshold=z_threshold,
                    use_bh_fdr=use_bh_fdr,
                    fdr_alpha=fdr_alpha,
                    fdr_scope=fdr_scope,
                )
            except Exception as e:
                err_rows.append({"Condition": cond_key, "File": str(excel_path), "Participant": pid, "Error": str(e)})
                continue

            # Wide row base
            row = wide.setdefault(pid, {"Participant": pid})

            # Fill wide columns for each ROI
            for roi_name, roi_out in roi_summary.items():
                # always global count/list
                row[f"{cond_key}_{roi_name}_nSig_global"] = roi_out["n_sig_global"]
                row[f"{cond_key}_{roi_name}_sigElectrodes_global"] = roi_out["sig_electrodes_global"]
                row[f"{cond_key}_{roi_name}_missing"] = roi_out["missing"]

                if fdr_scope in {"roi", "both"}:
                    row[f"{cond_key}_{roi_name}_nSig_roiFDR"] = roi_out.get("n_sig_roiFDR", 0)
                    row[f"{cond_key}_{roi_name}_sigElectrodes_roiFDR"] = roi_out.get("sig_electrodes_roiFDR", "")

                # Long rows
                long_rows.append(
                    {
                        "Participant": pid,
                        "Condition": cond_key,
                        "ROI": roi_name,
                        "n_roi_defined": roi_out["n_roi_defined"],
                        "n_roi_found": roi_out["n_roi_found"],
                        "missing": roi_out["missing"],
                        "n_sig_global": roi_out["n_sig_global"],
                        "sig_electrodes_global": roi_out["sig_electrodes_global"],
                        **(
                            {
                                "n_sig_roiFDR": roi_out.get("n_sig_roiFDR", 0),
                                "sig_electrodes_roiFDR": roi_out.get("sig_electrodes_roiFDR", ""),
                            }
                            if fdr_scope in {"roi", "both"}
                            else {}
                        ),
                        "source_file": str(excel_path),
                    }
                )

    if not wide:
        raise SystemExit("No participant files processed successfully. See Errors sheet in output (if created).")

    # Build DataFrames
    wide_df = pd.DataFrame(list(wide.values()))
    wide_df = wide_df.sort_values(by="Participant", key=lambda s: s.map(lambda x: pid_sort_key(str(x))[0]))

    # Add averages row for numeric columns
    numeric_cols = [c for c in wide_df.columns if c.endswith("_nSig_global") or c.endswith("_nSig_roiFDR")]
    avg_row: dict[str, object] = {"Participant": "Average"}
    for c in numeric_cols:
        avg_row[c] = float(pd.to_numeric(wide_df[c], errors="coerce").mean(skipna=True))
    wide_df = pd.concat([wide_df, pd.DataFrame([avg_row])], ignore_index=True)

    long_df = pd.DataFrame(long_rows)
    if not long_df.empty:
        long_df = long_df.sort_values(by=["Condition", "Participant", "ROI"], key=lambda s: s)

    err_df = pd.DataFrame(err_rows)

    # Metadata sheet
    metadata_rows = [
        {"Field": "root", "Value": str(root)},
        {"Field": "output", "Value": str(out_path)},
        {"Field": "semantic_folder_matched", "Value": f"{sem_cond.name} ({sem_cond.path})"},
        {"Field": "color1_folder_matched", "Value": f"{col_cond.name} ({col_cond.path})"},
        {"Field": "semantic_pattern", "Value": SEMANTIC_PATTERN},
        {"Field": "color1_pattern", "Value": COLOR1_PATTERN},
        {"Field": "oddball_harmonics_hz", "Value": ", ".join([f"{h:g}" for h in harmonics])},
        {"Field": "z_threshold", "Value": z_threshold},
        {"Field": "use_bh_fdr", "Value": bool(use_bh_fdr)},
        {"Field": "fdr_alpha", "Value": fdr_alpha},
        {"Field": "fdr_scope", "Value": fdr_scope},
    ]
    for roi_name, els in ROI_DEFS.items():
        metadata_rows.append({"Field": f"ROI_{roi_name}", "Value": ", ".join(els)})
    meta_df = pd.DataFrame(metadata_rows)

    # Write Excel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        wide_df.to_excel(writer, index=False, sheet_name="WideCounts")
        long_df.to_excel(writer, index=False, sheet_name="LongCounts")
        err_df.to_excel(writer, index=False, sheet_name="Errors")
        meta_df.to_excel(writer, index=False, sheet_name="Metadata")

        # Freeze panes for readability
        for sheet_name in ["WideCounts", "LongCounts", "Errors", "Metadata"]:
            ws = writer.book[sheet_name]
            ws.freeze_panes = "B2"

    print(f"Wrote report: {out_path}")
    if not err_df.empty:
        print(f"Warnings: {len(err_df)} file(s) could not be processed (see 'Errors' sheet).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())