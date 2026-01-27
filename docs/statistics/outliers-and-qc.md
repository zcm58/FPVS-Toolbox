# Outliers, QC flags, and manual exclusions

The Statistical Analysis module separates **flags** (informational) from
**exclusions** (participants actually removed from analysis). This lets
you review QC warnings before deciding whether to exclude anyone.

---

## What is flagged vs. excluded

### QC flags (informational)

- QC screening examines all **conditions and ROIs in the project**, even
  if you later select a subset for analysis.
- QC uses robust thresholds on **sum(|BCA|)** and **max(|BCA|)** metrics
  (across oddball harmonics) to flag unusually large responses.
- QC flags **do not automatically remove participants**. They appear in
  the *Flagged Participants* report so you can review them.

### DV hard-limit flags (informational)

- A **hard DV limit** (absolute value) flags participants whose Summed
  BCA values exceed the limit.
- These are also **flags only** unless the value is non-finite.

### Required exclusions (automatic)

- Participants with **non-finite Summed BCA values** are **required
  exclusions** and are removed from analyses.

### Manual exclusions (user-controlled)

- You can manually select participants to exclude. This is the only
  user-controlled exclusion step.
- Manual exclusions are applied before analyses run.

---

## Where to find the reports

Exports live in **“3 - Statistical Analysis Results”** and include:

- **Flagged Participants.xlsx**
  - *Flag Summary* and *Flag Details* tabs for QC and DV flags.
- **Excluded Participants.xlsx**
  - Records manual exclusions and required non-finite exclusions.

---

## Interpretation tips

- Use **Flagged Participants.xlsx** to document quality concerns and
  justify any manual exclusions in your reporting.
- Because QC flags do **not** remove participants automatically, the
  final sample size depends on **manual exclusions** plus required
  non-finite exclusions.

---

## Not found in code (documentation transparency)

The following details were **not found in code** while preparing this
page:

- A setting to automatically exclude QC-flagged participants. (Searched
  in `src/Tools/Stats/PySide6/stats_workers.py` and
  `src/Tools/Stats/PySide6/stats_outlier_exclusion.py`.)
