# Free Harmonic Clustering Analysis Agent Contract

## Scope

This package owns the clean-room Free Harmonic Clustering Analysis backend and
its thin embedded GUI. Numerical preparation, inference, and export modules
remain GUI-neutral. The GUI gathers active-project context, runs one legacy
contrast or one versioned repeated-session batch, and presents a concise
current-session result while delegating long work to signal-driven workers.

## Non-Negotiables

- The public tool title is `Free Harmonic Clustering Analysis`.
- Expose the GUI through the Main App's default Quick Tools route without
  requiring Beta Tools. Keep the page project-bound, discard current-session
  results when the active project changes, and reload that project's saved FHC
  recording exclusions.
- Do not copy, translate, import, or redistribute the authors' restrictively
  licensed MATLAB code or `.mat` layout.
- Read scientific inputs only from original `FullFFT Amplitude (uV)` condition
  workbooks discovered through `Main_App.projects.load_project_dataset_index`.
  Do not read Stats-ready Summed BCA workbooks.
- Read exact FullFFT headers and selected columns through the neutral
  `Main_App.io` XLSX-reader surface. Do not depend on the beta Stats package's
  compatibility adapter.
- Both GUI inspection and direct preparation must validate
  `Main_App.processing.full_fft_provenance`. That neutral project-local record
  owns source paths, rates, grid, cohort/QC, and processing/export identity. Do
  not require or fall back to `tools.stats.group_significant_harmonics_cache`.
- Standard harmonic-profile settings, detected/included lists, selection
  fingerprints, and Summed-BCA artifact freshness are outside this tool's
  numerical preparation. A stale standard derivative alone must not block
  preparation; stale/missing FullFFT, cohort/QC, rate, grid, or processing-
  export provenance must block with a post-processing remedy.
- Canonical groups and participant identities come only from `project.json`
  through the shared dataset index. Never infer group membership from folders.
- Keep the paper-faithful SNR/z/noise-window/L2 rules isolated from the locked
  Standard FPVS Screening method. Do not change or reuse its SNR/BCA selection
  results as substitutes.
- Free-harmonic adjacency is complete across retained harmonics at the same
  sensor. It is not a harmonic chain.
- New analyses use the fixed, versioned 197-edge FieldTrip-style BioSemi64
  graph reconstructed independently for the Toolbox. Record its edge list and
  hash, and do not describe it as the authors' adjacency matrix.
- Permute whole participant tensors. Never shuffle sensors, harmonics, or
  individual nodes independently.
- Positive and negative clusters use separate extreme-cluster nulls. Report
  cluster-level inference only; never label individual nodes pointwise
  significant.
- Describe cluster correction as conditional on the candidate domain,
  adjacency, node-entry threshold, declared contrast family, and valid whole-
  participant exchangeability. It favors extended effects, does not provide
  pointwise node significance, and does not correct separately run contrasts.
- Keep automatic-domain validation explicitly two-layered. Routine focused/CI
  verification runs the deterministic 24-null-replicate x 199-assignment
  regression smoke with at most five global rejections. It detects gross
  regressions only and is not calibration or evidence of unconditional FWER
  control.
- Formal validation is the separate resumable
  `fhc_automatic_unconditional_null_v1` release diagnostic: 4,000 seeded null
  replicates, split into 2,000 paired and 2,000 independent replicates, with
  four frozen 500-replicate regimes per design and the production 10,000
  assignments per replicate. Keep it outside routine pytest, focused
  verification, and precommit.
- Formal acceptance requires every prespecified guardrail: within each design,
  a one-sided 97.5% exact Clopper-Pearson upper bound below `.070` (at most
  117/2,000 rejections), and within each regime, a one-sided 95% upper bound
  below `.10` (at most 38/500). Report every miss; never substitute the smoke
  layer or tune the envelope after results are inspected.
- The reviewed v1 receipt passed every guardrail: independent groups rejected
  in 111/2,000 replicates (97.5% upper bound `.06645369553133039`) and paired
  conditions in 91/2,000 (upper bound `.055572191006579195`); all eight regime
  cells passed, with zero errors or no-selection replicates. Treat this only as
  bounded empirical evidence for the frozen simulated regimes, never as
  universal proof, a power result, or evidence that a real-data finding is true.
- Require complete finite maps on one shared frequency grid and one shared
  BioSemi64 sensor set. Do not zero-fill or perform node-wise omission.
- Resolve all writes beneath the explicit managed project root. Do not mutate
  `project.json`, silently overwrite a prior run, or derive output paths from
  the current working directory.
- Treat the analysis as source-immutable. It may create or update its versioned
  project-local FHC preference file and create additive completed run bundles,
  but it must not change `project.json`, shared project settings, participant
  metadata, ledgers, QC decisions, or processed workbooks.
- Preserve exactly one ordered two-level contrast per legacy run. The
  `fhc_repeated_session_batch_v1` extension is the only all-condition batch:
  it requires two stable groups and two ordered sessions and runs the four
  prespecified participant-level families documented in `ARCHITECTURE.md`.
  It is not an omnibus model builder. Result plots, a historical-run browser,
  and clipboard/manuscript helpers remain out of scope.
- Keep repeated-session participant, recording, group, session, visit, and
  condition identity canonical. Use complete pairs for all primary families;
  report missing visits as coverage and never treat recordings as independent
  participants, impute visits, or zero-fill them.
- GUI analysis-specific recording exclusions are additive, project-local FHC
  preferences and require nonempty reasons. Persist them beneath the FHC results
  parent, reuse them for later repeated batches until changed, and export them
  with the cohort audit without mutating project QC or metadata. Headless CLI
  exclusions remain explicit and batch-local.
- Freeze one shared harmonic domain across the repeated batch. Preserve the
  versioned tensor semantics and apply run-level Holm correction across
  conditions within each of four families plus the conservative all-batch
  layer. Never relabel raw cluster p-values as cross-run adjusted p-values.
- The reviewed legacy powered-null receipt does not cover the repeated batch,
  shared multi-cell selection, composite tensors, group-session interaction,
  or Holm layers. State that limitation in user-facing methods and exports.
- Read base and oddball rates, conditions, canonical groups, exclusions,
  participants, and FullFFT availability dynamically. Do not add tool-local
  metadata overrides or hard-coded stimulation frequencies.
- Default to Hermann automatic harmonic selection. Fixed mode selects the
  highest oddball harmonic and fills through it; both modes dynamically exclude
  every base-rate overlap.
- Keep the Hermann-compatible profile fixed in version 1: 10,000 assignments,
  strict `z > 3.29`, +/-0.1-Hz selector/noise windows, participant/arm L2
  normalization, two-sided node-entry alpha `.01`, separate signed nulls, and
  raw sign-specific cluster alpha `.025`.

## Performance

- Build one deduplicated selected-column plan for all target/noise bins.
- Parse each selected FullFFT worksheet at most once per run.
- Convert workbook values immediately into preallocated contiguous arm tensors;
  do not accumulate participant arrays only to stack-copy them later.
- Vectorize preparation and batched t-map generation across participants,
  sensors, and harmonics. Per-permutation cluster extraction may iterate.
- Validate the spatial graph and build its deterministic edge table once per
  run. Reuse batch-invariant sums, squares, and assignment buffers.
- Null permutations may use a mass-only cluster path, but its signed extreme
  masses must remain bitwise-equivalent to the full component construction.
- Do not run-scope cache every source DataFrame when each workbook is consumed
  once; that duplicates memory.
- Preserve timing and selected-column counts in provenance.

## Public API

Keep the package root small. Public callers should use:

- `prepare_project_contrast(...)`
- `run_free_harmonic_clustering(...)`
- `export_free_harmonic_run(...)`
- `prepare_repeated_session_batch(...)`
- `run_repeated_session_fhc_batch(...)`
- `export_repeated_session_batch(...)`

Do not expose pandas frames, MNE objects, or XML-reader internals.

Embedded GUI callers use
`Tools.Free_Harmonic_Clustering.gui.FreeHarmonicClusteringPage`. Keep the
shared information content in `tool_info.py`; do not duplicate method text in
the page implementation.

## GUI And Outputs

- Use the shared `SectionCard`, `StatusBanner`, `ActionRow`, and tabbed
  `ToolInfoContent` patterns. Do not nest cards.
- Route missing or stale FullFFT provenance through the Main App's shared
  **Post-processing Required** dialog. The page emits the affected project and
  reason; it must not show the raw provenance failure in its footer or launch a
  post-processing worker itself.
- Use one tab-free workspace. Flat and repeated projects use **Run Free
  Harmonic Clustering Analysis**. Repeated projects are recognized
  automatically and replace the flat-project selectors with a compact stable-
  group summary, fixed-order warning, and a project-persistent analysis-only
  recording-exclusion dialog with required reasons. A concise Results section
  appears only after completion; detailed cohort, contrast-family, direction,
  harmonic, method, and run provenance remains in the exported workbook.
- Keep the embedded task pages free of page-level scroll areas. Bounded result
  tables may scroll internally when their data exceeds the available viewport.
- Legacy Results shows current-session significant clusters ordered by
  ascending raw tail p. Repeated Results shows the condition x family global p
  plus both Holm layers in one bounded table. It does not print assignment
  count, degrees of freedom, cluster-forming threshold, or seed in the main
  GUI. Full details remain in the exported workbook; past runs remain
  available through Open Results Folder.
- The primary human-readable artifact is a polished
  `Free_Harmonic_Clustering_Results.xlsx` workbook. Retain machine-readable
  CSV, compressed-array, and manifest artifacts alongside it.
- Repeated batches use
  `Free_Harmonic_Clustering_Repeated_Session_Batch.xlsx` with consolidated
  batch/cohort/multiplicity audit tables and the same reproducibility bundle.
- Preparation, permutation inference, multiplicity correction where applicable,
  and export run sequentially on one background analysis worker. Workers
  communicate through signals and never touch widgets; the page must not retain
  prepared/result tensors after their display strings have been populated.

## Verification

Use synthetic/temp-project fixtures under `tests/free_harmonic_clustering/`.
Do not make tests depend on the developer's ACR project. Run:

```powershell
python .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused
```

The focused command runs only the 24 x 199 smoke layer. The powered
4,000 x 10,000 calibration is manual, resumable release validation owned by
`docs/agent/quality/free-harmonic-clustering-null-calibration.md`. The reviewed
v1 receipt is
`docs/agent/quality/free-harmonic-clustering-null-calibration-v1-receipt.json`.
A pending, partial, interrupted, or unreviewed later receipt is not a pass and
must not support a changed statistical claim.

The headless numerical modules must not import PySide6. Keep GUI smoke coverage
registered for CI and do not run Qt locally on Windows.

The version 1 release gate is a visible end-to-end GUI reproduction of the
private ACR Neutral Happy comparison: 18 anxious versus 16 non-anxious
participants, retained H1/H2, positive H1 cluster at C1/Cz/CPz, and raw
sign-specific p approximately `.0043`. Do not bundle the ACR project or make
automated tests depend on it; automated preparation, inference, export, and GUI
coverage must use synthetic or temporary project fixtures.
