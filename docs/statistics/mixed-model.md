# Linear mixed-effects model (Summed BCA)

## Plain-language overview

A linear mixed-effects model (often shortened to “mixed model” or “LMM”)
is a standard way to analyze **repeated-measures** data.

In FPVS-EEG, a repeated-measures structure happens any time each
participant contributes **multiple values**—for example, one Summed BCA
value for each **condition** and each **ROI**. Those values are related
because they come from the same person, so treating them as independent
would be statistically inappropriate.

A mixed model handles this by combining two ideas:

- **Fixed effects** describe the **average pattern for the group**.
  In this toolbox, that means estimating how Summed BCA changes across
  conditions, across ROIs, and whether condition effects differ by ROI.
- **Random effects** describe **participant-to-participant differences**.
  The default toolbox model uses a **random intercept**, which means each
  participant is allowed to have their own overall baseline response
  level (some participants are consistently higher or lower across all
  conditions/ROIs, independent of the experimental manipulation).

Why this is useful in FPVS-EEG research:

- It matches the reality that FPVS datasets are usually
  **subject × condition × ROI**.
- It gives interpretable answers to the same questions you would ask
  with repeated-measures ANOVA (condition effects, ROI effects, and the
  interaction), while explicitly accounting for subject-to-subject
  variability in overall response magnitude.
- It can be more tolerant of **minor imbalance** (e.g., a small number of
  missing condition×ROI cells after exclusions) than approaches that
  require perfectly complete data tables.

---

## More Details


### Model specification implemented in the toolbox

Summed BCA values are analyzed using linear mixed-effects modeling to
account for repeated measurements within participants. The dependent
variable is ROI-level Summed BCA (ROI-averaged baseline-corrected
amplitude summed across the set of statistically significant oddball
harmonics defined for the analysis). Data are indexed by participant, condition, and ROI.

Models are fit in Python using statsmodels (`MixedLM`) with a
participant-level random intercept. For single-group analyses, fixed
effects included Condition, ROI, and the Condition × ROI interaction. For
multi-group analyses, Group was included as an additional fixed effect
along with all interactions among Group, Condition, and ROI. This
specification estimates group-average effects of condition and ROI while
allowing each participant to vary in overall baseline response level via
the random intercept.

### Categorical coding and interpretation

Condition and ROI are sum-coded (sum-to-zero contrasts) when present, so
fixed-effect coefficients are interpreted as deviations from the **grand
mean** across factor levels rather than comparisons to an arbitrary
reference level. Under this coding:

- The **intercept** represents the grand mean Summed BCA across included
  factor levels.
- **Condition** and **ROI** terms reflect how each level deviates from
  that grand mean.
- The **Condition × ROI** interaction tests whether condition-related
  changes differ across ROIs (i.e., whether the condition effect depends
  on ROI).

Group contrasts are not explicitly configured in the current workflow,
so group terms follow the default contrast handling used by statsmodels.

### Practical relationship to RM-ANOVA

RM-ANOVA provides a familiar summary test for within-subject designs, but
it is most straightforward when every participant contributes a complete,
balanced set of condition×ROI observations. The mixed model addresses the
same repeated-measures structure while explicitly modeling
participant-to-participant differences (via the random intercept) and
can use all available observations when a small number of cells are
missing rather than dropping entire participants due to listwise
deletion.
