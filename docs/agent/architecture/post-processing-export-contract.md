# Post-Processing Export Contract

This page documents the current post-processing and Excel export behavior before direct callers are migrated away from historical package paths. Refactors must preserve these outputs exactly unless a future task explicitly changes the processing pipeline.

## Entry Contract

Active post-export adapter imports should use `Main_App.exports.post_export_adapter`.

`post_process(app, condition_labels_present)` expects an app-like object with:

- `preprocessed_data`: mapping of condition label to MNE `Epochs` or `Evoked` objects.
- `save_folder_path.get()`: output root folder.
- `data_paths`: source data paths used for PID and event lookup.
- `settings`: `SettingsManager`-like object or dict for analysis settings.
- `log(message)`: logging callback.

The function logs start/end status, skips conditions without data, and logs a warning if no Excel files are saved.

## Canonical Harmonic Selection And Freshness

Processing-end harmonic selection produces one immutable scientific result for
the project. Its metadata distinguishes the evaluated domain, strict local-Z
detections, the exact harmonics included in Summed BCA, base-rate-overlap
exclusions, stopping reason, electrode mask, participant/group/condition
coverage, pooling-cell Ns and weights, method ID/version, and source-workbook
fingerprints. A deterministic `selection_fingerprint` hashes those scientific
inputs while excluding transient cache timestamps and workflow state.

Every standard Summed-BCA consumer must use the exact canonical included BCA
columns. A report, map, Stats-ready export, or full-audit export must not infer
significance again, fill through a different cutoff, or choose a condition-,
group-, ROI-, or participant-specific list. The compact
`Quality Check/Harmonic_Selection_Summary.xlsx` workbook and the durable
selection metadata under `tools.processing.harmonic_selection` in
`project.json` remain the audit source for detected versus included harmonics.

Managed multi-group selection and Stats-ready export carry the stable
manifest `group_id` separately from the human-readable `group_label`.
Participant-to-group assignment, balanced pooling, cache identity, and
inference use the ID; labels are presentation metadata and duplicate labels do
not collapse two canonical groups.

Managed projects track selection-derived canonical artifacts under
`tools.post_processing.artifact_freshness` in `project.json`. Each record has a
project-relative path, `current`, `stale`, or `failed` status, the fingerprint
from which it was built, and the currently required fingerprint. The tracked
derivatives are:

- `3 - Statistical Analysis Results/Stats_Ready_Summed_BCA.xlsx`;
- `3 - Statistical Analysis Results/Analysis_Ready_Summed_BCA_Full_Audit.xlsx`;
- `6 - Source Localization/L2-MNE Hauk Source PSD Beta/`; and
- `6 - Source Localization/eLORETA Hauk Source PSD Beta/`.

Accepting the same fingerprint leaves current outputs intact. Accepting a
different fingerprint first marks all four derivatives stale, then resumes the
normal post-processing pipeline after harmonic selection. That resume reads
the immutable processed workbooks and their existing BCA columns; it never
loads raw EEG, filters, epochs, recomputes FFTs, or rewrites participant-
condition workbooks. The source-map rebuild reuses durable source-ready time-
domain derivatives rather than raw EEG or participant FFT generation. Before
replacement, an existing canonical file or directory is
moved beneath project-local `.fpvs_processing/stale_artifacts/`. Successful
publication marks the replacement current. A failed publication removes a
partial replacement, restores the preceding artifact, and leaves its registry
record failed/stale for the new fingerprint instead of presenting the old file
as current.

Original FullFFT sheets are upstream source artifacts, not Summed-BCA
derivatives. `Main_App.processing.full_fft_provenance` records their separate
neutral identity under `tools.processing.full_fft_provenance`: project-relative
source workbooks, base/oddball rates, the exact project frequency-protocol
fingerprint, exact grid and resolution, active cohort and frequency-QC state,
processing-ledger/export identity, the complete
canonical BioSemi64 geometry identity, and independent fingerprints. The
geometry payload includes montage and geometry versions, coordinate and scalp-
set fingerprints, mapping profile, retained scalp channels, and a composite
fingerprint. The full post-processing run writes this record only after
frequency-domain QC is accepted and marked current, before harmonic selection
and all of its standard derivatives. This ordering keeps valid FullFFT inputs
available to Free Harmonic Clustering even if selection or a sibling export
later fails. A harmonic-only rebuild
does not rewrite it because neither the FullFFT sources nor their cohort
changed. Stale standard Summed-BCA derivatives therefore do not block Free
Harmonic Clustering; stale FullFFT, cohort/QC, rate, grid, or processing-export
provenance does.

The current neutral FullFFT provenance schema is v3. Loading or writing it
requires the rates and fingerprint to match the managed project's canonical
frequency protocol. A protocol change makes the record explicitly stale and
requires post-processing; no application-wide 6/1.2 fallback may be stamped as
managed provenance.

Every active FullFFT workbook must match one completed processing-ledger entry
with the project geometry identity and the expected retained channel count.
Missing pre-QC-15 geometry, `standard_1005` legacy identity, an unknown
coordinate definition, or mixed retained/geometry fingerprints blocks creation
or reuse of neutral FullFFT provenance. Geometry staleness requires EEG
reprocessing before post-processing; a selection-only rebuild cannot repair
it. Existing legacy files remain audit artifacts and must not be silently
relabeled or pooled with canonical BioSemi64 outputs.

## Source-Ready Time-Domain Sibling Export

The Hauk source-PSD features do not change this Excel adapter or any workbook
formula. After a successful Excel export, the process runner may pass the same
resident condition Epochs to the GUI-neutral source time-domain derivative
writer. That writer averages repetitions in signed volts, keeps EEG only, and
atomically writes Raw FIF/provenance under the active project root at
`6 - Source Localization/Source-Ready Time Domain v1/`.
Artifact pairs use
`<condition label>/[<group>/]<participant>_<condition_id>_avg_raw.fif` and a
sibling `_avg_raw.json`; participant commit manifests use
`manifests/[<group>/]<participant>.json` and are published last.

The source-ready writer requires the processing-owned canonical geometry
payload, verifies that the averaged Raw contains exactly its retained scalp
set, and writes that payload into every JSON sidecar and participant commit
manifest. Missing, stale, or mismatched geometry fails publication; the writer
does not infer a montage from channel names at export time.

Downstream source-map orchestration may mark a completed participant as
source-ineligible when any canonical condition is missing or the processing
ledger explicitly records an incomplete source derivative. That omission is
complete-case across all source conditions and must be reported separately
from general project/QC exclusions. The retained manifest set remains strict;
missing or corrupt artifacts recorded as complete are not skipped.

The current L2-MNE cortical and eLORETA volume source-PSD exporters consume the
same retained FIF/cohort/harmonic/bin contract and apply the same FPVS
neighboring-bin z-score algorithm. They remain independent numerical
consumers: eLORETA applies its own volume inverse and computes its own source
power, participant z-score, cache, and volume-cluster arrays rather than reusing
L2-MNE values. Normal manual and post-processing rebuilds target both methods.
Neither current exporter reads FullFFT amplitude workbooks or uses them as a
fallback; legacy amplitude-derived manifests remain importable only under
their existing method identities.

Those project-source exporters and the legacy LORETA Stats-ready workbook are
currently participant-keyed. For canonical repeated-session projects, the
post-processing worker reports them as successful, non-applicable skips rather
than passing recording-keyed ledger/index data into an overwriting shape.
Skipping occurs before artifact replacement, so existing files and
recording-aware source-ready derivatives are not deleted or relabeled as
current. The recording-aware full-audit workbook remains the downstream Stats
input. Single-session publication and freshness behavior is unchanged.

This is a sibling generated output, not an alternate `post_process()` entry
point. It must reuse the already-validated exact `55_onbin` crop metadata and
must not calculate FFT amplitudes, neighboring-bin metrics, source estimates,
or modify the existing Excel output paths/sheets.

## Full-Audit Analysis-Ready Workbook

After processing-end QC and harmonic selection are accepted, the project-wide
post-processing worker writes the additive workbook
`3 - Statistical Analysis Results/Analysis_Ready_Summed_BCA_Full_Audit.xlsx`.
`Main_App.exports.analysis_ready_workbook` owns this export. It runs once per
completed project processing run in the existing background worker and shared
run-scoped XLSX-read cache.

This workbook is deliberately distinct from the filtered
`Stats_Ready_Summed_BCA.xlsx` compatibility artifact. It uses the canonical
QC-20 released recording-condition matrix and the QC-21 frozen ROI/scalp
snapshot. Direct callers must present the current final-release receipt; a
saved Quality Check workbook cannot bypass that gate. Only current validated
workbooks enter numerical tables, while reviewed exclusions and explicitly
accounted no-output cells remain visible in coverage/audit fields. The export
must never recompute harmonics: accepted processing-time metadata bound to the
same final-release receipt is the only selection source.

The primary `ROI Long` sheet provides one observed participant x condition x
configured-ROI row with raw Summed BCA, RMS-normalized BCA, signed-mean-
normalized BCA, canonical group label, and concise QC fields. Supporting wide,
electrode-level, whole-scalp, harmonic-scale, QC, ROI-definition, ROI-coverage,
and harmonic-selection sheets make the aggregation auditable without adding
source paths or file hashes to the statistical table. ROI Coverage records the
expected, observed, excluded, successfully interpolated, and used electrode
sets and counts for each released cell.

RMS-normalized BCA follows the topographic normalization order described by
Dzhelyova et al. (2017) and McCarthy and Wood (1985). For every participant x
condition x selected harmonic, each electrode BCA is divided by the scalp
vector length `sqrt(sum(electrode_bca**2))`; the normalized electrode values
are then summed across harmonics and finally averaged within ROI. The published
FPVS paper calls this quantity RMS, but the stated formula is root-sum-square,
not conventional `sqrt(mean(square))`; electrode count is therefore not part
of the denominator. `RMS Harmonic Scales` records every harmonic-specific
denominator. `Whole Scalp Values` retains a clearly labeled post-sum RMS for
description only; it is not used for normalization. Signed-mean normalization
remains post-summation: each raw electrode harmonic sum is divided by the
whole-scalp signed mean before ROI averaging.

A primary raw ROI value requires every unique member of its frozen configured
set and every selected-harmonic value. A reviewed exclusion of one member makes
only that recording-condition-ROI value blank; successfully interpolated
members remain present and are reported. Any unavailable member of the frozen
whole-scalp set makes every normalized ROI derivative for that recording-
condition blank. Duplicate/missing source rows and nonfinite computable values
are technical failures rather than partial sums. The writer publishes through
a same-directory temporary workbook and atomic replacement so a failed rebuild
cannot replace a prior complete XLSX file.

## Project Protocol And Spectral Eligibility

Current post-processing requires the immutable, ready project
`frequency_protocol` in the run-settings snapshot. It does not read an
application oddball-rate default or BCA ceiling. The protocol supplies the
exact presentation rate, oddball recurrence/rate, expected analyzed oddball
cycles, and marker identity. Missing, incomplete, or inconsistent protocol
evidence is a processing failure.

`Main_App.processing.spectral_eligibility.resolve_spectral_eligibility` is the
sole current technical-domain owner. For each realized FFT input it combines
the exact protocol and grid with successfully applied nominal high-pass and
low-pass edges, Nyquist, and the effective notch mask. The resolver enumerates
project harmonics through filter/Nyquist support and marks standard metrics
eligible only when the target and all required QC-14 +/-10-bin candidates are
inside the applied passband, above DC, strictly below Nyquist, and outside
effective notch support. The complete one-sided `FullFFT Amplitude (uV)` stays
available for audit; FullFFT column existence never grants standard-analysis
eligibility.

A notch remains applied when it intersects a project harmonic. A directly
notched target is audit-only, while a notch in a required noise bin leaves the
target amplitude as audit evidence but makes BCA, SNR, and local z unavailable.
These frequency holes do not exclude the recording-condition. The workbook
records every decision in `Spectral Eligibility` and every per-channel metric
status in `Spectral Metric QC`, including the exact protocol/filter/grid
identity and method fingerprints.

Managed SNR Plot Generator contexts rehydrate and intersect this technical
eligibility across the provenance-allowed workbooks. They annotate only
eligible non-presentation harmonics, keep that domain separate from the Stats
profile's selected list, and clamp the requested display range to the observed
FullSNR grid. Free Harmonic Clustering remains selection-independent: it reads
original FullFFT values under neutral provenance while using the project rates
only for frequency identity.

## PID And Output Naming

PID resolution order:

1. `app.pid_for_group` when present.
2. First path in `app.data_paths`, using `P\d+`, `Sub\d+`, or `S\d+` if present.
3. Filename stem with common EEG suffixes stripped.
4. `UnknownPID`.

For advanced per-participant output, when `app.group_name_for_output == condition_label`, output is:

- folder: sanitized recipe name;
- filename: `{pid}_{sanitized_recipe_name}.xlsx`.

For the single-file/current app path, output is:

- folder: sanitized condition label;
- filename: `{pid}_{sanitized_condition_label}_Results.xlsx`.

Folders are created under `save_folder_path.get()`. If subfolder creation fails, the workbook is written to the parent folder.

## Metrics And Sheets

For every valid data object:

- Pick EEG channels, excluding bad channels for non-evoked objects.
- Real MNE Epochs/Evoked objects may select those same ordered EEG indices
  directly from the resident object. Custom MNE-like objects and empty
  selections retain the established `copy().pick(...)` path.
- Average epochs across repetitions when the object is `Epochs`.
- Convert averaged data to microvolts before FFT and SNR metrics.
- Use 64-channel default electrode ordering only when the channel set matches `DEFAULT_ELECTRODE_NAMES_64`.
- Skip objects with mismatched channel count or order after the first valid object.

Workbook sheets and column behavior must remain:

- `FFT Amplitude (uV)`
- `SNR`
- `Z Score`
- `BCA (uV)`
- `FullSNR`, interpolated from 0.5 Hz to the applied low-pass/Nyquist support in 0.01 Hz steps when full-spectrum SNR is available.
- `FFT and neighbors`, only when neighbor rows are non-empty.
- `Spectral Eligibility`, one deterministic availability row per filter-reachable project harmonic.
- `Spectral Metric QC`, per-channel BCA/SNR/local-z availability and reason codes.

All metric sheets insert `Electrode` as the first column. Target-frequency columns are formatted as `{frequency:.4f}_Hz`.

For the normal one-object condition export, FullSNR calculation may retain
only the bins needed by the exported interpolation grid plus the unchanged
right-hand noise window. The retained FullSNR values and interpolated output
must be byte-identical to calculating the complete Nyquist range. Multi-object
conditions retain complete-spectrum accumulation because their frequency grids
can differ while their FFT matrix shapes match.

## FFT Neighbor Export

The `FFT and neighbors` sheet uses these columns in this exact order:

`file_name`, `condition_label`, `condition_id`, `repetition_index`, `channel_or_roi`, `target`, `fs`, `N`, `T_sec`, `df_hz`, `k0`, `f_bin_hz`, `crop_mode`, `n55`, `first55_samp`, `last55_samp`, `N_step`, `N_mod_step`, `fallback_reason`, `amp_m11` through `amp_m1`, `amp_p1` through `amp_p11`, `warning`.

The target label uses the project oddball rate, for example `1.2Hz` or
`0.3Hz`. Neighbor amplitudes are exported for +/-11 FFT bins around the target
bin, excluding the center bin. Out-of-range neighbor bins are `NaN` and set a
warning string.

`build_fft_neighbors_rows(...)` returns one row per electrode/channel. It resolves `k0` by the exact target-bin formula, records `fs`, `N`, `T_sec`, `df_hz`, and crop metadata, and raises if the target frequency is not exactly on an FFT bin. It must not fall back to the nearest frequency bin. `crop_mode` must be `55_onbin` and `N_step` must be present; fixed-epoch FFT fallback is not valid for normal post-export.

`write_results_workbook(...)` writes each provided metric DataFrame to its existing sheet name with no index column, freezes the header row, center-aligns cells vertically and horizontally, and sets each column width from the maximum header/data string length plus four characters. The optional `FFT and neighbors` sheet is written only when the neighbor DataFrame is present and non-empty.

Metric sheets whose first column is the all-string `Electrode` column and
whose remaining columns are finite native-float64 values may let pandas create
the exact header/style cache and then write body columns through XlsxWriter's
column API. Every other frame retains `DataFrame.to_excel`, and `FFT and
neighbors` always retains that path. The specialized path must preserve stable
XLSX ZIP members, cell values/types/styles, shared-string order, sheet order,
dimensions, widths, and freeze panes.

Column-width measurement may process adjacent columns in bounded DataFrame
blocks, but it must preserve the exact per-column `str(...)` length maximum and
the existing `+ 4` width. When the workbook destination is on a different
Windows volume from the system temporary directory, the final XLSX container
is assembled on the temporary volume, copied sequentially to a same-directory
temporary file beneath the intended project output folder, and atomically
replaced into place. The staging file is ephemeral: every durable file and the
publish temporary remain confined to the active project output path, and a
failed staged write must leave an existing workbook untouched.

During one `PostProcessingPipelineWorker.run()` call, repeated exact selected
reads from source XLSX workbooks may share a run-scoped cache. Cache identity
must include the resolved workbook path, size, nanosecond modification time,
filesystem ctime/creation identity, device/file identity, worksheet,
requested-column order, missing-column policy, electrode filter, and
electrode-column name. Processed input workbooks are immutable during these
scoped phases; concurrent same-file in-place edits are outside this boundary.
Cached frames are returned as defensive copies, and a pre/post signature check
prevents a read changed in flight from being stored. The scope is closed on
success, error, and the early frequency-domain-QC review return; reads outside
that explicit worker scope remain uncached. Process-global or cross-run
workbook caches are not allowed. On the normal path it is released after
Stats-ready export and before the memory-intensive time-domain source-map
producers, which do not consume the selected-XLSX reader.

That same worker run may also reuse one immutable `ProjectDatasetIndex` across
frequency-domain QC, harmonic selection, and Stats-ready export. These phases
may update tool metadata and downstream outputs, but they must not mutate the
processed input workbook tree, participant/group assignments, configured Excel
root, or manual participant-condition preprocessing exclusions covered by the
snapshot. Standalone entry points still load a fresh index, supplied indices
must match the resolved project root, Stats-ready diagnostics retain their
existing order, and consumers must not read the reused manifest snapshot after
an intervening metadata write.

## Preservation Rules

- Do not change metric formulas, FFT bin selection, noise-window logic, sheet names, column names, filename/folder naming, channel ordering, logging semantics, or completion/error behavior.
- Do not bypass the processing-ledger-to-FullFFT geometry match, accept a
  geometry-less legacy provenance record, or combine different geometry or
  retained-set fingerprints in one downstream analysis.
- Do not change workbook formatting, freeze panes, writer engine behavior, or the rule that omits `FFT and neighbors` when no neighbor rows exist.
- Do not change the 55-on-bin metadata handling; see `docs/agent/architecture/fft-crop-method.md`. Missing locked FFT crop metadata, `fixed_epoch_fallback`, or off-bin target frequencies must be hard failures, not warnings or nearest-bin fallbacks.
- Legacy compatibility wrappers have been deleted; runtime callers should use the current shared owner.
