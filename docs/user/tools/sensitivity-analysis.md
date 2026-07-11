# Sensitivity Analysis

Sensitivity Analysis estimates the smallest standardized effect a study would
be powered to detect under assumptions you enter manually. It is a descriptive,
G*Power-style calculator and is separate from the Statistical Analysis tool.

The tool does not read participant data or project settings. It does not save,
export, or modify any files.

## Supported Designs

### Paired or One-Sample t-Test

Enter the analyzable sample size, desired power, alpha, and whether the test is
two-sided or one-sided. Analyzable sample size means participants expected to
provide a complete pair after exclusions. A one-sided test should be used only
for a directional hypothesis chosen before examining the data. The result is
the minimum detectable Cohen's *dz*. For a paired test, *dz* standardizes the
mean within-participant difference by the standard deviation of those
difference scores.

### One-Way Repeated-Measures ANOVA

Enter the sample size, number of conditions, number of ROIs, desired power,
alpha, average correlation among repeated measurements, and nonsphericity
correction epsilon. Select the effect being evaluated and the tool derives the
number of repeated measurements automatically:

- condition effect: number of conditions;
- ROI effect: number of ROIs; or
- omnibus condition × ROI cells: conditions × ROIs.

For condition effects, ROIs are assumed to have been averaged or otherwise kept
outside the one-way effect. For ROI effects, conditions are treated the same
way. The result is the minimum detectable Cohen's *f* and its equivalent
eta-squared value.

The repeated-measures calculation assumes a balanced within-participant design.
Epsilon must be valid for the selected number of measurements; 1.00 represents
sphericity. The interface adjusts the permitted correlation and epsilon ranges
as the derived measurement count changes and blocks effects with fewer than two
levels.

The omnibus condition × ROI option treats all cells as levels of one
within-participant factor. It does not specifically estimate power for a
condition × ROI interaction. Use the information button in the Study
Assumptions card for six tabs: Quick Guide, FPVS Design, Assumptions, Mixed
Models, Interpretation (including reporting), and Methods (including
references). This analytical one-way model does not include
between-participant groups or factorial interaction power.

### Linear Mixed Model (Simulation)

The advanced simulation mode estimates sensitivity for the toolbox's supported
FPVS mixed model:

`value ~ condition * ROI + participant random intercept`

Enter analyzable participants, condition and ROI counts, desired power, alpha,
within-participant correlation, simulation count, and a reproducible random
seed. Choose one simulated effect:

- a standardized difference between two condition levels;
- a standardized difference between two ROI levels; or
- a standardized 2 × 2 condition × ROI difference-in-differences.

The selected contrast is embedded in the full condition × ROI design. Each
simulated dataset is fitted with the random-intercept mixed model, and the
selected fixed-effect coefficient block is evaluated with an omnibus Wald test.
The tool searches for the standardized contrast corresponding approximately to
the requested power.

Mixed-model effects are reported in residual-standard-deviation units. They are
not labeled Cohen's *d* or *f*, and conventional small/medium/large benchmarks
are not applied. The result includes estimated simulated power, a 95% Monte
Carlo interval, successful fits, failed fits, singular fits, and the random
seed. The Monte Carlo interval describes finite-simulation uncertainty; it is
not a confidence interval for the real study effect.

The simulation does not support between-participant groups, random slopes,
covariates, missing cells, or generalized outcomes. It runs in a background
worker and can be cancelled without blocking the Main App.

This workflow follows the general simulation-based mixed-model power approach
described by Green and MacLeod (2016): repeatedly simulate data from a specified
mixed model, refit the model, and estimate power from the proportion of
significant tests.

- Green, P., & MacLeod, C. J. (2016). [SIMR: an R package for power analysis of generalized linear mixed models by simulation](https://doi.org/10.1111/2041-210X.12504). *Methods in Ecology and Evolution, 7*(4), 493–498.

## Defaults

The initial values are:

- sample size: 24;
- desired power: 0.80;
- alpha: 0.05;
- alternative: two-sided;
- conditions: 2;
- ROIs: 1;
- effect evaluated: condition effect, producing 2 repeated measurements;
- average correlation: 0.50; and
- epsilon: 1.00.

The mixed-model mode defaults to 2 conditions, 2 ROIs, a condition contrast,
within-participant correlation of 0.50, 400 final simulations, and seed 2026.

Select **Reset Defaults** at any time to restore these values.

## Interpreting the Result

The result is the effect at which the model reaches the requested power, not an
expected effect or a guarantee. Under the entered assumptions, smaller true
effects have less than the requested power, but they are not ruled out. For
example, 80% power at Cohen's *d* = 0.60 means that, if the true effect were
0.60, repeating the same study many times would be expected to produce a
statistically significant result about 80% of the time. A smaller true effect
would produce significance less often than 80%, but it could still be detected.
A non-significant result does not prove that no effect exists. The result panel
uses neutral informational styling because the estimate is not a pass/fail
judgment.

After calculation, the page also provides an interpretation, a compact summary
of the assumptions used, and a reporting-ready sentence.
Changing any result-affecting input clears these outputs so a stale result is
not shown beside new assumptions.

For the two analytical modes, the tool also shows conventional Cohen
benchmarks:

- Cohen's *d*: 0.20 small, 0.50 medium, and 0.80 large;
- Cohen's *f*: 0.10 small, 0.25 medium, and 0.40 large.

These labels are descriptive reference points only. They do not establish
theoretical, clinical, or practical importance. Study-specific prior evidence,
measurement reliability, exclusions, model assumptions, and multiplicity may
all affect whether a planned sample is adequate.

The alpha entry applies to the test being evaluated. Sensitivity Analysis does
not automatically adjust alpha for multiple planned tests.
