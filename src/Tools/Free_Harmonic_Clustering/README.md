# Free Harmonic Clustering Analysis

This package contains FPVS Toolbox's clean-room Free Harmonic Clustering
Analysis backend and embedded GUI. It reads original managed-project
`FullFFT Amplitude (uV)` workbooks and preserves participant x sensor x
harmonic structure through cluster-level permutation inference.

The implementation follows the method described by
[Hermann et al. (2026)](https://doi.org/10.1111/psyp.70361) and mirrors the
[public FPVS_Multiharmonic
repository](https://github.com/oliver-hermann1/FPVS_Multiharmonic) where the
available information fixes behavior. It is an independent implementation,
not a copy, and is not claimed to be numerically identical to the authors'
unpublished normalized tensors, spatial-neighbor matrix, or FieldTrip
environment.

## Supported designs

- Two canonical project groups within one condition form an independent-groups
  contrast. Whole participant tensors are relabeled while observed group sizes
  remain fixed.
- One condition versus another for the same complete participant cohort forms
  a paired contrast. An optional canonical group filter may be applied, and
  whole-participant condition differences are permuted through sign flips.
- Each run analyzes one ordered A-minus-B contrast. Separate condition runs do
  not receive an automatic correction across conditions.

## Embedded workflow

Open **Free Harmonic Clustering Analysis** from the default Quick Tools list in
the Workspace Tools sidebar. The page dynamically
reads project conditions, groups, exclusions, base and oddball frequencies,
and FullFFT availability. It does not offer local metadata or participant
overrides.

1. Choose Paired Conditions or Independent Groups and define one A-minus-B
   contrast in **1. Setup**.
2. Use the default Hermann automatic harmonic selection, or choose the highest
   fixed oddball harmonic. Both modes fill through and exclude all dynamically
   identified base-rate overlaps.
3. Select **Run Analysis** once. The frozen cohort, exclusions, harmonic
   domain, source coverage, and participant x sensor x harmonic shape appear in
   **2. Review**, then permutations continue automatically without rereading
   source workbooks.
4. When **3. Results** opens, review the **Significant** view first, then **All
   clusters**. Use **Open
   Results Folder** for the polished Excel workbook and complete provenance.

The GUI exposes the locked Hermann-compatible profile rather than advanced
method controls. Version 1 runs 10,000 assignments, uses a two-sided node-entry
alpha of `.01`, complete free-harmonic adjacency, the fixed 197-edge
FieldTrip-style BioSemi64 spatial reconstruction, and separate signed nulls.
Raw sign-specific cluster p-values are judged at `.025`; doubled p-values are
secondary two-sided presentations.

The embedded task tabs do not use page-level scrolling; result tables scroll
internally only when their rows or columns exceed the available viewport. The
Results tab shows the current session's latest run only. Plots, an all-condition
batch, a historical-run browser, and clipboard/manuscript helpers are deferred
beyond version 1.

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

The Hermann-compatible adaptive selector stops with the structured code
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

Completed bundles include the polished human-readable
`Free_Harmonic_Clustering_Results.xlsx` workbook, a manifest, cluster summary
and membership tables, the full node t map, harmonic-selection audit,
participants and source workbooks, both signed null-extrema distributions, and
compressed numerical arrays. They record the exact spectral windows,
cohort/exclusions, L2 normalization, fixed 197-edge BioSemi64 graph and hash,
random assignment hash, method versions, and input file size/timestamps.

The workbook is organized into Run Summary, Significant Clusters, All
Clusters, Cluster Membership, Harmonic Selection, Participants and Exclusions,
Methods and Provenance, Node Statistics, and Null Distribution worksheets.
Machine-readable artifacts remain beside it for reproducibility.

The tool is source-immutable. It may add a completed result folder, but it
never edits `project.json`, settings, participant metadata, ledgers, QC
decisions, or processed workbooks. Failed or cancelled work does not publish a
completed bundle.

Inference is cluster-level weak FWER for the one declared sensor x harmonic
family. A significant cluster does not make its individual sensors,
harmonics, cells, or boundaries pointwise significant. Cluster effect sizes
are descriptive, post-selection, and shape-dependent.

## Version 1 acceptance

Automated preparation, inference, export, and GUI coverage uses synthetic or
temporary managed-project fixtures. Tests must never bundle or depend on the
private ACR project.

The additional visible release gate is an end-to-end GUI reproduction of the
canonical ACR Neutral Happy comparison: 18 anxious versus 16 non-anxious
participants, retained H1/H2, a positive H1 C1/Cz/CPz cluster, and raw
sign-specific p approximately `.0043`. Version 1 is not accepted until project
discovery, preparation, GUI review, permutation inference, and export reproduce
that result.

See the [user guide](../../../docs/user/tools/free-harmonic-clustering.md) and
[methods/reporting
checklist](../../../docs/user/reference/methods-reporting-checklist.md#free-harmonic-clustering-analysis)
for interpretation and manuscript requirements.
