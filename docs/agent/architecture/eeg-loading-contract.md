# EEG Loading and BIDS Import Contract

## Shared import boundary

`Main_App.io.bids_import` owns preparation and verified reuse of one recording's
BIDS dataset. `bids_loader` requires the active project's absolute root from
explicit worker settings or `currentProject.project_root`; it never writes
beside a source or chooses the current working directory. Full, lazy, prefetch,
QC inspection, and export event-recovery reads enter through `load_utils`.
Keep header-only format inspection inside I/O; downstream numerical code must
consume normalized MNE Raw, generic recording metadata, and project settings.

`io.recording_contract.RecordingContract` is the immutable input contract.
`io.acquisition_metadata.resolve_recording_contract` resolves hardware defaults,
channel roles/order, reference and marker semantics, geometry identity, and
scientific capabilities before shared numerical work. Loaded recordings carry
the resolved contract; cache restoration reattaches validated geometry and
metadata. `io.geometry_metadata` resolves fixed versus per-recording geometry
expectations and validates historical identity encodings for downstream ledgers
and cohorts. Manufacturer names in those persisted encodings remain unchanged
to preserve fingerprints; consumers must not dispatch on them.

The upstream calibrated spatial profile supplies the existing QC method's
channel domain and coordinate identity. Numerical algorithms remain under
`processing`, including references, filtering, resampling and QC calculations.
`processing.acquisition_policy` is a compatibility shim, not an implementation
owner. Adding an adapter must resolve the contract and its actual capabilities;
it does not automatically qualify another montage for calibrated QC or add-ons.

`load_utils.open_bdf_resource_header` is the bounded, metadata-only exception
used by resource planning before worker admission. It neither reads signal
samples nor creates BIDS imports, and rejects annotation-bearing files before
MNE could scan their payload. It cannot supply numerical preprocessing input.

Imports live in `.fpvs_cache/bids-import/` beneath that project. Each immutable
publication includes source/companion content hashes, metadata/settings identity,
versioned import receipts, and hashes of generated files. Source changes or
damaged imports require a new publication. Concurrent callers publish distinct
complete directories and never replace another reader's open files. Original
recordings are not modified. Conversion and identity-validation times are
reported separately; reuse records zero conversion time.

BioSemi BDF data is copied byte-for-byte. BVCDF signal bytes are copied unchanged while
header/marker companion links are relocated. MNE-BIDS 0.16 loads these datasets
using the pinned MNE 1.9 readers. Metadata normalization preserves source events,
annotations, channel/sample identity, acquisition metadata and original subject
fields. Internal BIDS identifiers must not replace canonical project identity
or leak into scientific outputs. Channel selection precedes RAM/memmap preload.

Unicorn uses a normalized BDF copy with the same packed signal samples. Only
the existing reviewed `?V` physical-dimension exception is corrected to `uV`
when its complete source contract matches. The original BDF is also retained
under `sourcedata`; source and normalized-copy identities remain distinct.

BVRF arbitrary calibrated float64 values cannot generally be preserved by
BrainVision float32 export. This route therefore preserves the original BVRF
companions in `sourcedata` and publishes an explicitly labeled FIF64 derivative
loaded by MNE. It is a precision-preserving import exception, **not standard
raw EEG-BIDS compliance**. Template/recorded geometry and FPVS marker policies
are applied at the shared admission boundary; import performs no filtering,
resampling, rereferencing, or interpolation. Full BIDS study import/export,
unsupported acquisition configurations, and physical hardware qualification remain separate
features; a readable recording does not enable unqualified spatial methods.

See the [conceptual map](hardware-pipeline-studio-roadmap.md#intended-conceptual-map-canonical-eeg-recording)
and [multi-hardware implementation plan](../exec-plans/active/multi-hardware-bids.md).

## Supported project routes

Confirmed project hardware selects upstream admission: `biosemi` retains the
existing ActiveTwo64 contract; `biosemi_active_three` uses recording-owned
geometry and explicit reference/channel settings; `brain_products` accepts the
documented BrainVision formats; `unicorn` uses its registered eight-channel
native-rate policy. BDF extensions never select a manufacturer or BioSemi
generation. All four routes return MNE Raw and an immutable `RecordingContract`
to the shared numerical engine. No manufacturer-specific numerical pipeline is
introduced.

ActiveThree BDF receives the source's calibrated units/sample rate, declared
channel roles, and recorded coordinates or an explicitly selected supported
template. The default preserves the recorded reference until final average
reference; selected recorded reference channels are optional. No 64-channel
limit or BioSemi64-calibrated QC is inherited. This does not add arbitrary
sensor types, multi-subject splitting, or physical device qualification.
[BioSemi's BDF documentation](https://www.biosemi.com/faq/file_format.htm)
confirms the shared container format, not a shared montage/reference policy.

## Brain Products project route

`Main_App.io.load_utils` dispatches `.vhdr` and `.bvrh` through `hardware_loader`
only for a confirmed Brain Products project. BioSemi loader arguments and
legacy behavior are preserved. `brain_products` adapts calibrated vendor data
into MNE Raw and a canonical numeric stimulus channel; `brain_products_files`
validates companion ownership and `brain_products_bvrf` owns streaming BVRF 1.0.
The pinned MNE 1.9 reader owns BVCDF under the MNE-BIDS import boundary.

Header-based discovery never treats `.eeg`, `.vmrk`, `.bvrd`, `.bvrm`, or `.bvri`
as independent participants. `recording_sources` includes companions in preflight,
preprocessing-cache, and ledger freshness. Prefetch validates all source bytes
and releases owned memory maps. Project channel-type overrides precede geometry
resolution. Recorded coordinates or an explicitly chosen template establish
spatial availability; absent coordinates remain absent.

The raw/cache/source-derivative geometry remains recording-owned. Downstream
spectral cohorts use the separate `processing.recorded_cohort_geometry` contract
to retain each source's coordinates while comparing compatible channel/policy
identities. Never replace a participant's digitization with another participant's
geometry or interpret the cohort identity as a spatial montage.

All numeric Stimulus/S markers are preserved, including oddball markers outside
the condition map. Brain Products event detection uses `initial_event=True` and
`consecutive=True` so sample-zero and adjacent descending codes survive.
Response and segment annotations cannot silently become condition codes.
Reviewed marker plans and existing resampling/crop guards still apply.

See the [user hardware guide](../../user/reference/brain-products.md) for format
limits and primary sources. These software contracts do not qualify physical
amplifier gain or stimulus latency.


This page documents the BDF loader contract for the active Main App processing
paths. Refactors must preserve supported file type, memmap paths, channel
typing, montage behavior, logging, and return semantics unless a future task
explicitly changes the processing pipeline.

For new devices or montages, also read the
[hardware, pipeline, and Studio roadmap](hardware-pipeline-studio-roadmap.md).
The standalone inspector and temporary Unicorn reader below remain evidence
owners. Production Unicorn admission adds the explicit project and processing
contracts described here rather than changing inspection into a QC approval.

## Entry Contract

### Acquisition Inspection Foundation

`Main_App.io.load_utils.inspect_eeg_recording(path, settings,
event_authority=...)` is a separate **read-only inspection result**, not a Raw
loader or a QC release. It composes `io.acquisition_profiles`, `io.bdf_format`,
and `io.recording_events`. This evidence API retains
`scientific_processing_allowed=False`: callers cannot treat it as hardware
qualification. Confirmed production projects instead enter through
`bids_loader`, whose mobile admission adapter validates the source and adds
the generic processing contract. Physical qualification questions remain in the
[Unicorn plan](../exec-plans/active/unicorn-hybrid-black-support.md).

- The immutable built-in registry separates format, acquisition, montage,
  event decoding and capability definitions. Unknown IDs/versions and incompatible
  combinations fail. Missing acquisition settings resolve internally as legacy
  BioSemi without modifying saved settings or adding fingerprint fields.
- Explicit Unicorn contracts select `unicorn_hybrid_black` / `unicorn8`, version
  `1.0`, native 250 Hz, eight-channel `average_scalp`, no resampling/interpolation,
  and unavailable normalized kurtosis/spatial capabilities. Production admission
  enforces these constraints before the shared numerical stages.
- The factory `EEG 1`-`EEG 8` mapping is opt-in with an evidence reference.
  Anatomical labels are never inferred from channel count. Template-coordinate
  source metadata and runtime coordinate identity remain explicitly template-based;
  they do not claim measured headset positions.
- Byte inspection retains signal ranges/units, native samples, source SHA256,
  fractional record origin and BDF+ TALs, including notes/timekeeping. It checks
  record sizes and timestamps before any MNE flattening. BDF+D is inspectable but
  blocked; BDF+C gaps, malformed times and truncated data cannot enter analysis.
- Each nonzero validated Unicorn Status sample is one event, including adjacent
  repeats/decreases. Annotations use explicit numeric or named mappings, never
  alphabetical IDs. Marker events are sorted chronologically while original
  annotation storage order and descriptions are retained. Authority is explicit;
  dual-source conflicts, off-grid times and native-sample collisions fail.
- Original units, including `?V`, remain unchanged in the format evidence.
  The explicit built-in Unicorn profile alone resolves the versioned
  `io.unicorn_units` interpretation described below. Valid file structure and
  matching markers cannot establish wireless sample integrity, hardware amplitude
  calibration, raw logger configuration, or physical onset timing.
- Inspection summaries are detached, path-free evidence, with a separately named
  inspection fingerprint. They do not replace preprocessing/ledger fingerprints
  and cannot authorize cached processing or downstream analysis.

Tests independently generate BDF/BDF+ format cases and cross-check a known EEG
scale with MNE. A sanitized 426-event receipt binds the original test-signal BDF
checksum and exact marker positions; it is not participant EEG or hardware
qualification. A third test-only profile reaches the same inspector without
device-name dispatch. Production acceptance uses the separate supported-hardware
loading/pipeline tests and the [current plan](../exec-plans/active/multi-hardware-bids.md).

### Unicorn-Only Unit Interpretation

The user-authorized `unicorn_recorder_eeg_units` v1.0 policy belongs to
`Main_App.io.unicorn_units`, not the format parser or shared BioSemi loader.
It rejects absent/default, explicit BioSemi, unrelated, and modified acquisition
definitions. No filename, channel-count heuristic, global MNE setting, or
fallback can select this correction.

The literal `?V` exception requires the observed Recorder 1.24.02 pattern:
all eight `EEG 1`-`EEG 8` channels explicitly mapped, native 250 Hz, physical
ranges -750000 to 750000, full signed 24-bit digital ranges, and only the
observed optional CNT/VALID/DT/Status auxiliaries. Any mismatch remains
unqualified. The manufacturer's Recorder documentation identifies EEG as
microvolts; the retained BDF/CSV comparison supports this software unit rule,
not absolute hardware gain calibration. Correctly labelled `uV`, `mV`, and `V`
use ordinary prefix conversion; unknown units fail closed.

`inspect_eeg_recording(..., include_eeg_samples=True)` optionally retains the
eight original digital EEG signals during the same source-checked read and
returns `eeg_samples_volts` in source order. The conversion applies the BDF
slope **and offset**, then the physical-to-volts factor exactly once. It never
accepts MNE-scaled data as input, mutates a Raw, scales telemetry or Status,
changes source bytes, or writes a project/cache artifact. Repeated reads derive
fresh values from original integers. Nonfinite/unrepresentable calibration and
discontinuous sample views fail explicitly. Without this opt-in, inspection
continues to materialize only Status.

The detached inspection summary/fingerprint retains policy ID/version, source
and interpreted units, per-channel factors, conversion order and source hash.
The sample view remains inspection-only: it cannot authorize processing, QC,
or cache reuse. Both the context-owned Raw adapter below and production BIDS
admission consume the same versioned interpretation. BioSemi identities,
preprocessing and the shared volts-to-microvolts FFT conversion are unchanged.

### Unicorn MNE Reader

`Main_App.io.load_utils.open_unicorn_recording_raw(path, settings,
project_root=..., event_authority=..., preload=False)` yields a context wrapper
with `raw`, original `inspection`, and detached `reader_provenance`. Supported
preload choices are `False` (lazy), `True` (RAM), and `"memmap"` (owned disk
preload). All three use stock MNE BDF reading, with EEG in volts. Keep Raw and
any disk-preloaded use inside the context. Invoke this file-I/O boundary from a
worker, not a GUI callback.

MNE 1.9 cannot overwrite nonempty `?V` units through its `units` argument, and
cannot lazily consume a file-like header overlay. This adapter therefore creates
one exclusive, run-owned copy beneath the caller's absolute active project root:
`.fpvs_processing/unicorn_reader/reader-*/reader.bdf`. It verifies the source
and copied bytes against the original inspection SHA256, then changes only
the eight approved dimension fields to `uV` using the same open descriptor.
Original recordings are never opened for writing. Correctly labelled inputs
are copied without header changes. MNE performs physical calibration and SI
conversion itself; no post-read rescaling or private MNE calibration state is
used. Temporary file and directory identities are checked before MNE opens them.

The adapter rejects non-Unicorn contracts before I/O and rejects structural,
unit, mapping and event inspection errors before MNE. Every ordinary channel
must share native 250 Hz; mixed-rate telemetry cannot cause implicit MNE
resampling. Only the eight mapped EEG channels, CNT/VALID/DT auxiliaries and
the configured Status role are accepted. Source channel order and labels are
preserved, auxiliaries are `misc`, and Status is `stim`. No reference or montage
is applied by this unit-correction adapter. Canonical events and original
BDF+ timing evidence remain authoritative rather than a fresh `find_events`
call or an inferred time origin.

The wrapper retains `scientific_processing_allowed=False` and unresolved
acquisition-evidence issues. Its provenance binds the original source SHA256,
inspection fingerprint, unit policy, adapter/MNE versions, normalized-copy
SHA256 and exact patched fields. `raw.filenames` points to the temporary reader
copy and must not replace original recording identity. These receipts are not
production cache/checkpoint eligibility.

Context exit closes Raw and explicitly releases an owned memmap before removing
only `reader.bdf`, `samples.dat` and their uniquely owned directory. Error paths
retain traceback locations while releasing incomplete MNE construction frames
that can otherwise keep Windows mappings open. Redirected/replaced directories
are never recursively removed. `io.mobile_eeg.open_mobile_import_source` uses
this context during production Unicorn BIDS preparation. Nonfinite telemetry
fails. Identity-scaled unitless telemetry additionally requires VALID=1 and
consecutive integer CNT samples; other calibration/units and absent telemetry
remain explicitly unverified and unchanged. No rounding, inferred rollover or
wireless-loss reconstruction is permitted. It freezes canonical sample-wise events and
provenance before the temporary reader is released. BIDS reuse reconstructs
those facts, not temporary filenames. The shared processing contract requires
native 250 Hz, eight channels, and no resampling or interpolation. The generic
event extractor preserves adjacent equal codes without interpreting them as
one BioSemi-style edge.

### Production BioSemi Entry

`Main_App.io.load_utils.read_bdf_sampling_rate_hz()` probes only fixed and
signal headers for automatic analysis-window setup. It returns an exact rate,
validates BDF structure and a common non-annotation data/stim grid, and reads no
EEG samples or MNE Raw. Malformed headers and file-access errors propagate.
Existing not-started recordings retain their explicit exclusion policy. The
processing setup rejects nonterminating fractional rates that cannot retain
their exact identity through the current runtime's decimal float grid.

`load_eeg_file(app, filepath, ref_pair=None, first_n_channels=None,
stim_channel=None, electrode_mapping_profile=None, electrode_montage=None, *,
preload_path=None, preload_in_memory=False, acquisition_settings=None)` expects:

- `log(message, ...)` for status and warning messages.
- An existing absolute active project root in explicit
  `acquisition_settings["project_root"]` or `app.currentProject.project_root`.
  Native EEG reads cannot fall back to the current working directory.
- Optional `currentProject.preprocessing` with `ref_channel1`,
  `ref_channel2`, `stim_channel`, `electrode_montage`, and
  `electrode_mapping_profile` values.
- Optional `settings.get(section, key, default)` fallback access.

The canonical active import path is
`Main_App.io.load_utils.load_eeg_file`.

Condition-aware preflight QC has a separate opt-in entry point:

```python
with Main_App.io.load_utils.open_preflight_eeg_file(
    app,
    filepath,
    ref_pair=(ref1, ref2),
    first_n_channels=64,
    stim_channel=stim,
    electrode_mapping_profile=mapping_profile,
    electrode_montage="biosemi64",
    acquisition_settings={**project_settings, "project_root": str(project_root)},
) as raw:
    ...
```

This context manager opens BDF data with `preload=False`, applies the same
channel-subset, EXG/stim typing, and geometry contract, and always closes the
lazy Raw on exit. It never calls `load_data()` and never creates the normal
full-recording float64 memmap. All lazy sample reads must remain inside the
context. The explicit `stim_channel` argument keeps event discovery and the
header subset on the same configured channel; when omitted, the normal host
resolution and `Status` fallback still apply.

Preflight caches live under the active project's
`.fpvs_processing/preflight_qc/v7_analyzed_condition_scope/`. Recording results
are keyed by effective recording settings; `events/` retains exact integer
source-event samples and `occurrences/` retains numerical evidence for exact
analyzed occurrences. Current marker planning and review provenance are rebuilt
around reused evidence. Schema-2 payload checksums, source-stat checks, channel
geometry, method versions, thresholds, and exact sample bounds govern reuse;
unusable entries trigger ordinary recalculation. Excluding one condition can
reuse the remaining occurrences through the existing aggregation function.
Unchanged condition review skips a redundant rescan; changed sources, marker
decisions, or condition choices still rebuild the project-wide result. Timings separate
condition reads, channel metrics, spectral calculation, and spectral-worker wait.

The implementation lives in `Main_App.io.load_utils`, alongside canonical
`Main_App.io.eeg_geometry`. `Main_App.Shared.load_utils` is a same-object
compatibility alias, preserving historical imports and monkeypatches.
`src/Main_App/Legacy_App/load_utils.py` and the old PySide6 backend loader path
remain deleted. Do not duplicate loader logic.

## Interactive QC Source Prefetch

After the signal-health scan, opening step 2 starts `QcSourcePrefetch` through
`Main_App.workers.qc_source_prefetch_worker` in a background QThread. Its
constructor performs no filesystem I/O. The producer sequentially decodes
complete selected-channel sources while the user reviews markers, conditions,
electrodes, and possible recording exclusions. It does not filter, resample,
score kurtosis, or apply any review decision before step 6.

Each run owns a unique `qc-source-*` directory under the active project's
`.fpvs_processing/`. The full loader's optional keyword-only `preload_path`
reserves a new absolute destination exclusively; ordinary callers retain the
existing per-process system-temp path. By default the coordinator keeps
disk-backed float64 Raw objects, caps staging at 16 GiB, and reserves 2 GiB of
free disk space. The explicit RAM-preload option instead retains arrays without
disk staging and caps them at 25% of available RAM. Budget limits and failed
preloads fall back to normal step-6 loading.

Step 6 stops queued speculative loading and adopts completed sources once,
checking the current source content hash, identity, and effective loader
settings. Reuse compares normalized loader arguments and a frozen acquisition
identity separately from the full project settings forwarded to BIDS admission.
Hardware, channel roles, montage, reference, and qualification changes reject
reuse; downstream filter or review settings and equivalent loader aliases do
not invalidate unchanged raw samples. Participant exclusions still control
whether a source may be staged or lent. Source content is bound before/after preloading, so replacing a file
while retaining its size/timestamp cannot reuse old samples. An active
source load may finish; unrelated pending sources use the normal loader without
waiting behind that load. While a preload is active, at most one foreground
kurtosis job starts. The scanner retains its current geometry, event, analysis
span, sample-hash, and review-authority checks. It takes exclusive mutation
ownership and releases each source in its per-file finally block. A repeated
scan never receives an already modified source.

The producer remains alive until the QC workflow exits. Cancellation and all
review exits request cleanup off the GUI thread; a responsive Qt event loop
waits for the active load and cleanup before downstream processing starts.
Consumed maps are removed after use, and remaining maps/run directories are
removed on normal completion, cancellation, or error. Cleanup rejects redirected
paths and never targets the project's persistent prepared-kurtosis checkpoints,
original recordings, exports, or the repository's MNE/fsaverage cache.

## BioSemi File And Path Behavior

- The BioSemi route accepts `.bdf`; confirmed Brain Products routes use the
  `.vhdr` and `.bvrh` entrypoints documented above.
- Unsupported extensions show a user warning and return `None`.
- Before MNE opens a BDF, the loader reads the fixed BDF header. A BioSemi
  file with `num_records == 0` whose file size is only the declared header
  length is treated as a recording-not-started placeholder: the loader logs an
  exclusion warning and returns `None`, while the process runner reports the
  file as `status="excluded"` instead of a processing error.
- Production BDF reads use the project-local BIDS import and MNE-BIDS reader,
  then select channels while lazy before optional RAM/memmap preload. The
  native MNE BDF decoder still supplies calibrated samples. The older guarded
  full-constructor `bdf_preload` optimization is no longer the production
  full-load entry point; keep native-reader internals inside the I/O boundary.
  Preflight uses `owned_bdf_lazy_read` only around its existing `find_events`
  and condition `get_data` calls, inside the existing I/O semaphore. It accepts
  one exclusively owned native lazy Raw, rejects local method overrides, and
  pins the native read/event entries and dependencies. The context suspends
  during the unchanged native call and restores the binding in `finally`,
  before annotation fallback or return; no persistent reader or owner remains.
  Small reads and unsupported state keep the native decoder. Copying or sharing
  Raw objects inside this internal read context is outside its ownership contract.
  Preflight event extraction alone requests `status_only=True`. With one native
  Status slice, a common sample grid, no annotation channel and no projection or
  compensation, it unpacks only that channel's integers in a temporary full-shape
  buffer. Every physical byte is still read with the native count and grouping;
  downstream calibration, masking and native file-reader bodies are unchanged.
  A short received count populates every received integer before native reshape,
  preserving truncation errors and cursor behavior. Other selections use the
  direct native class reader. This dispatch uses no additional NumPy selection
  helpers, and private function copies release before the owned Raw escapes.
  Whole-pipeline exact proof remains required before performance acceptance.
- Raw BDF loading remains disk-preloaded by default. A project-only,
  default-off Settings > Experimental > Performance switch uses MNE
  `preload=True` for preflight QC, interactive QC prefetch or its scanner
  fallback, and processing cache misses. It creates no full-recording memmap;
  a memory allocation failure in the ordinary loader is a load failure, never
  a silent fallback to disk. RAM QC prefetch is bounded to 25% of available
  memory and releases its buffers at the existing exclusive handoff/cleanup
  points. Preprocessed FIF cache hits and the separate lazy preflight context
  retain their established loading behavior.
- Only the explicit preflight context uses `preload=False` for on-demand
  condition reads.
- Preflight keeps ordinary condition intervals in RAM. An interval exceeding
  256 MiB is copied in 10-second reads to an automatically removed,
  condition-only float64 temporary memmap; the complete BDF is never preloaded
  or mapped by this path.
- `.set`/EEGLAB loading is intentionally unsupported in the active toolbox.
- Disk-backed preload files are created under
  `tempfile.gettempdir()/fpvs_memmap/pid_<process-id>-<random>/<unique-id>_raw.dat`.
  `Main_App.io.memmap_paths` exclusively creates one private directory per
  process and validates its identity on reuse. Loader, worker initialization,
  and per-file cleanup use this same owner; an existing guessed PID directory
  is never reused. Cleanup rejects redirected containers and retains live maps.
  Dead-process cleanup recognizes both historical and private PID names.
- The RAM switch is an execution/storage choice and must not change the
  processing fingerprint or preprocessed-Raw cache key. Confirm in a visible
  1280x900 project Settings session that the switch is visible under
  Experimental > Performance, starts off, Cancel discards it,
  Save persists it for that project, and a cache-miss run uses RAM only while
  enabled. Loader logs report `preload_mode='ram'` or `'disk'`. Check that the
  QC prefetch creates no `qc-source-*` disk staging
  directory in RAM mode. Qt execution remains CI-only locally.
- Loading does not resample data.
- Before either full or reduced loading, the loader performs a header-only BDF
  read and validates the complete acquisition geometry contract. A reduced
  load is never used to hide an incomplete or ambiguous full header.
- When `first_n_channels` is provided, the loader retains the first N members
  of the frozen canonical BioSemi64 sensor order, plus the selected reference
  pair and resolved stim channel. The `include=` list preserves the source
  file order, so no recorded signal is reassigned or reordered.
- Header validation, mapping, or subset failures are load failures. The loader
  does not fall back to a permissive full-file load.

## Channel Behavior

- The stimulus channel resolves from project preprocessing settings, app
  settings, then defaults to `Status`.
- The full header must contain exactly the 64 supported BioSemi scalp
  identities, the two selected and distinct EXG reference signals, and the
  configured stimulus channel; any other acquisition channels must be supported
  EXG1-EXG8 auxiliaries. Blank or case-insensitive duplicate names, missing
  scalp/reference/stim channels, mixed label schemes, and unsupported custom
  channels fail validation.
- `EXG1` through `EXG8` are the only supported auxiliary electrode labels.
  The selected pair, normally `EXG1` and `EXG2`, remains typed as EEG and
  coordinate-free until the initial reference is applied; other present EXG
  signals are typed as `misc`.
- `CMS` and `DRL` are not recorded scalp or reference data channels in this
  contract. A BDF header that presents either name as a data channel fails
  validation.
- The resolved stimulus channel is typed as `stim` when present.
- EXG and stimulus matching is case-insensitive, while actual channel casing is
  preserved.
- The active process runner requests all 64 canonical scalp identities plus
  `EXG1`/`EXG2` as the usual selected reference pair and the resolved stim
  channel. Membership is resolved from the validated mapping rather than the
  first 64 header positions. This avoids loading unused BioSemi `EXG3` through
  `EXG8` channels before preprocessing drops non-selected EXG channels.

## BioSemi64 Geometry And Errors

- `Main_App.io.eeg_geometry` is the public geometry surface. Its shared owner
  freezes the 64 anatomical names, MNE head-frame coordinates, geometry
  version, coordinate fingerprint, canonical and retained scalp-set
  fingerprints, mapping profile, and composite geometry fingerprint.
- The project-owned `electrode_montage` has one supported value:
  `biosemi64`, displayed as **BioSemi ActiveTwo 64**. The loader applies MNE's
  cached `biosemi64` montage with `on_missing="raise"`, `match_case=True`, and
  `verbose=False`, then verifies every retained scalp coordinate against the
  canonical head-frame coordinates.
- The default `anatomical_labels` mapping accepts the complete canonical scalp
  labels case-insensitively and normalizes their casing without moving data.
  `biosemi64_1020_ab_v1` explicitly maps A1-A32/B1-B32 to the standard
  BioSemi 64-channel 10/20 wiring. It does not describe BioSemi ABC/equiradial
  layouts and must never be selected for those or for a custom ordinal layout.
- The same geometry function and identity are used by lazy preflight and full
  loading. Each returned Raw carries a runtime identity that preprocessing
  validates again after any intentional channel limit.
- Unsupported montage or mapping identifiers, noncanonical coordinates, and
  missing or ambiguous header identities are hard load failures. Load failures
  log `!!! Load Error <filename>: <error>`, try to show a user error, close any
  opened Raw, and return or yield `None`. Recording-not-started placeholders
  remain a separate exclusion: they log `[LOADER EXCLUDED]` and are excluded
  from processing and analysis.

## Preservation Rules

- Do not change supported extension, memmap directory shape, strict full-header
  validation, canonical channel identities, channel subset/order policy,
  channel typing policy, geometry identity, montage arguments, logging
  messages, or `None` return behavior without an explicitly scoped behavior
  change.
- Do not restore `.set` support unless it is a new explicitly scoped feature.
- Do not introduce Tkinter, CustomTkinter, or CTkMessagebox; user warnings and
  errors must use `Main_App.gui.user_messages`.
- Keep all active runtime callers loading through `Main_App.io.load_utils`
  unless the loader contract is intentionally replaced and covered by focused
  tests.

## Online Verification

- BioSemi distinguishes its standard headcap layouts from ABC/equiradial
  layouts and publishes its standard 64-channel cap coordinates:
  https://www.biosemi.com/headcap.htm
- BioSemi documents connector pin/electrode ordering, which is why an A/B label
  needs an explicitly named wiring profile rather than ordinal inference:
  https://www.biosemi.com/faq/Help/help_P.htm
- MNE documents `biosemi64` and `standard_1005` as separate built-in montage
  definitions:
  https://mne.tools/stable/generated/mne.channels.make_standard_montage.html
