# Feature Tour

Use this page when you want a quick map of the main FPVS Toolbox features and when to use each one.

This page lists the main FPVS Toolbox features and when to use each one.

## Core features

| Feature | What it does | When to use it | Main output |
|---|---|---|---|
| Project setup | Stores project, group, condition, and trigger configuration | At the start of every study | Project settings and folder structure |
| EEG processing pipeline | Loads `.bdf`, preprocesses, epochs, runs FFT, computes metrics | After project setup and before stats | Per-condition Excel files |
| Harmonic selection (Rossion) | Selects oddball harmonics to include in Summed BCA | When building ROI-level dependent variables | Summed BCA DV Definition export |
| RM-ANOVA | Tests within-subject condition/ROI effects | Balanced repeated-measures designs | ANOVA result tables |
| Mixed model | Models repeated measures with participant random intercept | When data may be slightly unbalanced or for flexible modeling | Mixed model fixed-effects table |
| Post-hoc tests | Finds specific condition pairs that differ within each ROI | After significant interaction effects | Pairwise comparison tables |
| Baseline vs zero tests | Tests whether a condition ROI response is above no-response baseline | Detectability checks | Baseline vs Zero workbook |
| Outliers and QC | Flags unusual values and separates flags from exclusions | Before final inferential reporting | Flagged and excluded participant reports |
| Individual-level detectability tool | Creates participant-level topomap plus mini-spectrum figures | Participant-level reporting and diagnostics | Detectability figures |

## Typical order of use

1. Configure project and event map.
2. Run processing pipeline.
3. Confirm outputs in Excel.
4. Run harmonic selection and inferential statistics.
5. Generate QC reports and optional individual-level figures.

## Related docs

- [Processing Pipeline Overview](processing-pipeline.md)
- [Statistical Analysis Overview](statistical-analysis.md)
- [Output Files](outputs-reference.md)
