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

The tool reads these values dynamically. It does not provide local frequency,
group, condition, or participant overrides. Both the setup inspection and the
direct preparation API validate the same processing-owned neutral record:
project-relative source workbooks, exact FullFFT grid/resolution, base and
oddball rates, cohort/QC identity, and processing/export identity. Missing,
stale, or conflicting provenance blocks setup; restore the processed rates or
rerun post-processing. EEG preprocessing is not required merely to rebuild
this record.

The neutral record contains no standard Stats profile or selected Summed-BCA
harmonic list. Free Harmonic Clustering always performs its own Hermann
automatic or fixed-ceiling preparation from original FullFFT amplitude. A
standard profile change, or stale Stats-ready/full-audit workbook by itself,
does not alter or block this analysis. A changed FullFFT workbook, active
cohort, frequency-QC decision, processing/export identity, rate, or grid does.

## One Contrast Per Run

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

Version 1 does not run an omnibus test, group x condition interaction, or
automatic batch across conditions. A collection of separately run condition
contrasts is not automatically corrected as one larger family.

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

## Prepare, Review, Then Run

Define the comparison in **1. Setup**, then select **Prepare Analysis** in the
persistent action strip. Successful preparation unlocks and opens **2. Review
and Run**. That review shows:

- the design and A minus B direction;
- included participants, group sizes, exclusions, incomplete pairs, and final
  sample size;
- detected and retained harmonics plus the automatic z-score audit or
  fixed-domain provenance;
- the prepared data shape: participants x electrodes x harmonics; and
- sensor and source-workbook validation.

Long participant, exclusion, or selection lists are shortened in the visible
cards so the page remains readable without a page scrollbar. Hover over a
shortened value for the full list; the completed workbook also records the full
cohort and method provenance. Select **Run Permutations** from this tab to unlock
**3. Results**.

Preparation builds the numerical arrays once and reuses them for the
permutation run, avoiding a second workbook read. Condition workbooks are read
with a deduplicated selected-column plan and converted to contiguous numerical
arrays for vectorized calculation.

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

Paired analyses permute whole participant condition differences through sign
flips. Independent-group analyses shuffle whole participant labels while
preserving group sizes. Sensors and harmonics are never shuffled separately.

## Reading Results

The Results tab opens on **Significant**, which places clusters meeting the
Hermann-compatible threshold first, ordered by the raw sign-specific p-value.
Use **All clusters** for the complete current-session table. The task pages do
not use page-level scrolling; result tables scroll internally only when their
data exceed the available viewport. The primary cluster p-value is evaluated at
`.025` per direction for a two-tailed family alpha of `.05`. The doubled p-value
is included as a secondary two-sided presentation, not as a second test. A Monte
Carlo interval records uncertainty from the finite number of assignments.

A positive cluster means that the L2-normalized response is relatively stronger
for A than B over the connected electrode x harmonic cells. A negative cluster
means the reverse. Because of normalization, the test concerns response shape
and distribution, not overall response magnitude.

Inference is cluster-level and provides weak/global family-wise error control
for the one declared electrode x harmonic family when whole-participant
assignments are exchangeable. That control is conditional on the candidate
domain, adjacency, node-entry threshold, and contrast family. It does not
correct a collection of separately run contrasts, and it tends to favor
spatially or harmonically extended effects. A significant cluster does not
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

Version 1 has no result plots and no historical-run browser. The Results tab
shows the current session's latest run. Use **Open Results Folder** to review
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
