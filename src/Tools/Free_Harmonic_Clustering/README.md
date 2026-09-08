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
- Legacy runs analyze one ordered A-minus-B contrast. Separate legacy runs do
  not receive an automatic correction across conditions.
- Canonical two-group, two-session projects expose a prespecified
  repeated-session batch over all project conditions: groups averaged across
  complete session pairs, Visit 2 minus Visit 1 within each group, and the
  between-group difference in participant session change. One shared harmonic
  domain is frozen for the batch; global run p-values receive Holm correction
  across conditions within each family and across the full batch.

## Embedded workflow

Open **Free Harmonic Clustering Analysis** from the default Quick Tools list in
the Workspace Tools sidebar. The page dynamically
reads project conditions, groups, exclusions, base and oddball frequencies,
and FullFFT availability. It does not offer local frequency, group, session,
condition, or participant-identity overrides. Repeated batches may add
source-immutable, project-persistent FHC recording exclusions with required
audit reasons.

1. For a flat project, choose Paired Conditions or Independent Groups and
   define one A-minus-B contrast. A repeated-session project is recognized
   automatically and shows its full-batch design instead.
2. Use the default Hermann automatic harmonic selection, or choose the highest
   fixed oddball harmonic. Both modes fill through and exclude all dynamically
   identified base-rate overlaps.
3. Optionally review analysis-only recording exclusions for a repeated batch;
   each exclusion requires an audit reason, persists for later FHC batches in
   that project until changed, and never changes project QC.
4. Select **Run Free Harmonic Clustering Analysis** once.
   Preparation, permutations, multiplicity correction, and export continue in
   one worker pipeline.
5. Review the concise cluster or batch results that appear beneath Setup.
   Use **Open Results Folder** for the polished Excel workbook, all clusters,
   and complete provenance.
6. Select **View cluster maps**, or double-click a result row, to inspect the
   matching cluster or repeated-session contrast. Switch harmonics to see the
   exact member electrodes on the familiar ROI scalp layout. The map background
   shows the mean analyzed A-minus-B response with a fixed symmetric scale;
   black/white dots identify positive/negative significant-cluster members.
   Turn off the member-only filter to inspect every analyzed harmonic.

Completed bundles also include matching 600-DPI PNG and single-page PDF
harmonic panels, following Figures 7 and 10 of Hermann et al. (2026), plus
descriptive map values and captions. All retained harmonics are exported.
Linear interpolation is only for the descriptive response background;
significance and membership remain discrete. Cluster p-values apply to the
whole electrode x harmonic cluster, not its individual electrodes or slices.
Repeated-batch Holm annotations remain run-level corrections.

The GUI exposes the locked Hermann-compatible profile rather than advanced
method controls. The default runs 10,000 assignments, uses a two-sided node-entry
alpha of `.01`, complete free-harmonic adjacency, the fixed 197-edge
FieldTrip-style BioSemi64 spatial reconstruction, and separate signed nulls.
Raw sign-specific cluster p-values are judged at `.025`; doubled p-values are
secondary two-sided presentations.

The embedded workspace has no workflow tabs or page-level scrolling; the
significant-cluster table scrolls internally only when needed. It shows the
current session's latest result without printing technical run metadata in the
main GUI. Plots, a historical-run browser, and clipboard/manuscript helpers are
not part of the current page.

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
  Free Harmonic Clustering Analysis/
    project_settings.json
    <run-id>/
```

Use the `paired` subcommand with `--condition-a`, `--condition-b`, and an
optional canonical `--group` filter for repeated-condition analyses. Run
`python -m Tools.Free_Harmonic_Clustering --help` for all options.

The headless repeated-session batch uses canonical IDs and makes the change
direction explicit. Repeat `--condition` in planned order and use
`--exclude-recording RECORDING_ID=REASON` only for justified, batch-local
exclusions:

```powershell
python -m Tools.Free_Harmonic_Clustering repeated-session `
  --project-root "<managed-project-root>" `
  --condition "Neutral Angry" --condition "Angry Control" `
  --condition "Neutral Happy" --condition "Neutral Sad" `
  --group-a bc_group --group-b control_group `
  --session-a follicular_phase --session-b luteal_phase `
  --exclude-recording "participant-id__session-id=User-declared outlier"
```

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

Repeated batches use
`Free_Harmonic_Clustering_Repeated_Session_Batch.xlsx` in one additive run
directory. The workbook and companion files include run-global and both Holm
layers, every cluster/member/node/null table, complete-pair coverage and
reasoned exclusions, shared-domain provenance, derived seeds, source records,
and the fixed-order warning.

The tool is source-immutable. The GUI may update its versioned
`project_settings.json` beneath the project's FHC results parent and the tool may
add completed result folders, but it never edits `project.json`, shared project
settings, participant metadata, ledgers, QC decisions, or processed workbooks.
Failed or cancelled work does not publish a completed bundle.

Inference is cluster-level weak FWER for the one declared sensor x harmonic
family. A significant cluster does not make its individual sensors,
harmonics, cells, or boundaries pointwise significant. Cluster effect sizes
are descriptive, post-selection, and shape-dependent.

The completed legacy powered-null receipt does not validate the new
repeated-session batch, shared multi-cell harmonic selection, composite
tensors, group-by-session interaction contrast, or cross-condition Holm layer.
Repeated-session phase labels must be reported as session/phase-at-visit when
phase is aligned with fixed visit order.

## Legacy Version 1 acceptance

Automated preparation, inference, export, and GUI coverage uses synthetic or
temporary managed-project fixtures. Tests must never bundle or depend on the
private ACR project.

The additional visible release gate is an end-to-end GUI reproduction of the
canonical ACR Neutral Happy comparison: 18 anxious versus 16 non-anxious
participants, retained H1/H2, a positive H1 C1/Cz/CPz cluster, and raw
sign-specific p approximately `.0043`. Version 1 is not accepted until project
discovery, preparation, GUI result presentation, permutation inference, and
export reproduce that result.

See the [user guide](../../../docs/user/tools/free-harmonic-clustering.md) and
[methods/reporting
checklist](../../../docs/user/reference/methods-reporting-checklist.md#free-harmonic-clustering-analysis)
for interpretation and manuscript requirements.
