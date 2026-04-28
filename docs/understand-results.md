# Understand Results

Use this page when processing has finished and you need to decide how to interpret FPVS Toolbox outputs.

This section connects the exported metrics to the statistical choices you make in the app.

| Page | Use this page when... |
|---|---|
| [FFT and Frequency-Domain Quantification](fft-frequency-domain-quantification.md) | You want to understand SNR, BCA, Z scores, and harmonics. |
| [Statistical Analysis Overview](statistical-analysis.md) | You want a high-level map of the Statistics tool. |
| [Which Statistical Test Should I Use?](statistics/which-test.md) | You need to choose between RM-ANOVA, mixed model, post-hoc tests, and baseline vs zero tests. |
| [Outliers and QC](statistics/outliers-and-qc.md) | You need to inspect unusual values or explain exclusions. |

## Statistics workflow diagram

```text
Excel outputs
  -> choose ROI definitions
  -> select harmonics
  -> build Summed BCA values
  -> run model or tests
  -> review post-hoc and QC outputs
```

Alt text: A statistics workflow from Excel outputs through ROI definitions, harmonic selection, Summed BCA values, model tests, post-hoc comparisons, and QC outputs.

## Common decision points

- Use [Which Statistical Test Should I Use?](statistics/which-test.md) if you are unsure which analysis matches your study design.
- Use [Outliers and QC](statistics/outliers-and-qc.md) before final reporting.
- Use [Glossary](glossary.md) when a metric or statistical term is unfamiliar.
