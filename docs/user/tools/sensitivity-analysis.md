# Sensitivity Analysis

Sensitivity Analysis estimates the smallest standardized effect a study would
be powered to detect under assumptions you enter manually. It is a descriptive,
G*Power-style calculator and is separate from the Statistical Analysis tool.

The tool does not read participant data or project settings. It does not save,
export, or modify any files.

## Supported Designs

### Paired or One-Sample t-Test

Enter the sample size, desired power, alpha, and whether the test is two-sided
or one-sided. The result is the minimum detectable Cohen's *dz*. For a paired
test, *dz* standardizes the mean within-participant difference by the standard
deviation of those difference scores.

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
sphericity.

The omnibus condition × ROI option treats all cells as levels of one
within-participant factor. It does not specifically estimate power for a
condition × ROI interaction. Use the information button in the Study
Assumptions card for examples and interpretation guidance.

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

Select **Reset Defaults** at any time to restore these values.

## Interpreting the Result

The result is a minimum detectable effect, not an expected effect. Under the
entered assumptions, smaller true effects would have less than the requested
power.

The tool also shows conventional Cohen benchmarks:

- Cohen's *d*: 0.20 small, 0.50 medium, and 0.80 large;
- Cohen's *f*: 0.10 small, 0.25 medium, and 0.40 large.

These labels are descriptive reference points only. They do not establish
theoretical, clinical, or practical importance. Study-specific prior evidence,
measurement reliability, exclusions, model assumptions, and multiplicity may
all affect whether a planned sample is adequate.
