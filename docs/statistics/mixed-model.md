# Linear mixed-effects model (Summed BCA)

The FPVS Toolbox provides a linear mixed-effects model (LMM) for Summed
BCA, allowing you to model repeated measures within subjects while
estimating condition/ROI effects.

---

## Implementation

- **Library:** statsmodels `MixedLM`.
- **Random effects:** random intercept for each subject (default).
- **Fixed effects (single group):** condition, ROI, and their interaction.
- **Fixed effects (multi-group):** group, condition, ROI, and all
  interactions.

---

## Coding of categorical variables

- **Condition and ROI** are **sum-coded** by default when present.
- **Group coding:** Not found in code. The model does not explicitly set
  group contrasts, so statsmodels’ default coding likely applies.

---

## How to interpret coefficients

- **Intercept:** average Summed BCA across all conditions/ROIs (and
  groups, if using sum coding). A positive intercept suggests an overall
  response above zero.
- **Condition terms:** how each condition deviates from the overall mean
  (under sum coding).
- **ROI terms:** how each ROI deviates from the overall mean.
- **Interaction terms:** whether condition effects differ by ROI (or by
  group in multi-group mode).

---

## Relationship to RM-ANOVA

- **RM-ANOVA** is the traditional repeated-measures approach (balanced
  designs, sphericity corrections).
- **Mixed model** provides a flexible alternative that can handle some
  missing data (after exclusions) and gives coefficient-level estimates.

---

## Not found in code (documentation transparency)

The following details were **not found in code** while preparing this
page:

- A user-facing toggle to enable random slopes or likelihood-ratio tests
  (the helper supports these, but the Stats tool calls it with random
  intercept only and no LRTs). (Searched in
  `src/Tools/Stats/Legacy/mixed_effects_model.py` and
  `src/Tools/Stats/PySide6/stats_workers.py`.)
