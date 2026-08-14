# Free Harmonic Clustering Analysis Architecture

## Boundary

This is a sibling analysis tool under `src/Tools`, separate from Standard FPVS
Screening. Its numerical backend remains headless and widget-free. A thin
project-bound PySide6 beta surface under `gui/` gathers active-project context,
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
  -> GUI preparation review and explicit run confirmation
  -> paired sign flips or independent group-label permutations
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
  cohort/QC enforcement, and selected-column FullFFT ingestion.
- `analysis.py`: versioned BioSemi64 adjacency, node t statistics, connected
  components, permutation nulls, cluster p-values, and cluster-average effects.
- `api.py`: stable orchestration boundary.
- `exports.py`: contained, atomic, provenance-rich result publication.
- `__main__.py`: headless command entry point; no separate scientific behavior.
- `tool_info.py`: shared tabbed Overview, Method, Interpretation, and References
  content plus the contextual harmonic fill-through explanation.
- `gui/backend_adapter.py`: translates active-project and GUI selections into
  immutable backend requests without adding scientific behavior.
- `gui/models.py`: GUI-only prepared/result view models.
- `gui/workers.py`: cancellable signal-driven preparation and permutation
  workers; workers do not touch widgets.
- `gui/page.py`: embedded `FreeHarmonicClusteringPage` with flat Setup &
  Preparation and Results tabs.
- `gui/__init__.py`: small embedded-GUI import surface.

## Contrast Modes

- `independent_groups`: one condition, two canonical project groups, whole-
  participant label permutation with observed group sizes preserved, and a
  pooled independent t statistic.
- `paired_conditions`: two conditions in the same complete participant cohort,
  optional single canonical group filter, and whole-participant sign flips.

Each run owns one ordered A-minus-B sensor x harmonic family. A collection of
separate condition runs is not automatically corrected across conditions.

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
inspection and direct preparation both validate this record. Standard profile
IDs, detected/included harmonics, Summed-BCA selection fingerprints, and the
freshness of Stats-ready/full-audit workbooks are intentionally absent. A
standard profile change therefore cannot change this tool's candidates or
prepared tensors; a changed FullFFT source, cohort/QC state, rate, grid, or
processing/export identity blocks preparation until post-processing rebuilds
the neutral record.

## Inference Boundary

Cluster correction applies to one declared electrode x harmonic family,
conditional on the prepared candidate domain, the fixed spatial/free-harmonic
adjacency, node-entry threshold, contrast family, and valid whole-participant
exchangeability. It favors extended effects and does not turn cluster-level
significance into pointwise evidence for a sensor, harmonic, cell, or boundary.
Separate runs are separate uncorrected families.

Automatic mode selects its observed-arm ceiling before permutation and then
holds that domain fixed. The conditional maximum-cluster null does not by
itself establish unconditional error control for the combined adaptive-
selection-plus-permutation procedure. The deterministic regression harness
repeats automatic selection and permutation across 24 seeded null replicates,
requires the selected domain to vary while retaining at least two harmonics,
and accepts at most 5 global rejections with 199 assignments per replicate.
That deliberately wide, prespecified envelope detects gross regressions; it is
not a calibrated FWER validation study.

## Embedded GUI Contract

- The page is visible only when Beta Tools are enabled.
- Setup & Preparation resolves one contrast, displays the A-minus-B direction,
  and previews included/excluded participants, incomplete pairs, selected
  harmonics, source coverage, and participant x sensor x harmonic shape.
- Prepared arrays remain in memory so Run Permutations does not reread source
  workbooks.
- The Results tab is disabled before completion and shows only the current
  session's latest run. Significant clusters appear first by ascending raw
  sign-specific p-value. Version 1 has no plots or run-history browser.
- About this analysis uses shared tabbed `ToolInfoContent`. A second contextual
  information dialog explains fixed-domain fill-through and base-overlap
  exclusion.
- Long preparation and permutations run outside the UI thread. Cancellation,
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

## Version 1 Acceptance

Automated tests use synthetic or temporary project fixtures and never bundle or
depend on the private ACR project. Final acceptance additionally requires a
visible end-to-end GUI reproduction of the canonical ACR Neutral Happy result:
18 anxious versus 16 non-anxious participants, retained H1/H2, a positive H1
C1/Cz/CPz cluster, and raw sign-specific p approximately `.0043`. This manual
gate validates the complete project discovery, preparation, GUI, permutation,
and export path.
