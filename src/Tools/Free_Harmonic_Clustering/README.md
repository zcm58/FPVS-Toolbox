# Free Harmonic Clustering Analysis

This package is the headless validation release of FPVS Toolbox's clean-room
Free Harmonic Clustering Analysis. It reads original managed-project
`FullFFT Amplitude (uV)` workbooks and preserves participant x sensor x
harmonic structure through cluster-level permutation inference.

The implementation follows the method described by Hermann et al. where the
publication fixes behavior, but it is not claimed to be numerically identical
to the authors' unpublished normalized tensors, spatial-neighbor matrix, or
FieldTrip environment.

## ACR design

- Anxious versus Non-Anxious within one condition is an independent-groups
  contrast. Whole participant tensors are relabeled while group sizes remain
  fixed.
- One condition versus another for the same complete participant cohort is a
  paired contrast. Whole participant condition tensors are swapped through
  sign flips.
- Each command analyzes one declared contrast. Separate ACR condition runs do
  not receive an automatic correction across conditions.

## Headless use

Validate inputs and prepare tensors without writing any result files:

```powershell
.\.venv1\Scripts\python.exe -m Tools.Free_Harmonic_Clustering independent `
  --project-root "<managed-project-root>" `
  --condition "Positive Valence" `
  --group-a anxious `
  --group-b non_anxious `
  --oddball-frequency-hz 1.2 `
  --base-frequency-hz 6 `
  --max-harmonic-hz 48 `
  --prepare-only
```

Remove `--prepare-only` to run the default 10,000 assignments and publish an
atomic result bundle below:

```text
<project>/3 - Statistical Analysis Results/
  Free Harmonic Clustering Analysis/<run-id>/
```

Use the `paired` subcommand with `--condition-a`, `--condition-b`, and an
optional canonical `--group` filter for repeated-condition analyses. Run
`python -m Tools.Free_Harmonic_Clustering --help` for all options.

The paper-faithful adaptive selector stops with the structured code
`NO_HARMONICS_SELECTED` when neither arm has a non-base oddball harmonic with
strict `z > 3.29`. The command does not substitute the Toolbox's different
Standard FPVS Screening selector or invent a fallback harmonic range.

The adaptive domain is selected from the observed arms and then held fixed for
all assignments, as described in the paper. That same-data selection is an
inferential limitation; confirmatory work should prefer a preregistered or
independently selected harmonic domain. Independent-group relabeling also
assumes participants are freely exchangeable: unmodeled matching, strata, or
family structure require a different design.

## Outputs and interpretation

Completed bundles include a manifest, cluster summary and membership tables,
the full node t map, harmonic-selection audit, participants and source
workbooks, both signed null-extrema distributions, and compressed numerical
arrays. They record the exact spectral windows, cohort/exclusions, L2
normalization, fixed BioSemi64 edges and hash, random assignment hash, method
versions, and input file size/timestamps.

Inference is cluster-level weak FWER for the one declared sensor x harmonic
family. A significant cluster does not make its individual sensors,
harmonics, cells, or boundaries pointwise significant. Cluster effect sizes
are descriptive, post-selection, and shape-dependent.

## Validation evidence

The initial read-only ACR audit prepared 235 unique workbooks across all nine
conditions in 181 seconds. The exact strict selector succeeded for Happy
Caucasian, Negative Valence, Neutral Fear, Neutral Happy, Neutral Sad, and
Positive Valence; the other three conditions returned
`NO_HARMONICS_SELECTED`.

A full in-memory Positive Valence validation used 18 Anxious and 16
Non-Anxious participants, read 736 of 5,771 FullFFT columns per workbook,
retained seven non-base harmonics through 9.6 Hz, and completed 10,000 PCG64
assignments in 33.7 seconds. It produced four observed singleton clusters and
no cluster-level rejection. No ACR result files were published; this is
implementation-validation evidence, not a reported scientific analysis.

The release passed 59 focused backend tests, 71 project-I/O tests, and the
repository-wide gate (1,493 passed, 2 skipped), including fixed-domain paired
and unequal-group Gaussian-null calibration fixtures.
