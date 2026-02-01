# Outliers, QC flags, and manual exclusions

## Plain-language overview

FPVS datasets can contain participants with unusually large values,
missing values, or other issues that might distort group statistics.
This module helps you handle that cleanly by separating two concepts:

- **Flags**: warnings that say “this looks unusual, and you should take a look.”
- **Exclusions**: a decision to actually remove a participant from the
  analysis.

The point is to avoid “silent” data removal. You get a transparent paper
trail showing what was flagged, what was excluded, and why.

Why this is useful in FPVS-EEG research:

- It supports **transparent QC reporting** (what you noticed vs. what you
  removed).
- It reduces the chance of accidentally biasing results by
  auto-dropping participants without review.
- It produces **exported reports** you can archive with the project and
  use directly when writing your Methods/QC section.

---

## Manuscript-ready description

### Conceptual approach

Quality control in the FPVS Toolbox distinguishes between
**informational QC flags** and **analysis exclusions**. QC flags identify
participants with unusually large responses or implausible outcome
values, but flagged participants are **not automatically removed** from
analysis. Instead, flags are exported as a structured report to support
review, documentation, and transparent reporting. Exclusions are applied
only in two cases: (1) **required exclusions** triggered by non-finite
outcome values, and (2) **manual exclusions** selected by the user after
reviewing QC outputs.

### QC flags and DV limit flags

QC screening is computed across **all conditions and ROIs in the active
project**, independent of any subset later selected for inferential
analysis. Robust outlier screening is performed using harmonic-level
BCA-derived summary metrics, including **sum(|BCA|)** and **max(|BCA|)**
computed across oddball harmonics, in order to identify unusually large
responses that may reflect artifact, preprocessing failures, or other
non-physiological outliers. In addition, an optional hard absolute limit
can be applied to the dependent variable (Summed BCA); observations
exceeding this limit are recorded as **DV hard-limit flags**. QC and DV
flags are informational and are intended to prompt review rather than
enforce removal.

### Required and manual exclusions

Participants with **non-finite Summed BCA values** (e.g., NaN or ±Inf)
are treated as **required exclusions** and are automatically removed
from all inferential analyses because their outcomes cannot be modeled.
All other exclusions are **user-controlled**: after reviewing QC reports,
the user may manually designate participants to exclude, and these manual
exclusions are applied prior to running statistical tests. As a result,
the final analytic sample reflects only (a) required non-finite
exclusions and (b) user-selected manual exclusions, while QC flags remain
as a transparent record of potential data-quality concerns.

### Outputs for documentation

QC and exclusion outputs are exported to the project results directory
under **“3 - Statistical Analysis Results”**. The toolbox generates a
Flagged Participants report (summarizing QC and DV flags) and an Excluded
Participants report (recording required non-finite exclusions and
user-selected manual exclusions), enabling clear documentation of data
review decisions in manuscripts and reproducible project archiving.
