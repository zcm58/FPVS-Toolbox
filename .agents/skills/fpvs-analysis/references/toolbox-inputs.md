# Toolbox analysis inputs

## Prefer the released analysis table

- Start with `3 - Statistical Analysis Results/Analysis_Ready_Summed_BCA_Full_Audit.xlsx`
  in the active project root. The [export contract](../../../../docs/agent/architecture/post-processing-export-contract.md#full-audit-analysis-ready-workbook)
  owns its coverage and semantics. Verify that it belongs to the intended
  project and reviewed run. Check `Selection Summary`, `Harmonic Selection`,
  `ROI Definitions`, `ROI Coverage`, `QC Flags`, and `Analysis Notes` as
  applicable. A historical workbook can document a historical analysis when its
  cohort and provenance are identifiable.
- Read `ROI Long` for participant-level ROI analyses. The legacy key is
  `PID × Condition × ROI`; the repeated key is
  `Recording ID × Condition × ROI`, with the recording linked to `PID`,
  `Session ID` and `Visit Index`. Preserve ID strings, including leading
  zeros. Use the manifest and the public `Main_App.projects` dataset index
  if you need to resolve canonical identities, groups, or expected visits.
  Group membership comes from participant metadata. Treat blanks and
  ambiguous joins as unresolved. Use `Days From Baseline` only if the
  study analysis defines it as an exposure or time variable.
- Validate keys before and after joins, assert group membership is stable
  across visits for a between-participant factor, and compare the observed
  table against the intended group × visit × condition × ROI cells. If there
  are multiple recordings within a participant-visit, establish whether
  these are true repeats, alternate exports, or errors before aggregating or
  modeling. Preserve the distinction between exclusions, missing recordings,
  eligible but unavailable values, and valid near-zero or negative values.
  QC flags can be annotations. Apply documented eligibility decisions at
  their recorded scope and give the reason for any additional analysis-only
  exclusions. Count participants, recordings, complete pairs, and rows
  separately when relevant.
- `Stats_Ready_Summed_BCA.xlsx` is a filtered compatibility export. If it is
  the only input, state the limits on visit and coverage reconstruction and
  check whether they prevent the requested inference. For non-Toolbox input,
  map each field and unit to a documented equivalent before joining or fitting.

## Freeze the response before testing

| Question | Appropriate response or check |
| --- | --- |
| Is a tagged response larger? | For a Toolbox amplitude analysis use `Raw Summed BCA` (µV), unless another outcome was specified. The export sums baseline-corrected harmonics per electrode, then averages the frozen ROI. Negative BCA is a valid estimate. |
| Do responses have different scalp distributions independent of overall magnitude? | Use a prespecified topographic normalization and test a distribution contrast, such as Condition × ROI. Toolbox `RMS Normalized BCA` divides each harmonic by its whole-scalp L2 norm before summation. The signed-mean-normalized derivative has a different denominator and can be unstable near zero. Identify the exact normalization and its failures. |
| Is the response detectable relative to local noise? | Specify the spectrum, neighboring-bin rule, ROI and harmonic summary, threshold, tail, and multiplicity. Summed BCA, SNR, and local spectral Z answer different measurement questions. If screening multiple people, ROIs, conditions, or frequencies, retain the tested family and avoid selecting only detected participants for an amplitude comparison. |
| Is the general visual response different too? | Analyze base-rate harmonics as a separately defined outcome if relevant. An oddball contrast measures tagged differential response. A similar base response alone cannot establish equivalent engagement or attention. |

- For Toolbox analyses use the processing-owned exact selected harmonics, base
  overlap exclusions, selection profile and fingerprint. Compare analysis
  cells on a common eligible harmonic definition, ROI channel set, and
  compatible recording protocol, frequency grid, scaling, and montage. If
  different protocols or releases preclude this, restrict scope with reasons
  or analyze separately. Report the chosen bins and baseline method when
  reconstructing a published analysis instead of using released BCA.
- Prefer ROIs and harmonics fixed from a protocol, prior studies, or an
  independent dataset for confirmatory use. Report groups or conditions used
  to derive a pooled selection and identify contrast-driven choices as
  exploratory. Pooling can reduce contrast-driven selection but does not
  establish independent evidence for response-versus-zero detection. Document
  any inferential validity argument for same-data selection.
- A primary ROI value requiring unavailable frozen channels or harmonics
  stays missing. Preserve recorded interpolation and effective ROI coverage.
  For external reconstruction, state aggregation order and any averaging
  across trials or recordings. Report unequal accepted trial counts or usable
  durations by design cell when available. These can affect measurement
  precision and QC. Weight by precision only with a justified model and a
  stated estimand. The independent sample size comes from participants.

See [Statistics and tool modules](../../../../docs/agent/architecture/statistics-tools.md#relationship-to-published-fpvs-statistics)
for the Toolbox-specific harmonic and statistical choices.
