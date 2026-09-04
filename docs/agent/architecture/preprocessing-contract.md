# Preprocessing Contract

This page records the active preprocessing owner and the behavior that must stay
stable during Main App refactors. Treat it as the regression lock for the EEG
preprocessing path.

## Current Decision

`src/Main_App/processing/preprocess.py` is large because it preserves a
behavior-sensitive pipeline, not because it is automatically a refactor target.
Do not refactor it for size alone. Prefer documentation, characterization tests,
and focused regression checks unless there is a concrete bug, behavior change,
or maintenance task that requires code movement.

If the pipeline is working and no near-term preprocessing change is planned, the
lowest-risk maintenance path is:

1. Keep this contract current.
2. Add focused tests before any behavior-sensitive edit.
3. Split code only when the extraction boundary is obvious and fully covered.

## Active Owner

`src/Main_App/processing/preprocess.py` is the canonical active implementation
owner for EEG preprocessing.

`src/Main_App/processing/fft_multinotch.py` owns the internal, versioned
frequency-domain line-noise mask and application helper. It has no settings or
GUI responsibilities; `preprocess.py` remains the public pipeline orchestrator
and decides whether and where the helper runs.

Current app processing must call:

```python
from Main_App.processing.preprocess import perform_preprocessing
```

Compatibility paths such as `Main_App.perform_preprocessing` and
`Main_App.Shared.processing_mixin` may delegate to this import surface, but
active runtime code must not import retired `Main_App.Legacy_App` preprocessing
paths.

The public preprocessing surface is:

- `begin_preproc_audit(raw, params, filename)`
- `perform_preprocessing(raw_input, params, log_func, filename_for_log)`
- `finalize_preproc_audit(before, raw, params, filename, events_info=..., fif_written=..., n_rejected=...)`

Callers should not depend on private helpers or split-stage internals.

## Processing Route

The canonical file-level process runner is
`src/Main_App/Performance/process_runner.py`. Its single-file worker route is:

1. Exclude header-only BioSemi recordings before load.
2. Check the strict project-root preprocessed Raw cache.
3. On cache miss, load BDF through `Main_App.io.load_utils.load_eeg_file`.
4. Run raw channel-health QC for hard participant exclusions.
5. Capture pre-state with `begin_preproc_audit`.
6. Run `perform_preprocessing`.
7. Store a cache entry only after successful preprocessing.
8. Extract events from the configured stim channel.
9. Build epochs per event-map label.
10. Run post-export through `Main_App.exports.post_export_adapter`.
11. When post-export succeeds, publish the source-ready signed time-domain EEG
    derivative from the already-built condition epochs. This serialization step
    performs no new preprocessing, FFT, or source estimation.
12. Finalize the preprocessing audit with `finalize_preproc_audit`.
13. Clean up worker memory and temporary memmap paths.

The loader and preprocessed-Raw cache must supply a validated canonical
BioSemi64 runtime identity before raw QC or preprocessing continues. Cache
identity includes the montage, mapping profile, geometry/coordinate
fingerprints, and retained scalp set; an older or mismatched cache entry is a
miss and is not relabeled as current.

GUI processing must route through the active process runner. Single-file runs use
the same runner with `max_workers=1`. Do not add a fallback path that bypasses
the process runner or calls retired legacy preprocessing.

Before the processing ledger plan is chosen, the GUI may run the embedded
preflight QC workflow in `src/Main_App/gui/preprocessing_qc_workflow.py`. This
workflow is review-first: it scans the selected BDF pool for BioSemi
recording-not-started files, loads eligible raw files in a `QThread` for
conservative removed-electrode/raw-channel/spectral QC summaries, compares one
locked FFT-grid observation per participant-condition against a unique strict
majority when one exists, asks the user to confirm any participant-condition
grid exclusions, asks the user to confirm the manual removed-electrode table,
offers participant-level exclusions, and reports remaining suspicious
findings. The grid identity is the sampling-rate-independent integer count of
1.2-Hz oddball cycles in the planned crop; the review does not hard-code 120
seconds or alter the locked shortest-common crop calculation. Incremental raw
observations are compared with header-only observations from the active,
completed processed-workbook cohort; the current raw plan replaces an older
workbook observation for the same participant-condition. Ledger-incomplete and
frequency-domain-excluded participants do not define the reference. When valid
grids are tied, the review shows each cohort without guessing which one to
preselect. Accepted manual
removed-electrode, participant-condition, and participant-exclusion decisions
are saved to project preprocessing settings before
`classify_processing_inputs()` runs. Confirmed
recording-not-started files are passed to the process runner through
`_fpvs_preflight_recording_not_started_files` so they can be recorded as
`recording_not_started` exclusions without creating child-process work. The raw
BDF files are never modified.

Incremental processing runs classify the selected BDF pool before embedded
preflight QC and only scan files whose ledger state is new, stale, incomplete,
or missing expected outputs. Files already recorded as completed or excluded
for the current raw-file metadata and processing fingerprint keep their prior
QC decisions. If preflight QC adds participant-specific project metadata for
new files, the GUI carries forward still-valid completed states and refreshes
only skipped ledger fingerprint metadata so later runs do not rescan old files.
Settings provides a separate processed-workbook FullFFT-grid review for already
completed files. It reads workbook headers on a worker thread, uses the same
active harmonic-selection cohort and strict-majority oddball-cycle identity,
retains already excluded pairs for editing, and lets the user add or clear
participant-condition exclusions. Valid tied grids are shown without an
automatic choice, and recalculation remains blocked until the proposed included
cohort has exactly one valid FFT grid.

Epoch building in the process runner must preserve locked FFT crop behavior.
When valid `55_onbin` repetition crops exist for a condition, those repetitions
must keep `N % N_step == 0` and metadata `N_mod_step == 0`. Do not downgrade
the whole condition or any repetition to fixed-epoch fallback. Do not silently
skip fallback repetitions. If a selected repetition cannot produce a valid
`55_onbin` crop, the normal processing run must fail before post-export.
Downstream `FullFFT Amplitude (uV)` columns are expected to include the exact
nominal oddball harmonics from this crop behavior.

The source-ready derivative uses those same aligned `55_onbin` epochs. It
averages repetitions sample-by-sample in signed volts and preserves exact `N`,
sampling frequency, crop/bin metadata, EEG channel order, montage, bad-channel
provenance, and final average-reference state. It must not introduce a second
crop plan, nearest-bin fallback, spectral window, rectification, or magnitude
operation.

The process runner logs `[TIMING] file=... section=... elapsed_ms=...` for
cache lookup, load, pre-audit, preprocessing, cache store, events, epochs,
export, post-audit, and cleanup when those stages run. The returned per-file
result includes `timings_ms` and `preproc_cache_status` so users can compare
first-run and cache-hit runtimes.

The preprocessed Raw cache version is
`preprocessed-raw-v11-analyzed-intervals`, and the project processing ledger
uses `processing_fingerprint_v11_biosemi64_frequency_protocol`. The processing
fingerprint stores the project frequency protocol's canonical payload and
fingerprint, so equivalent protocol objects and manifests have one identity
while a rate, analyzed-cycle count, recurrence, or marker-code change
invalidates reuse. The
raw channel-health QC threshold, removed-electrode QC mode, per-file manual
removed-electrode list, baseline raw-amplitude metadata, and rare-burst
candidate list are part of the cache payload so changes to those settings
invalidate cached preprocessed Raw files. The downstream-only
`manual_excluded_participant_conditions` setting is deliberately omitted from
the raw-processing fingerprint: it does not change EEG preprocessing or
workbook generation. It remains part of the Stats harmonic-cache signature so
changing the included workbook cohort requires harmonic recalculation. The
cache identity also includes the
line-noise-filter enabled state, selected 50 or 60 Hz mains frequency, method
version, half-width, and component count. It also includes the project-owned
BioSemi64 montage and mapping profile plus the canonical coordinate and
retained-scalp-set identity. Current cache metadata persists
raw-QC, manual removed-electrode, kurtosis, and interpolated bad-channel names
plus the interpolation request/status/error, requested/applied/skipped FFT
multi-notch centers, and complete geometry identity so cache-hit runs can still
produce complete participant QC and preprocessing provenance.
The cache key also binds the current canonical frequency-protocol payload and
fingerprint, the exact condition event map, and the reviewed source-span-plan
fingerprint. Processing validates that reviewed plan against the current
protocol and event map before attempting a cache lookup; an internally valid
plan from an older project context cannot authorize reuse.

After frequency-domain QC is accepted, processing completion calculates the
project-wide significant-harmonic list once through
`Main_App.processing.harmonic_selection_qc`, persists its exact fingerprinted
selection in `project.json`, and writes
`Quality Check/Harmonic_Selection_Summary.xlsx`. Active downstream project
tools load this processing-time selection. They must stop with reprocessing or
Settings-recalculation guidance when it is missing or stale rather than
calculating another list. Settings recalculation must force a fresh calculation
from the current FullFFT workbooks without deleting the previous durable entry
at startup; the current fingerprint is replaced only after the recalculation
and project-metadata write succeed.

## Canonical BioSemi64 Geometry

The supported acquisition geometry is the MNE `biosemi64` template. The full
BDF header must first resolve to all 64 canonical anatomical sensors through
either direct anatomical labels or the explicit `biosemi64_1020_ab_v1`
standard 10/20 A1-A32/B1-B32 wiring profile. That profile does not support
BioSemi ABC/equiradial or custom layouts. CMS/DRL remain outside recorded data;
the selected EXG mastoid signals remain coordinate-free through the initial
reference and are then dropped. `biosemi64` is a standard cap-template
geometry; it does not claim participant-specific digitized electrode locations.

After the optional channel limit, preprocessing freezes the retained canonical
scalp set and validates the Raw coordinates and runtime identity. The ordinary
path retains 64 sensors. A configured reduced path retains the first N members
of the frozen canonical BioSemi order while preserving their source data order;
its reduced-set fingerprint prevents it from masquerading as a complete
64-channel result. Geometry validation is metadata/eligibility enforcement at
the existing boundary after step 3; it is not an added signal transform and
does not change the locked order below.

Historical processing that used `standard_1005` has a different geometry
identity. It cannot reuse the current preflight or preprocessed-Raw cache, and
processed cohorts with missing, legacy, or mixed geometry provenance cannot
publish current FullFFT provenance. Reprocess a historical recording before a
new analysis or publication when interpolation occurred or a geometry-based
rule informed its channel decisions. Even without interpolation, regenerate
scalp maps so values are drawn at the BioSemi64 positions.

The deterministic synthetic QC-15 diagnostic held signals and bad-channel
lists fixed while changing only `standard_1005` versus `biosemi64`. With no bad
channels, voltage and FFT/BCA/SNR/local-z values were identical, although plot
coordinates still differed. With interpolation, the repaired channel changed;
the following average reference spread part of that difference to other
channels. The largest frozen-scenario differences were 1.4691 microvolts in a
sample, 0.0693 microvolts in exact-bin FFT amplitude, 0.0677 microvolts in BCA,
0.3221 in SNR, and 1.3269 in local z, with six threshold-decision changes
across the reported pre- and post-reference stages. These are synthetic
sensitivity results, not an estimate of effects in representative lab data.
See
`docs/agent/quality/biosemi64-geometry-sensitivity.md` for the reproducible
protocol, limits, and required lab-data follow-up.

## Raw QC Signal Review and Technical Exclusions

`src/Main_App/processing/raw_channel_qc.py` owns pre-preprocessing
removed-electrode detection, signal-review evidence, and independent technical
no-sample failures. It runs after a BDF is loaded and before
`begin_preproc_audit` so interpolation cannot hide the original evidence.
The calibration surface for automatic removed-electrode detection lives in
`src/Main_App/processing/removed_electrode_detection.py`. Keep threshold
constants, user-facing method wording, and low-variance, high-amplitude, and
spatial-predictability decision rules there so future training-data updates have
one obvious adjustment point. Use
`docs/agent/quality/removed-electrode-detection-calibration.md` before changing
those defaults.

`src/Main_App/processing/preflight_qc.py` coordinates the embedded GUI preflight
scan without importing Qt. The normal GUI route supplies an explicit active
project root and condition event map, which enables condition-aware preflight
QC `v7_analyzed_condition_scope`. A caller that omits either required
input receives an explicit `not_evaluated` planning result. It does not run the
retired whole-recording/first-90-second signal checks.

The v6 path reads the complete configured Status channel to plan events, then requests
EEG samples only from each shared marker-derived locked FFT span. The
time-domain and spectral intervals are identical to the samples that normal
processing will analyze; there is no fixed minimum or maximum condition
duration. Repetitions of one condition retain the shared shortest valid on-bin
length selected by the FFT crop contract. A present condition with an invalid
marker-derived crop fails that participant's condition-aware preflight result
explicitly without reading a substitute onset-based or fixed-duration interval.
A condition configured in the project but absent from one recording retains the
normal processing path's existing missing-condition warning behavior.
The event plan records the source Raw sampling rate, `n_times`, and
`first_samp`; its half-open absolute bounds are converted to Raw-relative
indices for reads. It also carries stable event-plan, protocol, occurrence,
approved-span, and source-span fingerprints. Normal processing validates this
exact plan against the source event stream before any signal-based raw QC.

Processing-time raw-channel metrics use the unique union of approved source
spans. After the continuous filter/downsample stages, each source boundary is
mapped to the actual target Raw grid by nearest-sample rounding with half-sample
ties upward. The versioned target plan supplies the unique samples for the
existing kurtosis statistic and the exact relative slices for epoch creation.
MNE may independently round the absolute `first_samp` when it resamples a Raw;
the target plan therefore records that observed target origin and maps interval
times relative to the Raw start. It does not rescale source absolute indices.
Interpolation still operates on the resident continuous Raw at its established
pipeline position. Missing or stale source/target plans stop processing, and
the preprocessed cache and source-ready provenance bind both plan identities.
Time-domain QC computes exact float64 metrics once over every unique sample in
each approved occurrence. Supplementary transient screening uses 5-second
windows with a nominal 2.5-second hop. A final full window ends at the exact
occurrence stop when needed; an occurrence shorter than 5 seconds gets one
unpadded window. Repeated overlapping flags report the union of flagged-window
coverage and do not estimate artifact duration. Cap-wide window amplitude
findings remain visible when a short burst is diluted in the full-occurrence
aggregate. A channel feeds the removed-electrode confirmation table only when
low variance recurs across every evaluated occurrence. Extra evidence in one
occurrence does not erase that persistent low-variance reason. High-
amplitude, rare-burst, spatial, occurrence-local, and transient findings remain
visible review evidence and are not interpolation suggestions.

The retired project epoch-window fields are not part of normalized
preprocessing or runtime parameters. When an older manifest contains custom
values, project loading moves them to
`compatibility.processing_fingerprint_v9` solely to reproduce existing v9
ledger and source-ready sidecar identities. That compatibility metadata must
never control extraction, preprocessing, or QC.

The v6 spectral QC uses the same shared per-condition, shortest-repetition,
integer-oddball-cycle FFT span planner as normal processing. It evaluates the
Hann-windowed FFT for every channel in deterministic memory-bounded batches;
focused parity tests require byte-identical per-channel amplitudes relative to
the all-channel formula. Evaluation continues through the configured retained
upper band, bounded by the source and configured downsample-target
Nyquist frequencies. The configured downsample target remains 256 Hz by
default; 128 Hz is only that target's Nyquist frequency and no 128 Hz
resampling is introduced. Neighboring noise explicitly uses +/-12 FFT bins,
excludes the target and immediately adjacent bins, and removes one global
minimum and maximum, leaving 20 bins for the mean and population standard
deviation. Expected FPVS harmonics, effective configured mains-notch centers,
their collisions, and unexpected off-harmonic peaks are reported separately.

Condition-aware signal findings are review-only in preflight v6 and in the
normal process runner. Severe raw amplitude and candidate count, fraction,
hemisphere, and connected-cluster crossings enter the existing explicit
recording/participant decision review; continuing does not promote their
channels to interpolation targets. Technical integrity failures and saved
manual exclusions remain independent. Each review row begins unselected and
must be explicitly kept or excluded; an exclusion can use recording or
participant scope. V4 caps participant workers at four,
simultaneous BDF reads at two, and simultaneous spectral evaluators at two. A
condition buffer larger than 256 MiB is filled in 10-second chunks into a
temporary condition-only float64 memmap; no full-recording preflight memmap is
created. V4 preserves deterministic result order and checks cancellation
between condition reads, diagnostic windows, FFT channel batches, and cache writes.
Successful participant results
are cached atomically under the active project root at
`.fpvs_processing/preflight_qc/v7_analyzed_condition_scope`; a missing, corrupt, or
fingerprint-stale entry is a cache miss. The key includes raw path/size/mtime,
relevant settings, method and dependency versions, the canonical BioSemi64
geometry identity, and the resolved event/span plan. The v6 directory/method identity,
`locked_fft_span_v1` completion policy, and geometry fingerprint invalidate
results produced under earlier geometry or fixed-minimum coverage.

The project lifecycle action **File > Reset Project Processing Cache...**
forces the next run through a cold data-quality, raw-preprocessing, and
incremental-planning path. It removes the preflight cache above, the
preprocessed-Raw cache at
`.fpvs_cache/preprocessed`, and the incremental completion ledger at
`.fpvs_processing/processing_ledger.json` (plus a leftover ledger temporary
file). Clearing the ledger is required because input classification occurs
before preflight QC and otherwise omits completed files from the scan. The
action preserves raw data, `project.json`, manual QC settings, current outputs,
review workbooks, and `.fpvs_processing/processing_runs.jsonl`. It does not
attempt to flush operating-system filesystem caches. Once the following run
begins, normal participant-output cleanup replaces the outputs being
recomputed.

Downstream tool caches, including Stats harmonic-selection caches, are outside
this raw-processing reset and retain their normal fingerprint invalidation.

`src/Main_App/processing/preflight_qc_plan.py` owns the condition/event plan,
and `src/Main_App/processing/preflight_qc_cache.py` owns the GUI-neutral cache
primitive. `raw_channel_qc.py` and `raw_spectral_qc.py` retain their existing v1
APIs alongside their versioned condition-aware evaluators. Output ordering must
remain deterministic for reporting.
For grouped projects, `HeaderOnlyPreflight` and `PreflightQcFileResult` retain
the canonical `group_id` from `RawFileInfo`. The GUI resolves that ID through
`ProjectGroupContext` and shows the configured group label in live scan status,
empty-recording review, removed-electrode review, possible-exclusion review and
details, and remaining review flags. A missing or unknown grouped assignment is
an error; folder names are not a membership fallback. In v2.1, participant
exclusions and removed-electrode maps remain keyed by project-wide unique
participant ID.

For repeated-session v2.2 projects, every preflight and processing observation
also carries canonical `recording_id`, `session_id`, session label,
`visit_index`, source, and stable group identity. Caches, candidate maps,
accepted/rejected electrode provenance, explicit exclusions, remaining review
flags, condition-crop decisions, ledger rows, and QC exports key per-file state
by recording ID so a second visit cannot overwrite the first. Participant ID
remains the person/pairing identity. Declared sessions without a recording are
shown as missing coverage and are never fabricated.

The project preprocessing setting `removed_electrode_detection_mode` now has a
versioned choice status and source. New projects explicitly default to Off.
Existing valid modes remain ready choices; legacy booleans map to ready Auto or
Off choices. If neither was saved, the project loads as provisional Off with
`confirmation_required`, and a routine save does not materialize that guess.
`require_removed_electrode_detection_choice_ready()` is the GUI-neutral guard
used by processing input validation. Before an unresolved legacy project can
process, the GUI asks once whether to enable the experimental detector,
recommends Off, and persists the explicit choice and migration provenance. The
legacy `auto_detect_removed_electrodes` boolean remains a compatibility
projection and is `True` only when the mode is Auto. Participant and recording
manual maps are normalized and preserved independently.

Preflight and processing use the same saved automatic-detector mode. Reviewing
removed electrodes activates the independent manual-list switch without
changing Auto or Off. When conservative auto-detect is enabled,
persistently flat/very low-variance scalp channels can be automatically added to
`raw.info["bads"]` before preprocessing. The second-pass raw-QC detector adds
flag-only candidate lists for extreme high-amplitude outliers, rare-burst
channels, and spatially inconsistent channels. These flag-only categories stay
in the signal-review table and are never prefilled into the removed-electrode
or interpolation list.
Spatial channels are only flagged when local predictability is both low and a
robust outlier within the participant's own montage. Low-variance raw-QC bad
channels are excluded from kurtosis donor/pick calculations and are included in
the later spherical interpolation target list.

Raw channel QC also records recording-level baseline raw-amplitude medians. A
severe review flag is recorded when both the scalp-channel median STD is at
least 10,000 uV and median P2P99 is at least 100,000 uV. A warning starts at
2,000 uV median STD or 10,000 uV median P2P99. Neither level automatically
excludes a recording. The GUI explains that referencing may reduce shared
electrical noise and links to BioSemi's CMS/DRL/referencing explanation. It
does not imply that referencing repairs clipping or missing data. Metrics,
severity, reviewed decisions, and analyzed scope are retained in provenance.

The independent `manual_removed_electrodes_enabled` switch controls the
PID-to-electrode `manual_removed_electrodes` map in project preprocessing
settings. When enabled, valid manual entries remain authoritative under Auto or
Off: they are treated as confirmed removed-electrode raw-QC candidates, added
to `raw.info["bads"]`, excluded from kurtosis donor/pick calculations, and
included in the later spherical interpolation target list. Under Auto they are
combined with accepted detector interpolation candidates while retaining a
separate manual source label. When the switch is disabled, stored maps remain
dormant and do not affect processing. Manual entries can contribute to
candidate count, fraction, hemisphere, and BioSemi64 connected-cluster review
findings, but those findings cannot exclude a recording automatically. When
the experimental detector is Off, it emits no low-variance, high-amplitude,
rare-burst, spatial, or detector-derived burden evidence. Independent manual
entries retain their own authority.

Repeated projects may additionally store
`manual_removed_electrodes_by_recording`. An explicit recording row, including
an empty row, overrides the participant-level compatibility fallback for that
recording only. Likewise
`manual_excluded_recordings` and
`manual_excluded_recording_conditions` are distinct from participant-wide and
participant-condition scopes. GUI review tables must show participant,
recording, session/phase-at-visit, visit index, group, and scope; excluding one
recording must leave its sibling visit active unless the participant-wide scope
was explicitly chosen.

During embedded preflight QC, the removed-electrode review keeps provenance
separate from the final compatibility map. It stores the original FPVS
Toolbox-flagged set, the subset the user accepts, any auto flags the user
rejects, manual additions for physically removed electrodes missed by automatic
review, the final confirmed set, the manual-only auto misses, auto/manual
overlap, and an agreement status. The final confirmed set is still saved to
`manual_removed_electrodes` so preprocessing behavior stays compatible. The
provenance fields are copied into per-file audit, raw-QC exclusion payloads,
preprocessed-cache metadata, and processing-ledger entries; skipped incremental
runs can therefore still report the prior auto/manual comparison without
rescanning already-current files.
The saved `Data_Quality_Check_Review_Flags.xlsx` workbook uses the canonical
`PID`, `Group`, `Source File`, and `Flagged Item` columns so its group label is
visible and `qc_summary_export` can merge its flags through the existing named
columns.

The project preprocessing setting `manual_excluded_participants` stores
participant IDs that should be skipped without removing their raw `.bdf` files
from the project. These exclusions are edited in Settings > Advanced >
Processing QC and may also be populated by downstream QC tools such as the SNR
Plot Generator when a whole-participant spectral failure is detected. The
process runner resolves the PID through the same participant/file mapping used
for manual removed-electrode metadata and records an `excluded` preflight result
with reason `manual_participant_exclusion`. Parent-side parallel processing
handles these manual exclusions before child-process submission, so excluded
participants do not pay the BDF load/preprocessing cost and the worker pool can
move directly to eligible files.

The default `max_bad_chans` is `20`. The following provisional crossings create
recording-level review findings on the BioSemi64 scalp surface:

- More channels than `max_bad_chans` are flat, very low amplitude, extreme
  high-amplitude outliers, or spatially inconsistent.
- More than 50 percent of scalp channels are flat, very low amplitude, extreme
  high-amplitude outliers, or spatially inconsistent.
- At least 50 percent of a hemisphere is flat, very low amplitude, extreme
  high-amplitude outliers, or spatially inconsistent.
- When removed-electrode auto-detection is enabled, the largest connected
  bad-channel cluster on the scalp montage has at least six electrodes.

The count and fraction rules use strict `>` comparisons. Hemisphere and cluster
rules use `>=`. A connected cluster of four or five is a warning-level review;
six or more is a severe review. Both use the canonical BioSemi64 coordinates.

The hemisphere rule remains separate from the global fraction rule so a
one-sided concentration stays visible when the full-scalp fraction is lower.
Each structured finding carries its observed value, denominator, comparator,
threshold, channel names, candidate sources, rule version, and review-only
authority. These rules do not change the cohort or delete outputs. An explicit
recording- or participant-scope exclusion still uses the established manual
review path. The raw BDF is never modified.

At the end of a GUI processing run, excluded files are reported in a modal
summary alongside header-only BioSemi recordings. The summary must state that
the final processed dataset excludes those files and that the raw BDF files were
not altered. The processing ledger records excluded participants and removes
their expected managed Excel outputs so downstream Excel-based tools do not
silently include stale workbooks from an earlier run.

The GUI finish handler also writes
`Quality Check/Processing_QC_Summary.xlsx` under the active project root. The
workbook has one row per participant in the processing plan and reports the PID,
manually removed electrodes, auto-detected low-SD removed-electrode candidates,
preflight auto/manual removed-electrode comparison fields,
auto-detected high-amplitude removed-electrode candidates, auto-detected
spatial-consistency removed-electrode candidates, kurtosis-rejected electrodes,
final interpolated electrodes, total rejected/interpolated electrode count,
raw-QC warning rules, missing condition outputs, and whether that participant is
included in the final processed dataset. It also includes an exclusion reason
column for excluded or failed participants.
This export is generated from the current per-file results plus the processing
ledger so incremental runs can include participants completed in earlier runs.

For repeated projects, the summary has one row per recording and adds
Recording ID, Session ID and label, Visit Index, and Group. The v2.1 sheet name
and participant-only column shape remain unchanged for legacy projects.

Future calibration changes that can alter which raw files or channels enter the
processed dataset must update focused tests and bump the preprocessing cache and
processing-fingerprint labels listed in the calibration guide.

If a worker reports success and at least one, but not all, expected condition
workbooks exist, the processing ledger records that participant as `completed`
with `condition_completeness` set to `partial` and `completion_warning` set to
`missing_expected_outputs`. The available condition workbook(s) are preserved and
remain part of the processed dataset; missing conditions are flagged in the GUI
run summary and in `Processing_QC_Summary.xlsx`. This is a condition-completeness
warning, not a hard participant exclusion. If no expected condition workbook is
created for a successful worker result, the ledger records a failure with reason
`no_expected_outputs` because there is no usable condition-level export for that
participant.

QC-20's Wave 1 foundation stores a separate, versioned
`expected_recording_condition_plan` in that ledger before result accounting.
It freezes canonical recording/session identity, raw-file identity, project
conditions, protocol and geometry fingerprints, reviewed marker evidence, and
each exact planned occurrence span. Every declared condition receives a cell,
including a condition with no observed onset. Current cells are `planned`;
skipped entries without current occurrence evidence are `legacy_unknown`.
Current project-level recording and recording-condition exclusions are frozen
as explicit no-output decisions with their reason, exact scope, evidence
fingerprint, planning timestamp, and truthful reviewer-identity status. They do
not require a marker plan or workbook for the excluded scope. The expected
matrix is written only after any destructive reprocess confirmation and before
the first generated output is removed. A reprocess scope that adds previously
skipped files runs current pre-processing QC for those files and merges their
reviewed marker plans before the matrix is frozen.
Those planning states never claim a final processing outcome. In particular,
the historical `condition_completeness=partial` compatibility flag is not
migrated to QC-20's future `partially_retained` outcome. Atomic workbook
receipts and readiness/release gates remain later QC-20 stages.

## Pipeline Order

This order is locked behavior. It matches the project decision to align the
Toolbox preprocessing sequence with the Volfart et al. (2021) FPVS
implementation: FIR filtering happens before downsampling. Do not change this
order during ownership, file-organization, performance, cache, GUI, or
documentation refactors:

1. Initial reference using the selected reference pair.
2. Drop the selected reference pair channels.
3. Optional channel limit through `max_idx_keep`, preserving the stim channel
   when needed.
4. FIR filter using the current PySide6/legacy-parity cutoff mapping.
5. Optional smart FFT Hann multi-notch filtering of retained mains components.
6. Downsample when requested.
7. Kurtosis evidence, its decision gate, and authorized bad-channel interpolation.
8. Final average reference.

The retained BioSemi64 identity is frozen after step 3 and checked before
geometry-dependent QC/interpolation. This validation boundary does not move or
renumber the eight signal-processing stages.

The order is part of the app contract. A refactor that preserves each individual
operation but reorders stages is a statistical-method behavior change. Any
future reorder requires an explicit user request, a fingerprint/cache version
bump, updates to this page and `docs/user/reference/methods-reporting-checklist.md`,
and focused tests equivalent to `tests/processing/test_filter_downsample_order.py`.

## Locked Behavior

`perform_preprocessing` mutates the incoming `raw_input` object in place and
returns the processed `Raw` object plus the number of kurtosis-identified bad
channels. On critical errors caught by its outer guard it returns
`(None, num_kurtosis_bads_identified)`.

The `params` dictionary is also mutable during a run:

- `_fpvs_initial_ref_ok` and `_fpvs_initial_ref_pair` are removed at run start.
- On successful selected-pair referencing, those audit keys are written back.
- The filter fingerprint is computed from the preprocessing order version,
  `high_pass`, `low_pass`, `downsample_rate` or `downsample`, `reject_thresh`,
  reference channels, stim channel, line-noise-filter enabled state, selected
  mains frequency, and the versioned FFT multi-notch constants.

Invalid filter cutoff ordering is intentionally fail-fast: if both cutoffs are
present and `high_pass >= low_pass`, `perform_preprocessing` raises
`ValueError` before entering the broad pipeline error guard.

Several stage failures currently warn and continue instead of aborting:

- Initial selected-pair reference failure.
- Resampling failure.
- FIR filter failure.
- Final average-reference failure.

That continuation behavior is historical pipeline behavior. Do not convert it to
fail-fast behavior without an explicit behavior-change request and focused tests.
Canonical geometry validation and bad-channel interpolation are deliberate
exceptions: either failure aborts that recording so an unsuccessful repair
cannot be reported or exported as processed data.

## Stage Details

Reference handling:

- Default reference channels are `EXG1` and `EXG2` when params do not provide
  `ref_channel1` and `ref_channel2`.
- Selected reference channels are coerced to EEG type when MNE requires it.
- Selected reference channels are dropped after initial referencing if present.
- The audit layer relies on `_fpvs_initial_ref_ok` and
  `_fpvs_initial_ref_pair` when the selected pair is applied successfully.

Channel limiting:

- `max_idx_keep` selects the first N members of the frozen canonical BioSemi64
  order after reference-channel drop; the loader has already validated all 64
  acquisition identities.
- The configured stim channel is appended to the keep list when it would
  otherwise be dropped.
- Current behavior uses `raw.pick_channels(final_keep, ordered=False)`.
- Selection membership follows canonical order while `ordered=False` preserves
  the recorded source order of retained data.
- The process runner requests a 64-sensor loader subset plus the selected
  reference pair and stim channel. After complete-header validation, the loader
  selects all canonical BioSemi64 sensors by identity and preserves their BDF
  source order; it does not assume that the first 64 header entries define
  anatomy. This avoids loading unused `EXG3` through `EXG8` before the existing
  channel-drop stage.

Filtering:

- `l_freq` is `high_pass` when `high_pass > 0`; otherwise it is `None`.
- `h_freq` is `low_pass`.
- Filtering uses MNE FIR settings:
  `method="fir"`, `phase="zero-double"`, `fir_window="hamming"`,
  `fir_design="firwin"`, `l_trans_bandwidth=0.1`,
  `h_trans_bandwidth=0.1`, `skip_by_annotation="edge"`.
- The historical `filter_length=8449` sample kernel is preserved at the
  downsample target rate. When filtering now runs before downsampling, the
  sample count is scaled to the current sampling rate to preserve the same
  filter duration and MNE transition-band validity.
- The code logs filter snapshot, mutation, Nyquist, range, applied-cutoff, and
  mismatch diagnostics. These messages are part of the current regression
  surface because they help diagnose accidental cutoff changes.

FFT multi-notch line-noise filtering:

- The optional line-noise stage runs after the existing FIR and immediately
  before downsampling. It does not move or change any existing pipeline stage.
- New project settings default to the filter enabled at a 60 Hz mains
  frequency. The alternative is 50 Hz.
- The requested components are the fundamental plus two harmonics:
  50, 100, and 150 Hz or 60, 120, and 180 Hz.
- `fft_hann_multinotch_v1` uses an FFT-domain Hann notch with a 0.5 Hz
  half-width around each effective center. The center gain is zero and the
  mask returns to unity at the center plus or minus 0.5 Hz.
- The stage is smart: it applies only requested components whose notch support
  overlaps frequencies retained by the preceding FIR and that fit below the
  raw-data Nyquist limit. For example, a 1--100 Hz FIR retains the 50 Hz
  fundamental and the supported portion of the 100 Hz notch for the 50 Hz
  setting, while it retains the 60 Hz fundamental but not 120 or 180 Hz for the
  60 Hz setting. When no requested component remains effective, FFT/IFFT
  processing is skipped.
- When `line_noise_filter_enabled` is false, the helper is not called and no
  FFT data round trip occurs. The EEG processing result therefore follows the
  pre-feature numerical path unchanged.
- The enabled state, selected mains frequency, method version, half-width, and
  component count are processing provenance and cache-invalidating inputs.

Evidence and implementation rationale:

- Retter and Rossion's FPVS preprocessing used a 0.1--120 Hz band-pass followed
  by an FFT multi-notch described as 0.5 Hz wide at the first three 50 Hz
  harmonics ([Neuropsychologia 91, 9--28, 2016](https://doi.org/10.1016/j.neuropsychologia.2016.07.028)).
- The Letswave preprocessing guide explicitly omits a 50 Hz notch when its
  0.05--30 Hz band-pass has already excluded that contamination
  ([Letswave preprocessing tutorial](https://letswave.cn/tu_ch1_2)). This is the
  basis for skipping a requested notch whose complete support is above the
  preceding FIR transition.
- The paper supplies the 0.5 Hz numeric precedent and three-component harmonic
  count; `fft_hann_multinotch_v1` makes the otherwise ambiguous width semantics
  reproducible by defining 0.5 Hz as the Hann half-width. This Toolbox-specific
  definition must be reported as such rather than attributed verbatim to the
  paper.
- Edge-annotated spans are transformed independently, matching MNE's documented
  rule that filtering on either side of an `edge` annotation treats the spans
  as independent signals
  ([MNE `Raw.filter` documentation](https://mne.tools/stable/generated/mne.io.Raw.html#mne.io.Raw.filter)).

Downsampling:

- Downsampling runs after the FIR and optional FFT multi-notch stages.
- It runs only when `downsample_rate` is truthy and the current sampling
  frequency is greater than the requested target.
- It uses MNE `raw.resample(..., npad="auto", window="hann", verbose=False)`.

Kurtosis review and interpolation:

- Kurtosis runs only when `reject_thresh` is truthy.
- EEG picks exclude existing bads and exclude the stim channel when the stim
  channel exists and is not typed as EEG.
- Scoring uses only the union of current marker-reviewed, included analyzed
  occurrences after filtering and downsampling. Interpolation itself remains a
  fixed repair on the continuous processed recording.
- The versioned EEGLAB-inspired variant uses
  `scipy.stats.kurtosis(..., fisher=True, bias=False, nan_policy="propagate")`,
  removes 10 percent from each tail of the finite channel distribution, and
  normalizes with its trimmed mean and population standard deviation.
- A nonfinite input/statistic, too few valid reference channels, or degenerate
  reference scale remains unavailable and blocks unsupported automatic action;
  it is never converted to a zero score.
- `abs(signed_normalized_score) > reject_thresh` creates evidence. Confirmed
  manual/physical bad channels retain direct authority. The initial eligible
  corroborator registry is empty, so every otherwise non-manual kurtosis-only
  finding requires an explicit Approve or Reject decision in the GUI.
- The GUI displays recording/session, electrode, analyzed condition and
  occurrence scope, raw kurtosis, signed normalized score, threshold,
  corroborator status, review-only raw-channel context, and a compact trace.
  It has no default choice, requires a reason, and states that approval repairs
  the electrode throughout the processed recording. Cancel, close, missing or
  stale evidence, and non-GUI execution do not authorize interpolation.
- A decision receipt is valid only for its recording, channel, evidence
  fingerprint, processing settings, analyzed spans, and BioSemi64 geometry.
  Changed evidence requires review again. Only authorized channels are appended
  to `raw.info["bads"]`.
- Pre-marked bads are also sent through the same interpolation boundary when
  kurtosis is disabled or finds no additional channels.
- Interpolation requires a validated runtime BioSemi64 identity and accepts
  only retained canonical scalp sensors, using
  `raw.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)`.
- Requested targets are recorded before the call. The successful-interpolation
  list is populated only after MNE returns and clears every requested bad.
  Missing/mismatched geometry, an invalid target, an MNE interpolation error,
  or an uncleared target records a failed status and aborts the recording.

Final average reference:

- Final average reference is attempted after kurtosis/interpolation.
- It runs only when at least one good EEG channel is available.
- It uses `raw.set_eeg_reference(ref_channels="average", projection=True)` and
  then `raw.apply_proj(verbose=False)`.

Stim-channel preservation:

- The configured stim channel defaults to `config.DEFAULT_STIM_CHANNEL`.
- The optional channel-limit stage must preserve it when present.
- The pipeline logs whether the stim channel is present at the very end.

## Audit Contract

`begin_preproc_audit` captures the pre-state before preprocessing mutates the
`Raw` object. `finalize_preproc_audit` computes the post-state, compares it with
the pre-state, and logs either `preproc_audit` or `preproc_audit_mismatch`.

Audit payload behavior currently covered by tests:

- The final sampling frequency reflects downsampling.
- The stim channel is reported.
- `sha256_head` is populated.
- `fif_written` is reported as an integer flag.
- `save_preprocessed_fif` is not copied into the audit payload.
- Geometry provenance contains the canonical montage/version, coordinate and
  scalp-set fingerprints, mapping profile, and retained scalp set.
- Interpolation provenance distinguishes requested channels, successfully
  interpolated channels, `not_needed`/`succeeded`/`failed` status, and any
  error. Failed or unknown interpolation is never represented as zero burden.
- A clean synthetic round trip reports no audit problems.

Audit logging should not change pipeline behavior. Existing defensive logging
guards are allowed to keep audit/logging failures from changing preprocessing
results.

## Regression Rules

- Do not change filtering math, reference handling, rejection thresholds, event
  handling, output data shapes, export inputs, or processing order unless the
  user explicitly requests a behavior change.
- Do not change the mutability contract of `raw_input` or `params` without a
  migration plan and tests.
- Do not remove or rename the public preprocessing functions without updating
  all active callers and compatibility exports.
- Do not add `Legacy_App` or `PySide6_App` preprocessing imports.
- Do not introduce GUI toolkit dependencies into preprocessing.
- Do not convert unrelated warning-and-continue stages to hard failures without
  explicit approval. The locked FFT crop contract is the exception already
  approved here: missing `55_onbin` behavior must hard-fail.
- If an internal mode cannot use the active process runner, fail clearly rather
  than silently falling back to legacy preprocessing.
- Refactors may split or move files only after focused tests prove the public
  behavior and generated outputs are unchanged.

## Focused Verification

Use the processing scope for preprocessing ownership, routing, or behavior
changes. The driver selects `.venv1` or `.venv` and excludes Qt execution
locally:

```console
python .agents/scripts/verify.py --scope processing --tier focused
```

Processing-window pytest-qt coverage runs in CI only by default. For GUI wiring
changes, also document a visible/manual processing smoke path.

For the QC-15 Settings smoke path, launch the application normally, open a
project, and visit **Settings > Preprocessing**. Confirm that **Electrode
montage** shows the single disabled choice **BioSemi ActiveTwo 64**, that
**Channel mapping profile** offers anatomical labels and the explicitly named
standard 10/20 A1-A32/B1-B32 profile, and that its tooltip excludes
ABC/equiradial/custom caps. Save each applicable profile, close and reopen the
project, and confirm the selection round-trips through `project.json`. With a
matching BDF, start preflight and processing and confirm the log reports a
validated BioSemi64 montage; a deliberately mismatched profile must stop at
loading with a clear geometry error. Do not run this visible path through an
offscreen Qt platform.

For documentation-only edits to this contract, confirm the diff only touches
docs unless the user explicitly asked for implementation changes.
