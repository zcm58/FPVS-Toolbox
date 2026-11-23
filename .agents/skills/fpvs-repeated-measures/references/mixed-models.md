# Linear mixed models for FPVS response amplitude

Use [fpvs-analysis](../../fpvs-analysis/SKILL.md) for the outcome and eligibility
audit. These are study-specific models for continuous responses. The Toolbox's
[screening contract](../../../../docs/agent/architecture/statistics-tools.md)
owns exact native replication.

## Specify the model and estimand

Use participant identity for the repeated grouping factor. Start with the
fixed effects and interactions required by the estimand, retaining their
lower-order terms. Inspect independent participant counts, supported cells,
factor coding, and design rank before fitting.

| Question | Illustrative R formula | Contrast |
| --- | --- | --- |
| Does the condition effect differ across ROIs? | `bca ~ condition * roi + (1 \| pid)` | `(A − B) at Right − (A − B) at Left` |
| Do groups change differently across visits at the selected Condition × ROI? | `bca ~ group * visit + (1 \| pid)` | `(V2 − V1) in Group A − (V2 − V1) in Group B` |
| Does the ROI difference change across visits? | `bca ~ visit * roi + (1 \| pid)` | `(Right − Left) at V2 − (Right − Left) at V1` |
| Does the condition effect differ between groups? | `bca ~ group * condition + (1 \| pid)` | `(A − B) in Group A − (A − B) in Group B` |

Add factors such as condition, ROI, and group to the same model where the
planned estimand and data support the interaction. Avoid a default four-way
factorial fit. If a contrast averages across conditions or ROIs, write its
weights down. Equal cell weights and weights proportional to the observed
composition target different questions. Keep factor levels and direction
explicit.

- The formulas show random-intercept starting points. Assess whether
  participant differences in within-participant effects require random
  slopes or another repeated covariance. Plan a candidate structure that
  the number of observations per participant can identify. If outcomes
  share a visit and several rows contribute within that visit, a
  participant-visit intercept may model additional shared variation.
  For trial-level outcomes with reused stimuli, consider crossed participant
  and item effects when justified by the design.
- A two-visit table with just one value per person per visit often cannot
  support an unrestricted correlated intercept and visit slope plus residual
  variance. For longer or unequally spaced follow-up, inspect whether residual
  serial dependence or group-specific variance calls for a suitable covariance
  model. If a planned model is unstable, document the simplification and
  its impact on uncertainty. Treat a materially unsupported conclusion as
  limited even if a simpler model returns a p-value.
- Match the model to the outcome. A continuous BCA LMM can include zero or
  negative values. For genuinely binary observations, use an appropriate
  binary model with design-aware dependence. Thresholding amplitude into
  responder status changes the estimand.

## Fit and verify

1. Define missingness and exclusion rules, then freeze the modeled rows.
   Likelihood fits can use observed rows under an ignorable missingness
   assumption conditional on modeled variables and an adequate model.
   Report differential missingness, possible outcome-dependent QC or dropout,
   and any sensitivity to complete pairs or different assumptions. An entirely
   missing design cell cannot supply an unsupported interaction.
2. Use the existing project environment where feasible. In Python,
   `statsmodels.formula.api.mixedlm` takes fixed effects in `formula`,
   participant IDs in `groups`, and participant random effects in
   `re_formula`. In R, use `lme4::lmer` with an explicit random-effects
   formula and `emmeans` for fitted contrasts. Use a backend that can fit
   the planned covariance and inference. Record the actual versions and
   settings.
3. Report the estimator and reference distribution. REML is suitable for
   final variance estimation and standard contrasts in a specified linear
   mixed model. When using a likelihood-ratio test for nested fixed effects,
   refit both models by ML on identical rows with the same random structure.
   Ordinary chi-square likelihood-ratio tests for random variance
   components at zero have boundary problems. For small participant
   samples, consider Kenward–Roger or Satterthwaite inference where the
   backend supports it, or a justified design-aware alternative. Standard
   Statsmodels MixedLM Wald z and asymptotic likelihood tests do not
   implement those degrees-of-freedom approximations.
4. Inspect convergence warnings, covariance eigenvalues or boundary
   estimates, residuals across fitted values and design cells, and influence
   at participant level. Run plausible sensitivity checks when conclusions
   depend on a small number of participants or a variance assumption.
   A bootstrap or permutation must resample or exchange the independent
   participant units, preserving within-participant structure and design
   blocks. Report non-estimability, unstable fits, and changes to the
   planned model.

## Produce fitted contrasts

Use the model's population-level means with prespecified weights and
covariate settings. For example, put the fixed design rows in order
`A V1, A V2, B V1, B V2`. The group difference in visit change uses
weights `[-1, +1, +1, -1]`. Apply those weights to the design rows to
obtain the coefficient contrast `L`. Estimate `Lβ` and compute its
standard error from `sqrt(L V Lᵀ)`, where `V` is the fixed-effect
covariance in the same coefficient order. In Python, construct those rows
from the model's Patsy design information and align the covariance to
`fe_params`, excluding random-effect variance parameters. In R,
`emmeans` can construct the grid and apply the contrast with the chosen
weights and degrees-of-freedom method. Verify the sign on a small numeric
example and confirm the fitted rows match the intended cohort.

Report the target population, cell weights or conditioning levels, estimate,
interval method, test, multiplicity family, and participant coverage. Name
fitted comparisons that were selected after looking at the data as exploratory.

[Bates et al. on lme4](https://www.jstatsoft.org/article/view/v067i01) ·
[Statsmodels MixedLM](https://www.statsmodels.org/stable/generated/statsmodels.regression.mixed_linear_model.MixedLM.html) ·
[Matuschek et al. on random-effects structure](https://doi.org/10.1016/j.jml.2017.01.001)
