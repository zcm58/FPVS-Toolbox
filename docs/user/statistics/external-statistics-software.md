# External statistics software exports

Use this page when you want to analyze FPVS Toolbox data in JASP, R/RStudio,
or SAS instead of relying only on the built-in Statistics tool.

FPVS Toolbox can write an additional workbook named
`Stats_Ready_Summed_BCA.xlsx`. This workbook is additive: it does not replace
or change the existing per-subject Excel files, the existing Statistics tool
outputs, or the Analyze Single Group workflow.

The workbook contains the participant-level dependent variable used by the
Statistics tool:

**Summed BCA** = baseline-corrected amplitude, summed across the selected
oddball harmonics, then averaged within each selected ROI.

That means each participant has one Summed BCA value for each selected
condition and ROI. External software can then compare those values across
conditions, ROIs, and experimental groups.

## When to use this export

Use the stats-ready workbook when:

- You need an analysis that is not yet built into FPVS Toolbox.
- You want to run the same Summed BCA data in JASP, R/RStudio, or SAS.
- You have more than one experimental group and need between-group tests.
- You want to share an analysis-ready data file with a statistician.
- You want to keep FPVS preprocessing and harmonic selection in Toolbox, but
  run the final model elsewhere.

Do not use this workbook to inspect single-electrode harmonic-level values.
It is designed for participant-level statistics after ROI averaging and
harmonic summation have already happened.

## Create the workbook

1. Open the Statistics tool.
2. Confirm that the project data folder is selected and scanned.
3. Select the conditions you want to analyze.
4. Confirm the ROIs in Settings.
5. Confirm the Summed BCA policy:
   - Rossion harmonic selection, or
   - Fixed-K harmonic summation.
6. Click **Export Stats-Ready Workbook** in the Comparison Exports section.
7. Use the Last Export path to open or copy the workbook location.

The export uses the same selected subjects, selected conditions, selected
ROIs, base frequency, and Summed BCA policy shown in the Statistics tool.
Manual participant exclusions are applied before the workbook is written.

## Workbook sheets

| Sheet | Use it for | Shape |
|---|---|---|
| `RStudio_Long` | R/RStudio ANOVA, mixed models, post-hoc tests, and FDR correction | One row per subject x condition x ROI |
| `SAS_Long` | SAS `PROC MIXED` and SAS import workflows | Same records as `RStudio_Long`, with SAS-friendly column names |
| `JASP_RM_ANOVA` | JASP repeated-measures ANOVA | One row per subject, one numeric column per condition x ROI cell |
| `JASP_Long_Mixed` | JASP mixed models | Same shape as `RStudio_Long` |
| `Data_Dictionary` | Column definitions and wide-column mapping | Reference sheet |
| `Analysis_Recipes` | Short software-specific analysis reminders | Reference sheet |

The R/RStudio, SAS, and JASP long sheets contain the same Summed BCA values.
They are separate only to make import easier. They do not calculate different
dependent variables.

## Important columns

| Column | Meaning |
|---|---|
| `subject_uid` | Unique participant key for analysis. Use this as the subject or participant ID in models. |
| `subject_id` | Original participant label. |
| `group_id` | Experimental group. For single-group projects this may be `single_group` or the project group label. |
| `condition` | Condition name from the selected Excel files. |
| `roi` | ROI name from the selected ROI settings. |
| `summed_bca_uv` | Dependent variable for analysis, in microvolts. |
| `selected_harmonics_hz` | Harmonic frequencies used for that ROI, separated by semicolons. |
| `harmonic_count` | Number of harmonics included in the Summed BCA value. |
| `dv_policy` | Harmonic selection policy used for the export. |
| `fallback_used` | Whether the policy used an explicit empty-harmonic fallback for that ROI. |
| `source_workbook` or `source_file` | Source participant workbook used for that row. |

For multi-group projects, keep `group_id` in the analysis. Do not average
across groups before importing the data into external software.

## JASP: repeated-measures ANOVA

Use `JASP_RM_ANOVA` when you want the regular JASP repeated-measures ANOVA
interface.

1. Open JASP.
2. Open `Stats_Ready_Summed_BCA.xlsx`.
3. Choose the `JASP_RM_ANOVA` sheet if JASP asks which sheet to load.
4. Confirm that the condition x ROI columns are numeric scale variables.
5. Go to **ANOVA** > **Repeated Measures ANOVA**.
6. Create the repeated-measures factors:
   - Use `condition` as one repeated-measures factor.
   - Use `roi` as the second repeated-measures factor when you are analyzing
     more than one ROI.
7. Add the levels in the same order as the workbook columns.
8. Move each wide data column into the matching repeated-measures cell.
9. If the project has more than one group, add `group_id` as a
   between-subjects factor.
10. Select the effect-size, assumption-check, sphericity-correction,
    post-hoc, and multiple-comparison options required by your analysis plan.

For example, if the sheet has columns named `Face__Occipital`,
`Face__Frontal`, `Object__Occipital`, and `Object__Frontal`, define one
factor for condition (`Face`, `Object`) and one factor for ROI (`Occipital`,
`Frontal`), then assign the four columns to the matching cells.

If JASP removes participants from an RM-ANOVA, check whether a repeated cell
is blank. Standard repeated-measures ANOVA usually requires complete data.
If you have missing cells, use a mixed model instead.

## JASP: linear mixed model

Use `JASP_Long_Mixed` when you need a mixed model or when the dataset has
minor missing condition x ROI cells.

1. Open `Stats_Ready_Summed_BCA.xlsx` in JASP.
2. Choose the `JASP_Long_Mixed` sheet.
3. Confirm variable types:
   - `summed_bca_uv` should be numeric or scale.
   - `subject_uid`, `condition`, `roi`, and `group_id` should be categorical.
4. Open the Linear Mixed Models analysis.
5. Set `summed_bca_uv` as the dependent variable.
6. Add `condition` and `roi` as fixed factors.
7. If there is more than one group, add `group_id` as a fixed factor.
8. Add the interactions required by the study design, usually
   `condition x roi` for a single group or `group_id x condition x roi` for
   a multi-group project.
9. Add `subject_uid` as the participant random effect, usually as a random
   intercept.
10. Use post-hoc or estimated marginal means options to compare specific
    conditions or ROIs.

If the project has only one group, do not force `group_id` into the model as
a predictor. A factor with only one level cannot explain differences.

## R/RStudio

Use `RStudio_Long`. This is the most flexible sheet and is the recommended
starting point for scripted analyses.

Install packages once:

```r
install.packages(c("readxl", "dplyr", "afex", "emmeans", "lme4", "lmerTest"))
```

Read the workbook:

```r
library(readxl)
library(dplyr)

path <- "C:/path/to/Stats_Ready_Summed_BCA.xlsx"

df <- read_excel(path, sheet = "RStudio_Long") |>
  mutate(
    subject_uid = factor(subject_uid),
    subject_id = factor(subject_id),
    group_id = factor(group_id),
    condition = factor(condition),
    roi = factor(roi)
  )
```

### RM-ANOVA in R

For a single-group project:

```r
library(afex)

anova_single <- aov_ez(
  id = "subject_uid",
  dv = "summed_bca_uv",
  within = c("condition", "roi"),
  data = df
)

anova_single
```

For a multi-group project:

```r
anova_groups <- aov_ez(
  id = "subject_uid",
  dv = "summed_bca_uv",
  within = c("condition", "roi"),
  between = "group_id",
  data = df
)

anova_groups
```

Use RM-ANOVA when every participant has every required condition x ROI cell.
If cells are missing, use a mixed model.

### Linear mixed model in R

For a single-group project:

```r
library(lmerTest)

m_single <- lmer(
  summed_bca_uv ~ condition * roi + (1 | subject_uid),
  data = df,
  REML = FALSE
)

anova(m_single)
summary(m_single)
```

For a multi-group project:

```r
m_groups <- lmer(
  summed_bca_uv ~ group_id * condition * roi + (1 | subject_uid),
  data = df,
  REML = FALSE
)

anova(m_groups)
summary(m_groups)
```

The random intercept `(1 | subject_uid)` tells R that repeated rows from the
same participant are related.

### Post-hoc tests and FDR correction in R

Use `emmeans` for model-based comparisons:

```r
library(emmeans)

emm <- emmeans(m_groups, ~ condition | roi * group_id)
pairs_by_roi_group <- pairs(emm)
summary(pairs_by_roi_group, adjust = "fdr")
```

You can also adjust a vector of p-values directly:

```r
raw_p <- c(0.01, 0.03, 0.20, 0.04)
p.adjust(raw_p, method = "BH")
```

Use the correction family that matches the research question. For example,
correct condition-pair tests within each ROI if those are the planned
families of comparisons.

## SAS

Use `SAS_Long`. It contains the same records as `RStudio_Long`, but the
headers are kept short, lowercase, and underscore-delimited for SAS import.

Import the workbook:

```sas
proc import datafile="C:\path\to\Stats_Ready_Summed_BCA.xlsx"
    out=fpvs_long
    dbms=xlsx
    replace;
    sheet="SAS_Long";
    getnames=yes;
run;
```

### PROC MIXED for a single group

```sas
proc mixed data=fpvs_long method=reml;
    class subject_uid condition roi;
    model summed_bca_uv = condition|roi / ddfm=satterth solution;
    random intercept / subject=subject_uid;
    lsmeans condition*roi / diff;
run;
```

### PROC MIXED for more than one group

```sas
proc mixed data=fpvs_long method=reml;
    class subject_uid group_id condition roi;
    model summed_bca_uv = group_id|condition|roi / ddfm=satterth solution;
    random intercept / subject=subject_uid;
    lsmeans group_id*condition*roi / diff;
run;
```

The `class` statement tells SAS which variables are categorical. The random
intercept accounts for repeated measurements from the same participant.

### FDR correction in SAS

If you save post-hoc p-values into a SAS dataset, you can adjust them with
`PROC MULTTEST`. The raw p-value variable name depends on the output table
you save from your model.

Example pattern:

```sas
proc multtest inpvalues(raw_p)=posthoc_pvalues fdr;
run;
```

In this example, `posthoc_pvalues` is the SAS dataset and `raw_p` is the
column containing unadjusted p-values. Before reporting results, confirm that
the p-value column is the family of tests you intended to correct.

## Multi-group projects

The workbook is designed so between-group analyses are possible without
manual recovery of group membership.

For multi-group projects:

- Keep `subject_uid` as the participant identifier.
- Keep `group_id` as the between-subject factor.
- Do not average participant rows before import.
- In JASP RM-ANOVA, use `group_id` as a between-subjects factor.
- In R/RStudio, include `between = "group_id"` for `aov_ez()` or include
  `group_id` in the mixed-model formula.
- In SAS, include `group_id` in the `class` statement and the `model`
  statement.

If group labels are missing for some participants, fix the project
participant metadata before using the export. Mixing labeled and unlabeled
participants can make between-group results invalid.

## Quality checks before analysis

Before running the final model:

1. Open `Data_Dictionary`.
2. Confirm that `summed_bca_uv` is the dependent variable.
3. Confirm that the selected harmonics match the intended Rossion or Fixed-K
   policy.
4. Check `fallback_used`.
5. Confirm that every participant has the expected number of rows:
   `number of selected conditions x number of selected ROIs`.
6. Confirm that `group_id` is correct for every participant in multi-group
   projects.
7. Treat blank Summed BCA values as missing data, not as zeros, unless the
   data dictionary shows that the selected DV policy intentionally produced a
   zero value.

## Useful references

- [JASP supported import formats and analysis modules](https://jasp-stats.org/features/)
- [JASP getting started and data import notes](https://jasp-stats.org/getting-started/)
- [readxl `read_excel()` reference](https://readxl.tidyverse.org/reference/read_excel.html)
- [afex ANOVA functions for long-format data](https://www.rdocumentation.org/packages/afex/versions/0.17-8)
- [lme4 `lmer()` reference](https://lme4.github.io/lme4/reference/lmer.html)
- [R `p.adjust()` reference](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)
- [SAS PROC MIXED documentation](https://support.sas.com/documentation/cdl/en/statug/63033/HTML/default/mixed_toc.htm)
- [SAS PROC IMPORT documentation](https://support.sas.com/documentation/cdl/en/acpcref/63184/HTML/default/a003102096.htm)
- [SAS PROC MULTTEST raw p-value adjustment example](https://support.sas.com/documentation/cdl/en/statug/63347/HTML/default/statug_multtest_sect026.htm)
