# Which Statistical Test Should I Use?

Use this page when you have processed data and need to choose the next Statistics tool analysis.

The right test depends on the question you want to answer and whether every participant has data for every condition and ROI.

## Quick decision table

| Your question | Dataset pattern | Use this analysis | Main output |
|---|---|---|---|
| Do responses differ across conditions or ROIs? | Every participant has every condition x ROI cell. | RM-ANOVA | Main effects and interactions. |
| Do responses differ across conditions or ROIs when a few cells are missing? | A small number of participant-condition-ROI cells are missing. | Mixed model | Fixed-effect tests while accounting for participant differences. |
| Which specific condition pairs differ? | You already have a meaningful main effect or interaction to follow up. | Post-hoc paired tests | Condition-pair comparisons within each ROI. |
| Is a condition response above the no-response baseline? | You want detectability relative to zero BCA. | Baseline vs zero tests | Condition x ROI tests against baseline. |
| Which harmonics should contribute to Summed BCA? | You need to confirm the default group-level selection or alternate fixed list. | Harmonic selection | Harmonic set used to build the dependent variable. |
| Are there unusual values or exclusions to review? | Before final reporting. | Outliers and QC | Flagged and excluded participant reports. |

!!! warning "Do not use RM-ANOVA for missing repeated-measures cells"
    RM-ANOVA expects a complete table. If some participants are missing condition x ROI values, use the mixed model or resolve the missing cells before running RM-ANOVA.

!!! warning "Post-hoc tests answer a narrower question"
    Post-hoc tests do not replace the main model. Use them to explain which condition pairs differ after the main analysis shows a pattern worth following up.

## Recommended workflow

1. Confirm the Statistics tool detects conditions, ROIs, and participant IDs correctly.
2. Run harmonic selection if your workflow uses Summed BCA.
3. Check whether the dataset is complete across participant x condition x ROI.
4. Use RM-ANOVA for complete repeated-measures data, or mixed model for minor imbalance.
5. Use post-hoc tests to explain specific condition differences.
6. Use baseline vs zero tests when your question is detectability above local noise.
7. Review outliers and QC before final interpretation.

## Examples

| Situation | Recommended choice |
|---|---|
| 30 participants, 4 conditions, 3 ROIs, no missing cells. | Start with RM-ANOVA. |
| 30 participants, but 2 participants are missing one condition. | Start with mixed model. |
| Condition x ROI interaction is significant. | Run post-hoc paired tests within each ROI. |
| You need to know whether `Faces` has a detectable response in occipital ROI. | Run baseline vs zero tests. |
| You need to justify which oddball harmonics were included. | Archive the DV definition export and the stats-ready `Harmonic_Selection` sheet. |

## What to report

When reporting results, include:

- the dependent variable, such as Summed BCA;
- the conditions and ROIs included;
- whether missing cells were present;
- the main model or test used;
- the correction method for multiple comparisons;
- any exclusions or QC flags.
