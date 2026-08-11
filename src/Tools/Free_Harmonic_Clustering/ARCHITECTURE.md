# Free Harmonic Clustering Analysis Architecture

## Boundary

This is a sibling analysis tool under `src/Tools`, separate from Standard FPVS
Screening. The headless prototype has no GUI or worker dependency and does not
change preprocessing, workbook schemas, harmonic-selection caches, or project
metadata.

## Data Flow

```text
managed project root
  -> canonical dataset index and QC/cohort freeze
  -> common FullFFT header and selected target/noise-column plan
  -> one streamed XML read per participant-condition workbook
  -> raw amplitude tensor and paper SNR/z preparation
  -> retained non-base harmonic domain and participant L2 normalization
  -> paired sign flips or independent group-label permutations
  -> free-harmonic/spatial connected components and cluster-mass inference
  -> atomic project-local manifest, tabular results, and compressed arrays
```

Array order is participant x sensor x harmonic at the public numerical
boundary. Flattening is sensor-major (`sensor * H + harmonic`) so the combined
graph is `spatial_adjacency kron I_H OR I_S kron complete_harmonic_adjacency`.

## Modules

- `models.py`: immutable requests, method specifications, prepared tensors,
  cluster results, and export receipts.
- `preparation.py`: exact frequency-window planning, grand-spectrum z selection,
  participant SNR, and L2 normalization.
- `inputs.py`: canonical managed-project discovery, cohort/QC enforcement, and
  selected-column FullFFT ingestion.
- `analysis.py`: versioned BioSemi64 adjacency, node t statistics, connected
  components, permutation nulls, cluster p-values, and cluster-average effects.
- `api.py`: stable orchestration boundary.
- `exports.py`: contained, atomic, provenance-rich result publication.
- `__main__.py`: headless command entry point; no separate scientific behavior.

## ACR Modes

- `independent_groups`: one ACR condition, canonical Anxious minus Non-Anxious
  group assignment, whole-participant label permutation, pooled independent t.
- `paired_conditions`: two ACR conditions in the same complete participant
  cohort, optional single canonical group filter, whole-participant sign flip.

Each run owns one sensor x harmonic family. A collection of separate ACR
condition runs is not automatically corrected across conditions.

## Method Identity

The initial method version is
`hermann_free_harmonic_clustering_cleanroom_v1`. It fixes and exports:

- +/-0.1-Hz physical noise windows;
- target and immediate-adjacent-bin exclusion;
- sample SD (`ddof=1`) for harmonic-selector z;
- `z > 3.29` and fill-through-highest non-base oddball harmonic;
- participant/arm L2 normalization;
- two-sided cluster-entry alpha `.01`;
- complete harmonic adjacency and versioned BioSemi64 spatial adjacency;
- summed signed t mass, separate positive/negative nulls, 10,000 default
  assignments, strict FieldTrip-compatible Monte Carlo comparison with `+1`,
  and `.025` final alpha per direction.

The manifest labels the implementation paper-faithful but not numerically
author-validated until unpublished reference tensors, adjacency, and outputs
become available.

## Output

Default runs publish beneath:

```text
<project>/3 - Statistical Analysis Results/
  Free Harmonic Clustering Analysis/<run-id>/
```

The output is additive, never overwrites a completed run, uses project-relative
source paths, and writes its completion manifest last before atomically
publishing the staged directory.

