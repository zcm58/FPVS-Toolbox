# Free Harmonic Clustering Analysis Architecture

## Boundary

This is a sibling analysis tool under `src/Tools`, separate from Standard FPVS
Screening. Its numerical backend remains headless and widget-free. A thin
project-bound PySide6 surface under `gui/` gathers active-project context,
shows preparation and current-session results, and delegates preparation and
permutation work to workers. Neither layer changes preprocessing, workbook
schemas, harmonic-selection caches, project metadata, ledgers, QC state, or
source workbooks. Both layers validate the same neutral, processing-owned
FullFFT provenance; neither requires the standard Stats harmonic cache.

## Data Flow

```text
managed project root
  -> canonical dataset index and neutral FullFFT provenance validation
  -> QC/cohort freeze independent of standard Summed-BCA selection
  -> common FullFFT header and selected target/noise-column plan
  -> one streamed XML read per participant-condition workbook
  -> raw amplitude tensor and paper SNR/z preparation
  -> retained non-base harmonic domain and participant L2 normalization
  -> one GUI action chaining preparation and inference
  -> paired sign flips or independent group-label permutations
  -> optional repeated-session run-global Holm correction
  -> free-harmonic/spatial connected components and cluster-mass inference
  -> atomic project-local Excel workbook, manifest, tables, and compressed arrays
```

Array order is participant x sensor x harmonic at the public numerical
boundary. Flattening is sensor-major (`sensor * H + harmonic`) so the combined
graph is `spatial_adjacency kron I_H OR I_S kron complete_harmonic_adjacency`.

## Modules

- `models.py`: immutable requests, method specifications, prepared tensors,
  cluster results, and export receipts.
- `preparation.py`: exact frequency-window planning, grand-spectrum z selection,
  participant SNR, and L2 normalization.
- `inputs.py`: canonical managed-project discovery, neutral FullFFT provenance,
  cohort/QC enforcement, and selected-column FullFFT ingestion through the
  shared `Main_App.io` reader.
- `analysis.py`: versioned BioSemi64 adjacency, node t statistics, connected
  components, permutation nulls, cluster p-values, and cluster-average effects.
- `null_calibration.py`: GUI-neutral frozen powered-null generators, stable seed
  schedule, exact acceptance bounds, resumable result models, and receipt
  validation. It is developer validation code and is not imported by runtime
  GUI/API paths.
- `api.py`: stable orchestration boundary.
- `exports.py`: contained, atomic, provenance-rich result publication.
- `__main__.py`: headless command entry point; no separate scientific behavior.
- `tool_info.py`: shared tabbed Overview, Method, Interpretation, and References
  content plus the contextual harmonic fill-through explanation.
- `gui/backend_adapter.py`: translates active-project and GUI selections into
  immutable backend requests without adding scientific behavior.
- `gui/models.py`: GUI-only prepared/result view models.
- `gui/workers.py`: cancellable inspection plus one signal-driven analysis
  worker that prepares, permutes, and exports sequentially without touching
  widgets.
- `gui/page.py`: embedded `FreeHarmonicClusteringPage` with one scroll-free
  setup/results workspace plus a compact persistent status/action footer.
- `gui/exclusion_state.py`: versioned, atomic project-local persistence for the
  GUI's canonical recording exclusions beneath the FHC results parent.
- `gui/recording_exclusions_dialog.py`: source-immutable editor for project-
  persistent canonical recording exclusions; every selected row requires an
  audit reason.
- `gui/__init__.py`: small embedded-GUI import surface.

## Contrast Modes

- `independent_groups`: one condition, two canonical project groups, whole-
  participant label permutation with observed group sizes preserved, and a
  pooled independent t statistic.
- `paired_conditions`: two conditions in the same complete participant cohort,
  optional single canonical group filter, and whole-participant sign flips.

Each run owns one ordered A-minus-B sensor x harmonic family. A collection of
separate condition runs is not automatically corrected across conditions.

Repeated-session projects use the separately versioned
`fhc_repeated_session_batch_v1` contract. It requires exactly two stable groups
and two distinct ordered sessions, freezes one shared harmonic domain across
all declared cells, and emits four participant-level families per condition:

- `session_averaged_groups`: average the two candidate-SNR session tensors
  within a complete participant, L2-normalize the mean once, and compare groups;
- `paired_sessions_within_group:<group A>`: separately normalize each session,
  then sign-flip Visit 2 minus Visit 1 tensors within the first group;
- `paired_sessions_within_group:<group B>`: the same paired contrast within the
  second group; and
- `group_session_change`: compare the normalized-session Visit 2 minus Visit 1
  participant tensors between groups without renormalizing the difference.

All primary families use complete phase-balanced pairs. Missing visits and
analysis-specific recording exclusions with reasons remain in the cohort audit.
The GUI reloads its project-specific exclusions for later batches until the user
changes them; headless requests continue to provide exclusions per run. There is
no imputation, node-wise omission, or recording-level independence.

## Method Identity

The current scientific method version is
`hermann_free_harmonic_clustering_cleanroom_v2`. Version 2 distinguishes the
fixed 197-edge graph and explicit fixed-domain policy from the earlier
169-edge automatic-only prototype. It fixes and exports:

- +/-0.1-Hz physical noise windows;
- target and immediate-adjacent-bin exclusion;
- sample SD (`ddof=1`) for harmonic-selector z;
- `z > 3.29` and fill-through-highest non-base oddball harmonic;
- participant/arm L2 normalization;
- two-sided cluster-entry alpha `.01`;
- complete harmonic adjacency and the fixed, versioned 197-edge FieldTrip-style
  BioSemi64 spatial reconstruction;
- summed signed t mass, separate positive/negative nulls, 10,000 default
  assignments, strict FieldTrip-compatible Monte Carlo comparison with `+1`,
  and `.025` final alpha per direction.

The 197-edge graph is an independent Toolbox reconstruction, not the authors'
adjacency matrix. The manifest labels the implementation Hermann-compatible and
clean-room, but not numerically author-validated until unpublished reference
tensors, adjacency, and outputs become available.

Automatic mode derives eligible oddball harmonics from the project's base and
oddball rates and the observed FullFFT grid, selects the highest strict
grand-spectrum detection found in either contrast arm, and fills through while
excluding every base-rate overlap. Fixed mode replaces the detection step with
a user-selected highest harmonic and applies the same dynamic fill-through and
overlap exclusion. Missing project frequency metadata blocks preparation; the
GUI does not offer local overrides.

`Main_App.processing.full_fft_provenance` records project-relative FullFFT
source identity, exact grid/resolution, base and oddball rates, canonical
cohort/frequency-QC state, and processing/export ledger identity. GUI option
inspection and direct preparation both validate this record. Reviewed whole-
condition exclusions remove only their participant/recording condition cell;
reviewed condition-electrode exclusions on any selected cell block preparation
because this analysis requires the complete BioSemi64 graph. Decisions outside
the selected contrast do not widen that scope, and legacy `auto_*` suggestions
have no authority here. Standard profile
IDs, detected/included harmonics, Summed-BCA selection fingerprints, and the
freshness of Stats-ready/full-audit workbooks are intentionally absent. A
standard profile change therefore cannot change this tool's candidates or
prepared tensors; a changed FullFFT source, cohort/QC state, rate, grid, or
processing/export identity blocks preparation until post-processing rebuilds
the neutral record.

The repeated-session batch extends, but does not rename or recalibrate, the
legacy method. It reuses the fixed numerical graph/cluster-permutation core and
records its own batch contract, shared-domain fingerprint, tensor semantics,
derived per-run seeds, and multiplicity methods. The reviewed powered legacy
receipt is not evidence for the repeated composite tensors, interaction
contrast, shared multi-cell selector, or Holm layers.

## Inference Boundary

Cluster correction applies to one declared electrode x harmonic family,
conditional on the prepared candidate domain, the fixed spatial/free-harmonic
adjacency, node-entry threshold, contrast family, and valid whole-participant
exchangeability. It favors extended effects and does not turn cluster-level
significance into pointwise evidence for a sensor, harmonic, cell, or boundary.
Separate runs are separate uncorrected families.

Within a repeated-session batch, each condition-level electrode x harmonic run
first retains the same signed maximum-cluster correction. Its global two-sided
run p-value is the strongest observed cluster's doubled two-sided p-value (or 1
when no cluster forms). Holm correction is then applied across every declared
condition separately within each of the four scientific family IDs, with a
second conservative Holm layer across the entire condition x family batch.
Those Holm values are run-level annotations; cluster-specific raw p-values are
never presented as cross-condition adjusted values.

Automatic mode selects its observed-arm ceiling before permutation and then
holds that domain fixed. The conditional maximum-cluster null does not by
itself establish unconditional error control for the combined adaptive-
selection-plus-permutation procedure.

## Automatic-Domain Validation Layers

A global rejection means that one null replicate produces at least one
significant positive or negative cluster at the raw sign-specific `.025`
threshold.

Layer 1 is the deterministic CI regression smoke: 24 independent-group null
replicates, 199 assignments per replicate, automatic selection repeated end to
end, and at most five global rejections. Its deliberately broad envelope
protects implementation behavior but cannot estimate or establish
unconditional FWER.

Layer 2 is the separate powered
`fhc_automatic_unconditional_null_v1` calibration: 4,000 null replicates using
the production 10,000 assignments, balanced as 2,000 paired and 2,000
independent replicates and four frozen 500-replicate regimes within each design.
Each design must have a one-sided 97.5% exact Clopper-Pearson upper bound below
`.070` (at most 117/2,000), and each regime a one-sided 95% upper bound below
`.10` (at most 38/500).

`null_calibration.py` owns the GUI-neutral frozen generator, deterministic
seeds, acceptance calculations, and receipt validation. The resumable developer
runner under `scripts/manual_diagnostics/` records the method and adjacency
identities, protocol fingerprint, completed scientific rows, rejection counts,
exact bounds, and execution environment. It is never a routine test target.
The frozen protocol and receipt schema live in
`docs/agent/quality/free-harmonic-clustering-null-calibration.md`. The reviewed
v1 receipt is
`docs/agent/quality/free-harmonic-clustering-null-calibration-v1-receipt.json`.
It records 111/2,000 independent-group global rejections (`.0555`; one-sided
97.5% upper bound `.06645369553133039`) and 91/2,000 paired-condition
rejections (`.0455`; upper bound `.055572191006579195`). All eight 500-
replicate design-by-regime cells passed the prespecified 95% upper-bound rule;
the largest was 31/500 (`.062`; upper bound `.08276150904882956`). No replicate
errored or failed to select, selection ceilings varied in every cell, and the
serial/resume/parallel determinism check passed.

This completed calibration is bounded empirical evidence for the frozen
simulated regimes. It does not prove universal error control, statistical
power, or the truth of a real-data result. Automatic-mode inference remains
conditional on the candidate domain, adjacency, node-entry threshold, contrast
family, and whole-participant exchangeability.

## Embedded GUI Contract

- The page is part of the default Quick Tools list and does not depend on the
  Beta Tools setting.
- Flat-project Setup resolves one contrast and displays the A-minus-B direction.
  A repeated-session project is recognized from canonical inspection options
  and replaces the legacy selector with a compact stable-group summary and a
  project-persistent analysis-only recording-exclusion dialog with required
  reasons. One run action starts the applicable workflow. A concise Results
  section appears beneath Setup when complete; detailed cohort, exclusion,
  contrast-family, direction, harmonic, source-coverage, and participant x
  sensor x harmonic provenance remains in the exported workbook.
- Prepared arrays remain worker-local while the automatic permutation and
  export phases run, so source workbooks are not read a second time. After the
  result table receives plain display strings, the page retains no prepared or
  permutation tensors.
- Results is hidden before completion. Legacy Results shows current-session
  significant clusters in one bounded table ordered by ascending raw
  sign-specific p-value. Repeated Results shows one compact row per condition x
  family with the global run p-value and both Holm layers. Technical metadata
  and full cluster tables stay in the workbook. The page has no plots or
  run-history browser.
- About this analysis uses shared tabbed `ToolInfoContent`. A second contextual
  information dialog explains fixed-domain fill-through and base-overlap
  exclusion.
- Long preparation, permutations, repeated-batch multiplicity correction where
  applicable, and export run sequentially on one worker thread. Cancellation,
  failure, and project switching cannot publish a partial completed bundle.

## Output

Default runs publish beneath:

```text
<project>/3 - Statistical Analysis Results/
  Free Harmonic Clustering Analysis/<run-id>/
```

The output is additive, never overwrites a completed run, uses project-relative
source paths, and writes its completion manifest last before atomically
publishing the staged directory. Its primary human-readable artifact is
`Free_Harmonic_Clustering_Results.xlsx`, with ordered Run Summary, Significant
Clusters, All Clusters, Cluster Membership, Harmonic Selection, Participants
and Exclusions, Methods and Provenance, Node Statistics, and Null Distribution
worksheets. CSV, compressed-array, and manifest artifacts remain available for
machine use and audit.

Repeated batches publish the same way but use
`Free_Harmonic_Clustering_Repeated_Session_Batch.xlsx` and batch-oriented
summary, cohort/exclusion, shared-harmonic, cluster/membership, node/null,
methods/provenance, and source-audit tables within one additive directory.

## Legacy Version 1 Acceptance

Automated tests use synthetic or temporary project fixtures and never bundle or
depend on the private ACR project. Final acceptance additionally requires a
visible end-to-end GUI reproduction of the canonical ACR Neutral Happy result:
18 anxious versus 16 non-anxious participants, retained H1/H2, a positive H1
C1/Cz/CPz cluster, and raw sign-specific p approximately `.0043`. This manual
gate validates the complete project discovery, preparation, GUI, permutation,
and export path.
