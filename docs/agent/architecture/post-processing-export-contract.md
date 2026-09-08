# Post-Processing Export Contract

This page documents current post-processing, Excel reports, and NumPy spectral
companion exports. Refactors must preserve scientific values and processing
order unless a task explicitly changes the corresponding method contract.

## Native Condition Results

New standard participant/recording-condition outputs use
`<recording>_<condition>_Results.fpvs`: a small UTF-8 JSON declaration owned by
`Main_App.io.result_manifest`. It replaces the former XLSX pointer workbook,
not the scientific arrays. It records a version, ordered sheet names, and the
existing immutable `.spectra.*.npz` / `.metrics.*.npz` descriptors (basename,
size, SHA-256, schema version and sheets). Numerical values remain in those
uncompressed companions, with the same dtypes, bits, grid and metadata.

Companions validate before the manifest is atomically published beside them.
Failed publication preserves the previous manifest; readers reject missing,
corrupt or inconsistent native results without falling back to an older XLSX.
Shared condition/spectral/selected-column readers retain their APIs and accept
both native anchors and historical XLSX declarations. Explicit XLSX report
destinations and advanced recipe exports retain their existing writer.
Long/wide statistical workbooks remain Excel and retain exact numeric readback
and formatting. Full-audit formatting reuses column rules/styles; individual
Stats exports retain both original Excel serializers in memory before writing
the final workbook, preserving the established numeric rounding boundary.

Dataset discovery accepts both anchor formats and prefers the exact native
sibling. Existing legacy-only recordings stay reusable; recordings selected
for reprocessing freeze native output paths before expected-cell receipts are
created. Receipt keys remain compatible (`workbook_write_receipt_v1`) and
continue to bind exact anchor paths, hashes, validated schemas and companions.
This changes no preprocessing or FFT operation, harmonic rule or QC decision.

Reading a BCA Method Audit may reuse exact frequency-column parsing within that
single call: at most 256 built-in string tokens of at most 128 characters each.
Numeric values, custom string types and oversized tokens retain direct parsing.
Cache allocation/admission failure falls back to the original parser. This
bounded memo contains no scientific arrays, survives no read, and changes no
row ordering, duplicate handling, exceptions, workbook validation or arithmetic.

## Entry Contract

Active post-export adapter imports should use `Main_App.exports.post_export_adapter`.

`post_process(app, condition_labels_present)` expects an app-like object with:

- `preprocessed_data`: mapping of condition label to MNE `Epochs` or `Evoked` objects.
- `save_folder_path.get()`: output root folder.
- `data_paths`: source data paths used for PID and event lookup.
- `settings`: `SettingsManager`-like object or dict for analysis settings.
- `log(message)`: logging callback.

The function logs start/end status, skips conditions without data, and logs a warning if no result files are saved.

The processing-end GUI must use required post-processing outcomes when deciding
whether a run succeeded. An early frequency-QC/readiness failure must preserve
its specific reason in the saved downstream-stale state and report incomplete
progress, even when every available participant workbook was just written.
File recency is not evidence of a released analysis cohort. Tool guards display
that saved reason rather than assuming an exclusion changed. Full-audit export
is optional for single-session projects, but is required for repeated-session
Stats because the legacy participant-keyed export cannot represent visits.
Normal and selection-resume completion must report a repeated-session full-audit
failure as incomplete, while independently valid FullFFT/SNR evidence remains
available. Optional source-map failures do not invalidate successful core outputs.

Visible smoke check (CI or an approved local visible session): finish an adaptive
harmonic review, then verify that full-audit export succeeds on both a fresh
selection and a saved-selection resume. In a disposable repeated-session project,
make that export fail and confirm the completion message names the unavailable
analysis workbook without claiming Stats readiness or invalidating upstream SNR.
The equivalent single-session audit failure remains an optional-export warning.

Preflight condition review compares the declared event map with the actual
planned spans. A declared condition with no start occurrence requires an
explicit exclusion decision or cancellation to investigate triggers before
processing starts. Missing conditions are not preselected for exclusion, and
recording-level and participant-level decisions retain their existing scopes.
This does not relax the expected recording-condition ledger release checks or
create output receipts for absent data.

Confirmed raw-file registration atomically records
`tools.processing.pending_raw_registration` with the cumulative added
processing IDs and their registration fingerprint. It also marks downstream
QC, neutral FullFFT provenance and selection-derived artifacts stale and clears
the harmonic cache entries, preserving review decisions and existing files.
`Main_App.processing.raw_registration_state` prevents pre-review coverage,
canonical dataset/final release, FullFFT provenance and clearing QC staleness
from accepting an old plan that omits these IDs. The current expected plan must
match their canonical manifest identity and condition map, and its outcomes
must account for every added recording, including explicit valid exclusions.
Cancelling later QC therefore cannot make Resume Post-processing release the
previous smaller dataset. Missing visits with no registered raw recording do
not become expected recordings.

This enrollment check reconciles receipt metadata without rehashing artifacts;
normal outcome reconciliation still defaults to full artifact validation, and
all existing physical-artifact and scientific release checks remain required.
Before building pre-review coverage, the workflow atomically stores compact
completion receipts for additions with validated current processing accounting.
These bind canonical recording identity to the expected recording and outcome
fingerprints. Separate Single-file runs accumulate completion; later Single
reruns do not make earlier completed additions appear pending. The cumulative
registration fingerprint stays unchanged by completion, and direct release
checks remain read-only. Pending additions absent from the current plan still
block release. Projects without this marker retain their existing behavior.

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

The canonical selection builder applies the manifest's existing JSON conversion
before fingerprinting, workbook generation, persistence, and report handoff.
Harmonic-keyed maps therefore use the same string keys in memory and on disk;
unavailable diagnostic numbers use the same null representation. This preserves
the scientific fingerprint and ordered selection rows while allowing full-audit
export to compare the complete caller payload against the validated persisted
selection exactly. The export's mismatch and final-release guards remain strict.
Saved-cache loading also retains harmonic keys with explicitly unavailable Z
diagnostics, so rehydrating a selection cannot silently remove evidence or change
its scientific fingerprint.

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

The accepted-selection/all-current shortcut leaves current outputs intact when
the fingerprint matches. A normal full run regenerates exports; pending repair
also overrides that shortcut. Accepting a different fingerprint first marks all
four derivatives stale, then resumes the normal post-processing pipeline after
harmonic selection. A continuation without pending repair reads
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

Frequency-domain review identity excludes the harmonic cache's
`selection_cache_source`, `selection_cache_saved_at`, and `selection_cache_key`
annotations. Saving review decisions can change those annotations without
changing any scientific evidence; unchanged findings must reuse the accepted
review. Older saved reviews are compatible only when their validated analysis
hash matches the complete current payload with the original cache annotations
substituted. Automatic synchronization preserves that original validated review
evidence when reusing its analysis identity. Source, cohort, harmonic-selection,
ROI, settings, and finding changes continue to invalidate review reuse.
Resolved Retain decisions for prior-exclusion reconfirmations stay in the
completed review receipt when its validated analysis is unchanged, even after
those reconfirmation findings disappear. They add no active exclusion authority
and do not reopen the ordinary findings solely because the visible list shrinks.

Repeated-session review reports resolve `recording_assignments` from the full
canonical project recording registry for both analyzed recordings and prior
exclusions requiring reconfirmation. An excluded recording can therefore appear
in `recording_summaries` with its registered participant, group, and session while
remaining absent from the numerical `recordings`, source workbooks, and harmonic
inputs. Unknown registry IDs still fail identity validation; saved decision text
never supplies a replacement identity. This review metadata does not change
scientific cohort fingerprints or exclusion scope.

Post-processing validation reuse is owned by
`Main_App.processing.post_processing_context`. An explicit context spans one
worker's QC/selection/workbook phases; standalone export entry points create
their own scope, and nested exports share it. Scope exit discards all retained
results. Hits still check current project/cohort/settings/ROI identities,
release decisions and source dependencies, and return detached values.
Publishing artifact-freshness bookkeeping alone does not invalidate scientific
selection. Public final-release gates remain mandatory.

The independent frequency-QC context reuses only successful `current` evidence
derived from the processing ledger. The scope retains at most one such context,
with an 8 MiB Python-container admission cap and a 32 MiB snapshot-read cap.
Canonical project and live ledger paths plus content SHA-256 identify reuse;
hits return detached values and recheck the ledger after detachment. Missing,
corrupt, invalid, oversized or changed inputs use the uncached diagnostics.
Misses parse the exact bounded byte snapshot used for their identity and use
that one snapshot for coverage and processing entries, preventing retention of
mixed evidence if a mutable ledger path changes and then changes back.
Workbook, source-provenance, selection and review-decision validation remain
outside this ledger-only cache at their original call sites.

`Main_App.processing.provisional_harmonic_cache` holds at most two provisional
scientific results for one frequency-QC review flow. The GUI passes the same
instance from the first worker through decision saving to the resumed worker,
then clears it on completion, cancellation or failure. Standalone QC calls
remain uncached unless explicitly given an instance. Ordered scientific inputs
and source-content hashes must match before reuse. Only provisional harmonic
evidence is cached: reports, current decisions, exclusions and final-release
checks are rebuilt on every run.

The worker's two source-map modes share one compatibility-index scope after
workbook validation is released. Each standalone source producer also opens
that scope; nested calls reuse it and scope exit retains no participant arrays.

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
managed provenance. Its cohort/QC fingerprint uses only reviewed frequency-
domain decisions, including participant- and recording-condition exclusions
and their condition-scoped electrode exclusions. Historical `auto_*` values
remain audit suggestions in project state but do not own cohort identity or
neutral provenance. Changing a reviewed condition decision invalidates the
record and requires post-processing to rebuild it.

Every active FullFFT workbook must match one completed processing-ledger entry
with the project geometry identity and the expected retained channel count.
Missing pre-QC-15 geometry, `standard_1005` legacy identity, an unknown
coordinate definition, or mixed retained/geometry fingerprints blocks creation
or reuse of neutral FullFFT provenance. Geometry staleness requires EEG
reprocessing before post-processing; a selection-only rebuild cannot repair
it. Existing legacy files remain audit artifacts and must not be silently
relabeled or pooled with canonical BioSemi64 outputs.
The same geometry check runs on the candidate cohort before review, without
requiring accepted QC or current downstream artifacts. A saved mapping mismatch
can be resolved by restoring the configuration actually used to process the
source; deliberately changing source wiring still requires reprocessing.

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
The input adapter accepts the writer's historical `55_onbin` and current
`project_marker_plan_target_grid_v2` crop identities. Both retain the exact
sample-count, on-bin divisibility, fingerprint, reference, channel, unit and
artifact-integrity checks; accepting the current tag adds no recropping or
resampling.

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

Whole-condition QC exclusions must be applied consistently to the provisional
harmonic pool and final ROI coverage. Pre-review source coverage still validates
the original workbook, but a subsequently reviewed excluded condition is not a
required contributor to harmonic selection. Never derive this exemption from
file absence: only the existing scoped review decisions authorize it. Cohort QC
reports these cells as `excluded_by_review` / `reviewed_condition_exclusion`.
Final coverage accepts the same canonical decisions as live pair sets or saved
JSON rows, retains the source evidence, and makes the affected result unavailable.
Saved coverage must also agree with its canonical whole-cell exclusion decisions;
contradictory older coverage requires rebuilding reviewed post-processing.
Other conditions/visits stay eligible; actual contributing Ns and the existing
group/condition weights are preserved. Entirely empty declared adaptive-pooling
cells and genuinely missing required sources retain their existing failure rules.

The primary `ROI Long` sheet provides one observed participant x condition x
configured-ROI row with raw Summed BCA, RMS-normalized BCA, signed-mean-
normalized BCA, canonical group label, and concise QC fields. Supporting wide,
electrode-level, whole-scalp, harmonic-scale, QC, ROI-definition, ROI-coverage,
and harmonic-selection sheets make the aggregation auditable without adding
source paths or file hashes to the statistical table. ROI Coverage records the
expected, observed, excluded, successfully interpolated, and used electrode
sets and counts for each released cell.

Stats-ready ROI validation uses the same canonical BioSemi channel-name
normalization as the frozen QC-21 definition snapshot. Case-only spelling
differences such as `FCZ`/`FCz` must not invalidate an unchanged ROI, while real
membership or ordering changes still require a new release. Full-audit numeric
and exclusion lookups normalize frozen channel labels to the electrode table's
uppercase keys; published coverage retains the canonical snapshot labels.

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
- `FullSNR` and `FullFFT Amplitude (uV)`: small companion-file notices for new exports; legacy exports contain their dense arrays directly.
- `Spectral Data`: the versioned companion declaration for new exports.
- `FFT and neighbors`, only when neighbor rows are non-empty.
- `Spectral Eligibility`, one deterministic availability row per filter-reachable project harmonic.
- `Spectral Metric QC`, per-channel BCA/SNR/local-z availability and reason codes.

All metric DataFrames insert `Electrode` as the first column. Target-frequency
columns are formatted as `{frequency:.4f}_Hz`. FullSNR retains its established
0.5-Hz to applied low-pass/Nyquist grid in 0.01-Hz steps.

For the normal one-object condition export, FullSNR calculation may retain
only the bins needed by the exported interpolation grid plus the unchanged
right-hand noise window. The retained FullSNR values and interpolated output
must be byte-identical to calculating the complete Nyquist range. Multi-object
conditions retain complete-spectrum accumulation because their frequency grids
can differ while their FFT matrix shapes match.

## NumPy Spectral Companion

`Main_App.io.spectral_data` owns `numpy_spectral_companion_v1`. Every new
condition export writes FullFFT and its independently calculated FullSNR into
one uncompressed, non-pickled NPZ beside the workbook. Float64 arrays preserve
the values supplied to the writer exactly, including signed zero and nonfinite
FullSNR values. Labels, electrode order, exact FullFFT frequencies, fs/N, units,
protocol, eligibility fingerprint, and retained-occurrence metadata are saved.
FullSNR is never reconstructed from the averaged FullFFT array.

The companion is named `<workbook stem>.spectra.<20-character SHA prefix>.npz`.
Its `Spectral Data` workbook sheet has `Field`/`Value` columns with JSON-encoded
version, local basename, byte size, full SHA-256, and ordered spectral sheet
names. References cannot escape the workbook directory. Readers verify both
the manifest and complete companion before supplying values. A declared
missing, corrupt, unsupported or changed companion is an error; it must never
fall back to a notice sheet or silently reuse a cache. Workbooks without this
declaration keep the established Excel-only read behavior.

`write_results_workbook` writes and validates the immutable companion first,
then validates and atomically replaces the workbook last. Cross-volume XLSX
staging resolves the companion against the final workbook directory. Failed
schema validation, copy or replacement preserves the previous workbook and
companion. A failed or superseded export can leave an unreferenced companion;
managed reprocessing cleanup removes only generated spectral siblings. It
preserves unrelated NPZ files and other participants during selective cleanup.

The workbook remains the dataset-index discovery identity. Its write receipt
also records `spectral_companion`; condition readiness and incremental reuse
check that descriptor. Neutral FullFFT provenance schema v3 adds the same
optional source field, and Stats, plots, scalp-map and detectability cache
identities bind the companion. Legacy source signatures remain unchanged when
no declaration exists. Moving a project preserves this association through
the relative sibling filename; copy or share the workbook and companion
together. No application-owned workbook-only project clone/export path exists.

The shared full/header/selected-column readers route spectral and compact
tables to their separate NPZ companions. Stats, FullFFT grid QC, Free Harmonic Clustering,
legacy LORETA FullFFT inputs and Individual Detectability use this boundary.
Plot snapshots capture both dense arrays with their workbook and validate
source identity before publication. Scalp Maps calculates from the saved
compact BCA/SNR/Z values. A run-scoped cache retains at most four numerical
companion payloads per family. A separate cache keeps up to 256 already-verified
spectral headers and compact schemas so later identity/header passes do not
reload evicted numerical arrays. Spectral headers share identical immutable
tuples and are also bounded to 262,144 unique header labels. Reuse requires the
same declaration and workbook/companion signatures, including size, modification
and change times, device, and file ID. First reads still validate checksums and
schema/grid; new scopes revalidate, and changed signatures invalidate reuse.

Pure frequency calculations additionally use bounded in-memory reuse, independent
of workbook identity: `full_fft_grid_qc` retains at most eight exact text-header /
oddball-rate results (32,768 labels per header), and `spectral_eligibility` retains
at most sixteen immutable domains of up to 256 harmonics. Larger inputs use the
same uncached calculation. Keys include the full ordered header or the validated
protocol, sample grid, filter and notch snapshots respectively. Every request
still validates its current inputs and exported eligibility rows; these caches
never replace source-file validation or retain mutable reports/receipts.

## Compact Condition Companion

`Main_App.io.condition_data` owns `numpy_condition_companion_v1` and a separate
`<workbook stem>.metrics.<20-character SHA prefix>.npz`. The `Condition Data`
workbook manifest uses the same relative-name, size, and SHA-256 contract as
the dense companion. It stores already-calculated FFT amplitude, BCA, SNR, Z,
Spectral Eligibility, Spectral Metric QC, FFT and neighbors, and FFT Metadata.
Numerical blocks preserve their original values and types without pickle;
text/mixed metadata retain explicit types and missing-value distinctions.

Default per-condition Excel tabs are notices, with no automatic numerical
copies or large audit tables. `write_results_workbook(include_condition_excel=True)`
is the explicit report-writer option. Stats-ready and full-audit long/wide
Excel exports retain their existing writers and remain user-facing outputs.

Compact reads validate the compact archive and load requested tables/columns
without materializing dense spectra or unrelated audit rows. Old workbook-only
or dense-only companion exports retain Excel compatibility for their compact
tables. New caches, current-run receipts, final QC release, neutral provenance,
and publication source identities include `condition_companion`; a missing or
changed declared file is an error, never a reason to reuse a notice tab. Cleanup
can remove declared generated compact companions for repair, including corrupt
ones, but preserves arbitrary NPZ files and undeclared compact archives.

This is a storage change only: all FFT bins through Nyquist are retained,
including the 30,721 bins from 120 seconds at 512 Hz. Excel's 16,384-column
limit no longer constrains FullFFT. Epoching, trigger timing, filtering,
averaging, noise windows and statistical methods are unchanged.

## FFT Neighbor Export

The `FFT and neighbors` sheet uses these columns in this exact order:

`file_name`, `condition_label`, `condition_id`, `repetition_index`, `channel_or_roi`, `target`, `fs`, `N`, `T_sec`, `df_hz`, `k0`, `f_bin_hz`, `crop_mode`, `n55`, `first55_samp`, `last55_samp`, `N_step`, `N_mod_step`, `fallback_reason`, `amp_m11` through `amp_m1`, `amp_p1` through `amp_p11`, `warning`.

The target label uses the project oddball rate, for example `1.2Hz` or
`0.3Hz`. Neighbor amplitudes are exported for +/-11 FFT bins around the target
bin, excluding the center bin. Out-of-range neighbor bins are `NaN` and set a
warning string.

`build_fft_neighbors_rows(...)` returns one row per electrode/channel. It resolves `k0` by the exact target-bin formula, records `fs`, `N`, `T_sec`, `df_hz`, and crop metadata, and raises if the target frequency is not exactly on an FFT bin. It must not fall back to the nearest frequency bin. `crop_mode` must be `55_onbin` and `N_step` must be present; fixed-epoch FFT fallback is not valid for normal post-export.

`write_results_workbook(...)` moves the two dense spectral DataFrames into the
companion and writes each remaining report DataFrame to its existing sheet
name with no index column, freezes the header row, center-aligns cells
vertically and horizontally, and sets each column width from the maximum
header/data string length plus four characters. The optional `FFT and
neighbors` sheet is written only when the neighbor DataFrame is present and
non-empty.

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
