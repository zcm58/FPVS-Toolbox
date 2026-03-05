# Baseline vs Zero Tests (Condition × ROI)

## What this test answers (plain language)
This test asks a simple question: **does a condition produce a real oddball response, or is it indistinguishable from the local noise level?**  
In other words, it tests whether the average response for each **Condition × ROI** is **reliably greater than the “no-response” baseline**.

This is useful because the main Stats models (RM-ANOVA, Linear Mixed Models, and post-hoc paired tests) primarily tell you whether conditions differ from each other. They do not directly answer whether a single condition’s response is clearly above baseline.

## What “zero” means here (important)
The FPVS Toolbox typically analyzes responses using **Baseline-Corrected Amplitude (BCA)** (or a similar baseline-corrected metric). BCA is defined relative to a local estimate of the noise floor around the target frequency bin.

Because of this definition:
- The raw FFT amplitude is always above 0, but **BCA can be near 0** when there is no response.
- **BCA = 0** means the amplitude at the target frequency is, on average, the same as the surrounding local noise estimate.
- A **positive BCA** means the target bin’s amplitude is higher than the local noise estimate.

So, when this module tests “greater than zero,” it is testing whether the response is greater than the local noise floor *as defined by the BCA computation*.

## Statistical definition (technical)
For each Condition × ROI cell, the Toolbox performs a **one-sample t-test** comparing participant-level values against 0:

- Null hypothesis: the mean response is 0 (no response above the local noise estimate)
- Alternative hypothesis: the mean response is greater than 0 (a positive response above local noise)

The default alternative is one-tailed (“greater”), because the question is specifically whether a condition produces a positive response relative to baseline. (A two-tailed option may be available depending on the analysis settings.)

### Unit of analysis (to avoid pseudo-replication)
The test is run on **participant-level values** (one value per participant per Condition × ROI).  
It does **not** treat electrodes or trials as independent samples.

## Multiple comparisons correction (BH-FDR)
Because multiple Condition × ROI tests are run in the same analysis, the Toolbox applies multiple comparisons correction using **Benjamini–Hochberg False Discovery Rate (BH-FDR)**.

- The table includes both **p (raw)** and **p (BH-FDR corrected)**.
- The **reject** flag is determined using the corrected p-value at the chosen alpha level (e.g., 0.05).
- The correction scope is reported (e.g., “global” means all Condition × ROI tests in the output were corrected together as one family).

## How to interpret the output
If a Condition × ROI row has **reject = TRUE** (after BH-FDR correction), you can say:

> “This condition elicited a reliable response in this ROI that was significantly greater than the baseline-corrected no-response level (BH-FDR corrected).”

This supports the conclusion that the condition’s response is detectable above the local noise estimate used by the BCA computation.

### What this test does *not* prove
- It does not prove the response is “not noise” in an absolute philosophical sense. It supports a statistical conclusion given the Toolbox’s operational definition of local noise.
- It does not replace condition-vs-condition comparisons. A condition can be significantly greater than baseline while still being smaller than another condition.

## Common pitfalls and notes
- **Missingness:** If some participants are missing a condition, the test for that Condition × ROI will have a smaller N. The output reports N per test.
- **Small N:** With very small sample sizes, results may be unstable; the Toolbox will mark tests as insufficient when N is too small for reliable estimation.
- **Tail choice:** One-tailed tests are more sensitive to detecting positive responses. If you need a more conservative test, use a two-tailed alternative and report it explicitly.
- **Metric matters:**  
  - For **BCA**, “no-response” corresponds to ~0, so testing vs 0 is appropriate.  
  - For **SNR**, “no-response” corresponds to ~1, so the analogous test would be SNR > 1.  
  - For **Z scores**, “no-response” corresponds to ~0.

## Where this appears in exports
The results are saved as a separate workbook:
- **Baseline vs Zero Tests.xlsx**
  - Sheet: **Baseline_vs_Zero** (main results)
  - Sheet: **Metadata** (alpha, correction method/scope, alternative, DV name, timestamp, and N summaries)
