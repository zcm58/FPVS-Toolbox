# Rossion harmonic selection (Summed BCA)

## Plain-language overview

In FPVS, the oddball response is not limited to a single frequency.
If the brain is truly responding to the oddball stream, you often see a
response at the oddball frequency (e.g., 1.2 Hz) **and** at several
higher harmonics (2.4, 3.6, 4.8, ...).

This module decides **which oddball harmonics count** toward the outcome
used for statistics: **Summed BCA**.

The key idea (the “Rossion method”) is simple:

- Look at the **group-level Z-scores** at each oddball harmonic.
- For each ROI, include the harmonics that show a reliable group
  response, and stop when the response clearly dies off.

Why this is useful in FPVS-EEG research:

- It produces an outcome measure that reflects the **total oddball
  response** across the harmonics that actually carry signal.
- It is **ROI-specific**, which matters because different scalp regions
  can show different harmonic profiles.
- It creates a single, interpretable number per
  **participant × condition × ROI** that can be used in RM-ANOVA, mixed
  models, and post-hoc tests.

---

## Manuscript-ready description

Summed BCA was defined using an ROI-specific harmonic selection procedure
based on the approach commonly attributed to work done by the Rossion Group.
Harmonic selection was performed at the group level using ROI-averaged
Z-scores derived from the spectral “Z Score” sheets in the per-subject,
per-condition output files. Candidate frequencies were restricted to
oddball harmonics present in the spectral exports, identified as
multiples of the oddball rate (base frequency divided by `every_n`,
default `every_n = 5`) within a tolerance, and excluding base-rate
harmonics (exact multiples of the base frequency). An optional setting
allowed exclusion of the first oddball harmonic (harmonic 1).

For each candidate harmonic, Z-scores were first averaged across the
channels belonging to each ROI, yielding ROI-mean Z values for each
subject and condition. These ROI-mean Z values were then pooled across
subjects and across the set of selected conditions and averaged to yield
a group mean Z for each ROI × harmonic. Within each ROI, harmonics were
scanned in ascending frequency order and evaluated against a user-defined
Z threshold (default 1.64). Non-significant harmonics were ignored until
the first significant harmonic was observed (“arming” step). After
arming, the selection terminated when two consecutive harmonics failed to
exceed threshold. The selected harmonic set for each ROI consisted of all
significant harmonics encountered prior to the stop criterion.

Summed BCA values were then computed for each subject × condition × ROI
by extracting baseline-corrected amplitude (BCA; µV) at the selected
harmonics from the “BCA (uV)” sheets, summing BCA across the selected
harmonics within each channel, and then averaging across channels within
the ROI. This yielded a single ROI-level Summed BCA outcome per condition
and participant, which served as the dependent variable for inferential
analyses.

If no harmonics were selected for a given ROI, an empty-list policy was
applied. Depending on user settings, the toolbox either (a) fell back to
a Fixed-K harmonic set (default K = 5) drawn from the same oddball
harmonic domain, (b) set Summed BCA to zero for that ROI, or (c) halted
with an error to prompt adjustment of selection settings. The toolbox
exports a dedicated report (“Summed BCA DV Definition.xlsx”) documenting
the harmonic domain, group mean Z values, ROI-specific selected harmonic
lists, and any fallback behavior.

---

## Not found in code (documentation transparency)

The following detail was not found in the current workflow:

- A more specific UI label/description for the Z-threshold setting beyond
  the functional meaning “minimum group-mean Z value for a harmonic to
  count as significant.”
