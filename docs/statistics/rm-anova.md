# RM-ANOVA details (Summed BCA)

The FPVS Toolbox uses repeated-measures ANOVA (RM-ANOVA) to test
within-subject effects of **Condition**, **ROI**, and their interaction on
Summed BCA.

---

## Implementation

- **Primary library:** Pingouin `rm_anova` (when installed).
- **Fallback library:** statsmodels `AnovaRM` (when Pingouin is not
  available).

The output is normalized into a consistent table that includes:

- **Effect** (Condition, ROI, Condition × ROI)
- **F Value** (F statistic)
- **Num DF / Den DF** (degrees of freedom)
- **Pr > F** (p-value)
- **partial eta squared** (effect size)
- **Pr > F (GG)** and **Pr > F (HF)** when Pingouin provides sphericity
  corrections

---

## How to read the table

- **F statistic:** ratio of explained variance to residual variance. A
  larger F indicates stronger evidence for an effect.
- **Num DF / Den DF:** degrees of freedom for the effect and error.
- **p-values:** use the GG/HF corrected columns when available (they
  adjust for sphericity violations).
- **partial eta squared:** effect size, computed from F and dfs when not
  provided by the library.

---

## Notes for end users

- RM-ANOVA requires a **balanced design** (each subject must have all
  required condition × ROI combinations). If the data are unbalanced, the
  analysis reports an error and lists missing combinations.
- RM-ANOVA focuses on **differences among conditions and ROIs**; it does
  not directly test whether Summed BCA is different from zero.

---

## Not found in code (documentation transparency)

The following details were **not found in code** while preparing this
page:

- A user-facing setting that toggles sphericity correction methods
  (Pingouin decides this internally). (Searched in
  `src/Tools/Stats/Legacy/repeated_m_anova.py` and
  `src/Tools/Stats/PySide6/stats_main_window.py`.)
