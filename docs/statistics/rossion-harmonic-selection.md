# Rossion harmonic selection (Summed BCA)

This page explains the **Rossion method** used to define which oddball
harmonics contribute to the Summed BCA DV. The method is **ROI-specific**
and is based on **group mean Z-scores** computed from the Z-score sheet in
your spectral output files.

---

## What the method produces

For each ROI, the Rossion method produces a list of oddball harmonics
(Hz). That list is then used to compute Summed BCA for **every subject
and every condition** in that ROI.

- **Per ROI:** each ROI gets its own selected harmonic set.
- **Per subject × condition × ROI:** Summed BCA is the sum of BCA values
  over those selected harmonics, averaged across channels in the ROI.

---

## Inputs and data sources

The Rossion method uses the same per-subject, per-condition Excel output
files that store ROI-aggregated spectral data.

- **Z-score source:** the **“Z Score”** sheet is used to compute group mean
  Z-values for each ROI and harmonic.
- **BCA source:** the **“BCA (uV)”** sheet provides the BCA amplitudes to
  be summed once harmonics are selected.
- **Column format:** frequency bins are read from columns that end in
  `_Hz` (e.g., `1.2_Hz`).

---

## Step 1: Build the candidate harmonic domain

The tool builds the candidate harmonic list using the following steps:

1. **Read frequency columns** from the Z-score sheet (columns ending in
   `_Hz`).
2. **Exclude base-rate harmonics:** any column that is an exact multiple
   of the base frequency is removed (tolerance 1e-6).
3. **Select oddball harmonics:** oddball harmonics are defined as
   multiples of (base frequency / every_n), with the default
   `every_n = 5` and tolerance 1e-3.
4. **Optional exclusion of harmonic 1:** if “Exclude harmonic 1” is
   enabled, harmonic number 1 is removed from the list.

Result: an ordered list of oddball harmonic frequencies (Hz) that are
candidates for the Rossion selection rule.

---

## Step 2: Compute group mean Z per ROI and harmonic

For each subject, condition, ROI, and harmonic in the domain:

- The tool **averages Z values across the ROI’s channels** (using the
  channels that are present in the Z-score sheet).
- These ROI-mean Z values are **pooled across all selected conditions and
  all subjects**, then averaged to yield a **group mean Z** for each
  ROI × harmonic.

This produces a table with columns like:

- `roi`
- `harmonic_hz`
- `mean_z` (group mean Z across selected conditions and subjects)

---

## Step 3: Rossion selection rule (per ROI)

For each ROI, harmonics are scanned in ascending order:

- **Threshold:** a harmonic is **significant** if group mean Z exceeds the
  current **Z threshold** (default 1.64). The threshold is set in the
  Statistical Analysis settings.
- **Arm after first significant:** non-significant harmonics are ignored
  until the first significant harmonic is found.
- **Stop rule:** after the first significant harmonic is found, the
  algorithm **stops after 2 consecutive non-significant harmonics**.

The selected harmonics are the significant harmonics **before the stop
rule triggers**.

---

## Step 4: Compute Summed BCA (the DV)

For each subject × condition × ROI:

1. **Read BCA (uV)** values at the selected harmonics for that ROI.
2. **Sum BCA across selected harmonics** for each channel in the ROI.
3. **Average across ROI channels** to yield the Summed BCA value.

This produces the DV table used by RM-ANOVA, mixed models, and post-hoc
comparisons.

---

## Fallback behavior when no harmonics are selected

If the Rossion method selects **no harmonics** for a given ROI, the
behavior depends on the **Empty list policy** setting:

- **Fallback to Fixed-K (default):** use the Fixed-K selection (default
  K = 5) instead of the empty list.
- **Set DV = 0:** keep the harmonic list empty and set Summed BCA to 0
  for that ROI.
- **Error:** stop and report an error so you can adjust settings.

The Fixed-K harmonics are also built from oddball harmonics (every_n = 5)
and can optionally exclude harmonic 1 and base-rate harmonics.

---

## Outputs you can review

When you export results after running the Rossion method, the tool writes
**Summed BCA DV Definition.xlsx** with:

- **DV Definition** (summary of the policy and thresholds),
- **ROI Harmonics** (selected harmonics per ROI, fallback use, stop
  reason),
- **Mean Z Table** (group mean Z values used for selection).

---

## Not found in code (documentation transparency)

The following details were **not found in code** while preparing this
page:

- A user-facing description of how Z thresholds are labeled in the UI
  beyond “minimum group-mean Z value for a harmonic to count as
  significant.” (Searched in `src/Tools/Stats/PySide6/stats_main_window.py`
  and `src/Tools/Stats/PySide6/dv_policies.py`.)
