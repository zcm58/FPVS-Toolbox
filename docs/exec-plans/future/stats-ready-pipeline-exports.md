# Stats-Ready Pipeline Exports

## Status

Future plan. This work has not started.

## Summary

Add optional analysis-ready Excel and CSV outputs from the data processing pipeline for JASP, RStudio, and similar statistical software. These files must be additive: existing post-processing workbooks, sheet names, formulas, processing order, BDF loading, preprocessing, BCA math, and current Stats behavior must remain unchanged.

## Goals

- Produce long-format exports that are easy to analyze in R, JASP, Python, or spreadsheet tools.
- Produce Summed BCA long-format exports with one row per subject, condition, and ROI.
- Produce Summed BCA wide-format exports with one row per subject and stable condition/ROI columns for repeated-measures workflows.
- Preserve the Rossion-method harmonic selection and BCA summing behavior by reusing the existing Stats/DV logic instead of reimplementing it in a separate export path.
- Include a data dictionary sheet or file that documents column names, units, source sheets, Rossion settings, selected harmonics, and empty/fallback behavior.

## Planned Outputs

The future implementation should write a dedicated stats-ready export set without modifying existing per-subject or post-processing workbooks.

- Long-format data:
  - One row per subject, optional group, condition, ROI, metric, and harmonic or derived DV.
  - Stable fields for subject, group when available, condition, ROI, metric name, harmonic frequency, value, units, and source workbook.
- Summed BCA long-format data:
  - One row per subject x condition x ROI.
  - Fields for summed BCA value, selected harmonics, harmonic count, selection policy, units, and source workbook.
- Summed BCA wide-format data:
  - One row per subject, with stable condition/ROI columns suitable for JASP repeated-measures setup.
- Data dictionary:
  - Documents field names, value meanings, units, source sheets, selected-harmonic metadata, and Rossion-method settings.

Excel should be the primary user-facing format. CSV exports should also be produced when practical because they are simple to import into RStudio, JASP, Python, and other statistical tools.

## Rossion Method Requirement

Summed BCA must match the current Stats implementation exactly. The export path must reuse the existing Rossion harmonic-selection and DV helpers so that:

- statistically significant harmonics are selected using the same group-level Z-score rules,
- ROI-specific harmonic selections are preserved,
- excluded or empty harmonic cases follow the same policy as the Stats workflow,
- BCA summing across selected harmonics produces the same values as the current Stats reports.

Do not introduce a second independent implementation of harmonic selection or Summed BCA calculation.

## Likely Ownership

The data-shaping and export implementation should live near the Stats I/O or reporting layer because that area already owns DV policy, long-format transformations, and statistical reporting semantics. The Main App processing pipeline should call it only as an optional additive export step after existing processing outputs are complete.

## Test Plan For Future Implementation

- Golden-data tests prove existing post-processing workbooks and current pipeline exports are unchanged.
- Schema tests lock long-format and wide-format column names.
- Value tests prove Summed BCA outputs match the existing Stats DV helpers.
- Harmonic metadata tests prove selected harmonics match the Rossion-method selection rules.
- Empty or missing harmonic tests prove fallback behavior is explicit and documented.
- Run the relevant Stats structure/reporting checks and `python .agents/scripts/audit/agent_audit.py`.

## Assumptions

- This feature is not part of the active Main App refactor yet.
- Existing post-processing workbook contracts remain authoritative until this plan is explicitly activated.
- New exports are optional/additive and must not become a hidden dependency for current processing or Stats workflows.
