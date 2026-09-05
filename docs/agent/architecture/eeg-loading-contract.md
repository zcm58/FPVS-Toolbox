# BDF Loading Contract

This page documents the BDF loader contract for the active Main App processing
paths. Refactors must preserve supported file type, memmap paths, channel
typing, montage behavior, logging, and return semantics unless a future task
explicitly changes the processing pipeline.

## Entry Contract

`load_eeg_file(app, filepath, ref_pair=None, first_n_channels=None,
electrode_mapping_profile=None, electrode_montage=None)` expects the host
object to provide:

- `log(message, ...)` for status and warning messages.
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

The implementation still lives in `Main_App.Shared.load_utils` during this
layout migration slice. Do not change that implementation as part of
import-surface moves.

`src/Main_App/Legacy_App/load_utils.py` and the old PySide6 backend loader path
have been deleted. `src/Main_App/Shared/load_utils.py` is kept as the temporary
implementation module and must not duplicate logic elsewhere.

## File And Path Behavior

- Supported extension is `.bdf`.
- Unsupported extensions show a user warning and return `None`.
- Before MNE opens a BDF, the loader reads the fixed BDF header. A BioSemi
  file with `num_records == 0` whose file size is only the declared header
  length is treated as a recording-not-started placeholder: the loader logs an
  exclusion warning and returns `None`, while the process runner reports the
  file as `status="excluded"` instead of a processing error.
- BDF files load through `mne.io.read_raw_bdf(...)`.
- The normal processing loader remains disk-preloaded and unchanged. Only the
  explicit preflight context uses `preload=False` for on-demand condition reads.
- Preflight keeps ordinary condition intervals in RAM. An interval exceeding
  256 MiB is copied in 10-second reads to an automatically removed,
  condition-only float64 temporary memmap; the complete BDF is never preloaded
  or mapped by this path.
- `.set`/EEGLAB loading is intentionally unsupported in the active toolbox.
- Disk-backed preload files are created under
  `tempfile.gettempdir()/fpvs_memmap/pid_<process-id>/<file-stem>_raw.dat`.
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
  errors must use `Main_App.Shared.user_messages`.
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
