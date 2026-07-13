# Sensitivity Analysis

Sensitivity Analysis estimates the smallest standardized effect a study would
be powered to detect under assumptions you enter manually. It is a descriptive,
G*Power-style, idealized design-sensitivity calculator and is separate from the
Statistical Analysis tool. Its primary result is a minimum standardized
detectable contrast conditional on the entered assumptions.

The tool does not read participant data or project settings. It does not save,
export, or modify any files. Because it does not inspect observed data, it does
not validate residuals, variance estimates, convergence, missingness, or the
fit of a completed study's model.

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
within-participant correlation, and simulation count. The tool generates a new
internal random seed each time the embedded page is opened. Choose one simulated
effect:

- a standardized difference between two condition levels;
- a standardized difference between two ROI levels; or
- a standardized 2 × 2 condition × ROI difference-in-differences.

The primary Design tab contains analyzable participants, the effect, condition
count, and ROI count. These three numeric design inputs start blank whenever the
tool is opened and must be entered before running a simulation. The Advanced tab
contains random-intercept correlation and the independent confirmation
simulation count. Most users can retain both advanced defaults. The 0.50
correlation is a neutral assumption inherited from the tool's original
repeated-measures setup; it was not estimated from FPVS data or selected from a
specific FPVS publication. Under the current residual-SD parameterization, the
participant random intercept cancels from the supported within-participant
contrasts, so changing this value usually has little effect on the result.

The selected contrast is embedded in the full condition × ROI design. Each
simulated dataset is fitted with the random-intercept mixed model, and the
selected fixed-effect coefficient block is evaluated with an omnibus Wald test.
The tool searches for the standardized contrast corresponding approximately to
the requested power.

The effect search is adaptive. Each candidate begins with a small simulation
batch and receives additional batches, up to 2,000 simulations, when its Monte
Carlo interval overlaps the requested power. Candidate effects share the same
search datasets so comparisons are stable. By default, the final confirmation
uses 10,000 simulated studies from a separate random stream that did not select
the effect. If that confirmation falls below target power, the tool performs
one fresh local search and a second independent confirmation. Up to eight
worker processes run model fits concurrently while keeping the GUI responsive.

Mixed-model effects are reported in residual-standard-deviation units. They are
not labeled Cohen's *d* or *f*, and conventional small/medium/large benchmarks
are not applied. The result includes estimated simulated power, a 95% Monte
Carlo interval, successful fits, failed fits, singular fits, and the random
seed used for that run. Reporting the seed preserves an audit trail even though
it is not an editable input. The Monte Carlo interval describes
finite-simulation uncertainty; it is not a confidence interval for the real
study effect.

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

The mixed-model Design tab requires manual entry of analyzable participants,
conditions, and ROIs for every opening. Its effect defaults to a condition
contrast. Advanced defaults are random-intercept correlation 0.50 and 10,000
independent confirmation simulations; a hidden seed is randomized per opening.

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
