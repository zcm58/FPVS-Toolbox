# Free Harmonic Clustering Analysis

Free Harmonic Clustering Analysis is a project-bound analysis for
comparing how an FPVS oddball response is distributed across both electrodes
and harmonics. Unlike a summed-harmonic analysis, it retains each participant's
electrode x harmonic array and uses connected cluster mass for permutation
inference.

The implementation is an independent, clean-room adaptation of the method
described by [Hermann et al. (2026)](https://doi.org/10.1111/psyp.70361). It
follows the paper and public implementation where the available information is
sufficient, but it is not a copy and is not claimed to be numerically identical
to the authors' unpublished normalized arrays, software state, or adjacency
matrix.

## Before You Start

Choose the abbreviated **Free Harmonic Clustering** entry in the default Quick
Tools list to open **Free Harmonic Clustering Analysis**. The active project
must contain:

- valid base and oddball frequency metadata;
- current neutral FullFFT provenance in `project.json` that matches the
  processed workbooks, active cohort/QC state, processing export, and current
  Project Settings;
- canonical conditions, participants, and, for an independent-groups run,
  canonical group assignments;
- processed condition workbooks with compatible `FullFFT Amplitude (uV)`
  sheets; and
- the complete supported BioSemi64 sensor set on one shared FullFFT frequency
  grid.

Repeated-session v2.2 projects are recognized automatically. The repeated
workflow requires exactly two stable groups and two ordered sessions. It keeps
canonical participant, recording, group, session, and visit identity throughout
preparation, so two visits are paired and are never treated as independent
participants.

The tool reads these values dynamically. It does not provide local frequency,
group, condition, or participant overrides. Both the setup inspection and the
direct preparation API validate the same processing-owned neutral record:
project-relative source workbooks, exact FullFFT grid/resolution, base and
oddball rates, cohort/QC identity, and processing/export identity. Missing,
stale, or conflicting provenance opens the shared **Post-processing Required**
dialog. Choose **Run Post-processing** to refresh the downstream files from the
existing processed EEG data; EEG preprocessing is not rerun. After the neutral
record is current, the FHC setup reloads automatically.

The neutral record contains no standard Stats profile or selected Summed-BCA
harmonic list. Free Harmonic Clustering always performs its own Hermann
automatic or fixed-ceiling preparation from original FullFFT amplitude. A
standard profile change, or stale Stats-ready/full-audit workbook by itself,
does not alter or block this analysis. A changed FullFFT workbook, active
cohort, frequency-QC decision, processing/export identity, rate, or grid does.

## Available Workflows

### Legacy One-Contrast Workflow

Choose one ordered two-level contrast:

- **Paired Conditions:** Condition A minus Condition B for the same complete
  participants. You may restrict the cohort to one canonical project group; the
  default uses all eligible participants.
- **Independent Groups:** Group A minus Group B for one condition. Whole
  participant arrays are relabeled while the observed group sizes are
  preserved.

The direction is always displayed as A minus B. Positive clusters indicate
A > B and negative clusters indicate A < B. Set A and B directly in Setup;
select them in the opposite order to reverse the contrast.

Legacy one-contrast mode does not run an omnibus test, group x condition
interaction, or automatic batch across conditions. A collection of separately
run legacy contrasts is not automatically corrected as one larger family.

### Repeated-Session Full Batch

For a repeated-session project, the GUI replaces the legacy contrast selector
with one prespecified full batch. Every project condition is analyzed in four
participant-level contrast families:

1. **Groups averaged over sessions:** average the two session SNR tensors within
   each complete participant, L2-normalize that participant mean once, then
   compare Group A minus Group B by whole-participant label permutation.
2. **Session/phase-at-visit within Group A:** L2-normalize each session tensor,
   calculate Visit 2 minus Visit 1 within participant, and use whole-participant
   sign flips.
3. **Session/phase-at-visit within Group B:** use the same paired calculation
   within the second group.
4. **Group difference in session change:** compare the participant-level Visit
   2 minus Visit 1 normalized-session difference tensors between groups. This
   is the direct group-by-session interaction contrast; the difference tensor
   is not normalized again.

All four families use complete, phase-balanced pairs for the relevant
condition. Missing sessions remain visible in the cohort audit and are never
imputed or zero-filled. GUI recording exclusions persist for this project's
Free Harmonic Clustering batches until changed. Reasons are optional; blank
reasons appear as `No reason provided` in the audit. These exclusions do not
change project QC or any source file. CLI exclusions apply only to that batch.

The session direction is later visit minus earlier visit. If every participant
completed sessions in the same order—as in the Birth Control project—phase is
perfectly confounded with visit order, elapsed time, repetition, and
habituation. Results must therefore be called **session/phase-at-visit** effects,
not isolated menstrual-phase effects.

Each condition-level result retains maximum-cluster correction across its
electrode x harmonic nodes. The batch then applies Holm correction to the
global two-sided run p-values across conditions within each of the four
prespecified contrast families. It also reports a conservative Holm adjustment
across every condition x family test in the full batch. These are run-level
corrections; raw cluster p-values are not relabelled as cross-condition-adjusted
cluster p-values.

## Selecting Harmonics

The default **Hermann automatic selection** profile calculates grand-spectrum
z-scores for both contrast arms. It detects oddball harmonics using strict
`z > 3.29`, takes the highest detected harmonic in either arm, and fills through
that upper harmonic. If neither arm has an eligible detection, preparation
stops with a no-harmonics-selected result instead of inventing a fallback.

The optional **Fixed harmonic list** control asks for the highest oddball
harmonic to include. It then fills through from the first eligible oddball
harmonic to that upper end. It is not a selector for one isolated harmonic.

For both modes, candidate frequencies are derived from the project's oddball
frequency, base frequency, FullFFT grid, and available upper frequency. Every
oddball harmonic that coincides with a base-rate harmonic is excluded. No
particular base rate, oddball rate, or upper frequency is hard-coded.

The repeated-session batch derives and freezes one shared harmonic domain
across all included groups, sessions, conditions, and contrast families. In
automatic mode it computes selector z-scores separately in every declared
group x session x condition cell, takes the highest strict detection in any
cell, and fills through once for the whole batch. This keeps the candidate node
family comparable throughout the batch. Legacy one-contrast automatic
selection remains unchanged.

## Run the Analysis

For a legacy project, define one comparison and select **Run Free Harmonic
Clustering Analysis** once.
For a repeated-session project, review the detected groups, ordered sessions,
all-condition plan, and optional analysis-only recording exclusions, then
select **Run Free Harmonic Clustering Analysis**. The tool prepares the data
and continues through all permutations and export without another confirmation.
A concise result appears beneath the setup controls when the run completes.

## Explore Cluster Maps

Select **View cluster maps**, or double-click a results row, to open the
**Cluster maps** tab. A batch row opens its condition and contrast family;
a cluster row selects that cluster. Choose a harmonic by its frequency and
oddball-frequency multiple, or use the previous/next buttons. The member-only
filter shows harmonics with members of the selected cluster (or any significant
cluster). Turn it off to see every analyzed harmonic, including maps with no
significant-cluster members. Electrode labels can be shown for orientation.

The presentation follows Figures 7 and 10 of
[Hermann et al. (2026)](https://doi.org/10.1111/psyp.70361):

- The background shows mean analyzed arm A minus mean analyzed arm B. For
  ordinary contrasts these are L2-normalized SNR responses; repeated-session
  contrasts preserve the analysis's session-average or session-change
  definition. The color bar is dimensionless, not microvolts or t values.
- Every harmonic within a contrast uses the same symmetric, zero-centered
  color scale, including when you select an individual cluster.
- Black dots mark positive significant-cluster members and white dots mark
  negative significant-cluster members at that exact harmonic. The contrast
  labels identify which condition or group is higher.
- The scalp geometry is shared with the Toolbox ROI selector. The smooth
  background is a linear interpolation of response differences inside the
  electrode layout; it is descriptive and does not change the analysis.

The p-value belongs to the entire electrode x harmonic cluster. A marked
electrode, a colored area, or a displayed harmonic does not carry its own
significance claim. Separate patches within one map can belong to the same
cluster through connections at other harmonics. Repeated-session Holm values
are shown separately because they correct global run p-values rather than
individual clusters. These maps illustrate scalp measurements; they do not
localize brain sources.

Use **Open Results Folder** to find the exported harmonic panels. Matching
600-DPI PNG and single-page PDF figures show every retained harmonic with
shared color limits. Larger domains are split across numbered figures.
The map metadata records descriptive values, membership, and captions so
the artwork can be checked against the result. This is an independent
implementation using the Toolbox layout, rather than an exact reproduction
of the paper's FieldTrip rendering.

The viewer is read-only. Switching harmonics does not rerun statistics, edit
ROIs, or change saved project settings. Changing the analysis setup or active
project clears the current maps along with the results table.

The main workspace intentionally omits dense preparation and technical run
summaries. The completed workbook records the full cohort, exclusions,
incomplete pairs, harmonic-selection audit, prepared data shape, source
validation, assignment count, threshold, seed, and other method provenance.

Preparation builds the numerical arrays once and reuses them for the
permutation run, avoiding a second workbook read. Condition workbooks are read
with a deduplicated selected-column plan and converted to contiguous numerical
arrays for vectorized calculation.

The same repeated batch is available headlessly. Session A is the positive
side of the change, so the Birth Control direction is follicular Visit 2 minus
luteal Visit 1. Repeat `--condition` in the planned order; any
`--exclude-recording` value must include a nonempty `RECORDING_ID=REASON`:

```powershell
python -m Tools.Free_Harmonic_Clustering repeated-session `
  --project-root "<managed-project-root>" `
  --condition "Neutral Angry" --condition "Angry Control" `
  --condition "Neutral Happy" --condition "Neutral Sad" `
  --group-a bc_group --group-b control_group `
  --session-a follicular_phase --session-b luteal_phase `
  --exclude-recording "participant-id__session-id=User-declared outlier"
```

## Hermann-Compatible Statistical Profile

The first release exposes no advanced method controls. It uses:

- target SNR divided by the mean surrounding amplitude within +/-0.1 Hz,
  excluding the target and its immediately adjacent FFT bins;
- L2 normalization of each participant and contrast arm across the full
  electrode x harmonic array;
- a two-sided node-entry alpha of `.01`;
- signed summed-t cluster mass;
- complete free-harmonic adjacency at each electrode;
- a fixed, versioned 197-edge FieldTrip-style BioSemi64 spatial graph;
- 10,000 whole-participant assignments by default; and
- separate positive and negative extreme-cluster null distributions.

The 197-edge spatial graph is an independent clean-room reconstruction of a
FieldTrip-style BioSemi64 neighborhood graph. It is not the authors' adjacency
matrix. The exact edge list, version, and hash are retained with each run.

Paired analyses permute whole participant differences through sign flips.
Independent-group analyses shuffle whole participant labels while preserving
group sizes. This applies to the corresponding repeated-session families as
well as legacy contrasts. Sensors and harmonics are never shuffled separately.

## Reading Results

For a legacy contrast, the main workspace reports whether significant clusters
were found and shows only those clusters, ordered by raw sign-specific p-value.
For a repeated-session batch, it shows one compact row per condition x contrast
family with the number of significant clusters, global run p-value,
within-family Holm p-value, and full-batch Holm p-value. The page does not use a
page-level scroll area; result tables scroll internally when needed. Use
**Open Results Folder** for complete cluster tables and technical run details.
The primary raw cluster p-value is evaluated at `.025` per direction for a
two-tailed family alpha of `.05`. The doubled p-value is included as a
secondary two-sided presentation, not as a second test. A Monte Carlo interval
records uncertainty from the finite number of assignments.

A positive cluster means that the L2-normalized response is relatively stronger
for A than B over the connected electrode x harmonic cells. A negative cluster
means the reverse. Because of normalization, the test concerns response shape
and distribution, not overall response magnitude.

Inference is cluster-level and provides weak/global family-wise error control
for the one declared electrode x harmonic family when whole-participant
assignments are exchangeable. That control is conditional on the candidate
domain, adjacency, node-entry threshold, and contrast family. It does not
correct a collection of separately run legacy contrasts. The repeated-session
batch's Holm layers address its prespecified run-level families, not arbitrary
analyses outside that batch. Cluster inference tends to favor spatially or
harmonically extended effects. A significant cluster does not
make any individual electrode, harmonic, cell, or boundary pointwise
significant. Cluster-average effect sizes are descriptive, post-selection, and
shape-dependent. Higher harmonics can reflect a more complex evoked waveform,
but one harmonic should not be assigned to one neural process in isolation.

Automatic mode chooses its ceiling from the observed arms and holds that
ceiling fixed during permutations. The cluster permutation therefore controls
the conditional family defined by that prepared domain; this fact alone does
not prove unconditional error control for the combined adaptive-selection and
permutation procedure.

The Toolbox separates software regression testing from formal statistical
calibration. Routine automated testing repeats 24 seeded null analyses with 199
assignments each and permits at most five global rejections. This small envelope
is only a gross-error smoke check.

A separate powered protocol is frozen for 4,000 null replicates: 2,000 paired
and 2,000 independent, divided among four 500-replicate regimes per design,
using the production 10,000 assignments. Its design-level and regime-level
exact-binomial guardrails were fixed before execution. The reviewed run passed
every guardrail: independent groups rejected in 111/2,000 replicates (`.0555`;
one-sided 97.5% exact upper bound `.06645`) and paired conditions in 91/2,000
(`.0455`; upper bound `.05557`). All eight 500-replicate regime cells passed;
the largest was 31/500 (`.062`; one-sided 95% upper bound `.08276`). There were
no errors or no-selection replicates, and the deterministic execution check
passed.

This result is bounded empirical evidence for the frozen simulated regimes,
not mathematical proof of universal error control, a power analysis, or
evidence that any real-data result is true. Automatic-mode cluster inference
remains conditional on the candidate domain, adjacency, node-entry threshold,
contrast family, and valid whole-participant exchangeability. Do not report the
24 x 199 smoke as calibrated evidence or generalize the powered result beyond
its documented regimes.

The powered receipt covers only the frozen legacy paired-condition and
independent-group workflows. It does **not** validate the repeated-session
batch, its shared multi-cell harmonic selector, composite participant tensors,
interaction contrast, or cross-condition Holm layer. The repeated workflow
reuses the locked numerical cluster-permutation core, but that is a software
inheritance statement rather than new calibration evidence.

The workspace has no result plots or historical-run browser. It
shows the current session's latest result. Use **Open Results Folder** to review
earlier additive runs.

## Outputs

A successful run creates a new, non-overwriting directory below:

```text
<project>/3 - Statistical Analysis Results/
  Free Harmonic Clustering Analysis/<run-id>/
```

Its primary human-readable file is
`Free_Harmonic_Clustering_Results.xlsx`, organized into these worksheets:

1. Run Summary
2. Significant Clusters
3. All Clusters
4. Cluster Membership
5. Harmonic Selection
6. Participants and Exclusions
7. Methods and Provenance
8. Node Statistics
9. Null Distribution

A repeated-session batch instead writes
`Free_Harmonic_Clustering_Repeated_Session_Batch.xlsx` in one additive batch
directory. It includes the batch/run summary, both Holm layers, all cluster and
membership rows, the complete-pair cohort and exclusion audit, shared harmonic
selection, methods/provenance, node statistics, signed null distributions, and
source-workbook audit. Machine-readable per-run tables and compressed arrays
remain beside it.

The workbook uses frozen headers, filters, readable widths, consistent numeric
precision, and restrained significance highlighting. Machine-readable CSV,
compressed-array, and manifest artifacts remain beside it for reproducibility.

The tool is source-immutable: it never modifies `project.json`, project
settings, participant metadata, QC ledgers or decisions, or processed
workbooks. Failed or cancelled work does not publish a completed result bundle.

## Reporting

Report the ordered contrast and design, cohort and exclusions, exact harmonic
domain and its selection provenance, L2 normalization, graph version/hash,
node-entry threshold, assignment count and seed, cluster mass, membership, raw
sign-specific p-value, Monte Carlo interval, doubled p-value when shown, and
descriptive effect size. Also retain the neutral FullFFT provenance method and
source/cohort/QC/processing fingerprints exported with the run. Retain the
complete result bundle with the analysis record.

For a repeated-session batch, additionally report the two ordered canonical
sessions and visit indices, the fixed-order confounding, complete-pair N by
group/condition, all analysis-specific recording exclusions and reasons, the
four tensor constructions, the shared batch harmonic-domain fingerprint, and
the global run p-value with both within-family and all-batch Holm values. Do not
describe a cluster's raw p-value as Holm-adjusted, and do not interpret the FHC
result as a test of total Raw BCA magnitude.

See the [Free Harmonic Clustering reporting
checklist](../reference/methods-reporting-checklist.md#free-harmonic-clustering-analysis)
for the full manuscript and provenance checklist.

## References

- Hermann, O., Wong Hiu Ching, W., & Stothart, G. (2026).
  [Preserving harmonic structure in FPVS-oddball: A two-dimensional
  cluster-based permutation approach](https://doi.org/10.1111/psyp.70361).
  *Psychophysiology, 63*(7), e70361.
- [Hermann et al. public `FPVS_Multiharmonic`
  repository](https://github.com/oliver-hermann1/FPVS_Multiharmonic).
- [FPVS Toolbox methods and reporting
  checklist](../reference/methods-reporting-checklist.md#free-harmonic-clustering-analysis).
