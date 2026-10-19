# QC-13: Project Expected Analyzed Cycles

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-11, and QC-12 when
executing this action.

**Status:** implemented on the active QC branch. Each project owns one positive
integer expected analyzed oddball-cycle count and source. FPVS Studio imports
and manual entry normalize into the same exact protocol, and processing keeps
analyzed cycles, marker counts, usable spans, and derived seconds distinct.

**Timing correction completed, 2026-09-05:** replaced nearest-target-sample
crop rounding with v3-compatible MNE stimulus sampling-window alignment,
verified against actual boundary markers before scoring and after cache reuse.
Exact declared sample counts, original source coordinates, continuous
preprocessing order, and correct relative sample origins remain intact.
Unverifiable alignment fails; cache and ledger versions now invalidate old
windows. Verification: 64 real-MNE alignment cases cover marker phase, pulse
width, 256/512-Hz and noninteger downsampling ratios, nonzero origins, and
120-second windows. The processing gate passed 582 tests (one skipped), and
28 kurtosis review/runner integration tests passed. The repo precommit gate
remains blocked only by eight pre-existing local-path findings in `outputs/`.
No local Qt execution was performed. Visible smoke: process one known BDF at
256 Hz, verify the declared duration and workbook completion, then repeat via
the cache and confirm unchanged crop metadata. FullFFT storage redesign remains
a separate future change; spectra were not truncated by this correction.

## Accepted Behavior

### Full-length setup follow-up, 2026-10-06

Implemented. The user approved automatic planned-window setup from Studio and
duration-first manual entry. Keep one planned length per project. Studio's
sequence count times oddball repeats gives presentations, whose first-to-last
oddball markers bound one fewer complete cycle. Resolve the largest complete
cycle count inside that planned bound against both source and effective target
sampling grids; do not infer the target from a participant's available length.
Persist the input policy and resolved cycles in the canonical protocol identity.
Existing explicit cycle protocols retain their numerical identity. Manual
duration entry previews the actual compatible duration; advanced cycle entry
remains available. Header discovery reads no EEG signal data.

Shorter-window analysis and common-segment analysis are separate secondary
features, outside this change. Preserve the full-length mismatch/review gate,
preprocessing order, averaging, FFT normalization and spectral eligibility.
Verify import round trips, differing project lengths, exact source/target grids,
invalid/mixed Studio counts, legacy identity, GUI parser/draft behavior and
unchanged rejection of short recordings. Local Qt execution remains disabled;
register coverage and document a visible smoke route.

Implementation files for this follow-up:

- `src/Main_App/projects/analysis_window.py`, `frequency_protocol.py` and
  `fpvs_config_import.py`: exact planned inputs, one canonical versioned target
  and strict current Studio schedule imports.
- `src/Main_App/gui/project_protocol.py`, `settings_panel.py` and
  `processing_inputs.py`: Duration/Automatic/Advanced setup and project-wide
  sampling-grid resolution before QC and artifact classification.
- `src/Main_App/io/load_utils.py`:
  canonical header-only BDF sampling-rate discovery, with explicit failures.
- `tests/project_io/test_analysis_window.py` and
  `test_fpvs_config_import.py`; `tests/processing/test_analysis_window_setup.py`,
  `test_project_frequency_protocol_inputs.py` and `test_shared_load_utils.py`;
  `tests/gui/test_project_protocol.py`,
  `test_protocol_condition_markers_static.py`, `test_gui_preproc_dialog.py` and
  `test_processing_failure_routing_static.py`: protocol, import, setup and
  existing orchestration regression coverage. The two new test files are
  registered in `.agents/verification.toml`; Qt coverage uses the existing
  registry and was not executed locally.

Project-I/O, GUI, EEG-loading, FFT-crop and methods-reporting contracts document
these rules. The visible smoke route is in
`docs/agent/architecture/gui.md`. Existing RAM-preload edits were preserved.

Verification completed, 2026-10-06: the repository precommit gate passed all
audits, changed-file Ruff and compilation, and 5,391 tests (two skipped;
73 existing warnings). Both actual current Studio FPVS Oddball and Cognitive
Load FPVS exports passed import, source-grid resolution, save and reopen checks.
Independent review confirmed project-wide Single-mode discovery, synchronized
top-level/nested protocol identities, and early rejection of runtime-incompatible
rational source rates. The existing static registration harness now loads the
real setup helper. No local Qt execution, hardware/PsychoPy launch, scientific
method change, shorter-window implementation or installer rebuild was performed.

1. Extend the project frequency protocol with a positive integer
   `expected_analyzed_oddball_cycles` and its source (`fpvs_studio_import` or
   `manual`). Define it as complete cycles in the intended FFT span, equal to
   the oddball target's FFT-bin index `k = f_oddball * N / fs`; never treat it
   as an oddball-presentation or trigger count.
   Do not add per-condition lengths. Show resolved seconds as
   `cycles / oddball_rate`; duration-first entry and Studio Auto are the basic
   controls, while cycles remain an advanced saved value.
2. Map current Studio's authored sequence/repeat fields using the documented
   first-to-last marker rule into the same normalized protocol. Validate the
   common planned length and retain the input policy/sampling grids. Do not
   create a second runtime protocol or infer a target from generic event counts.
3. Require a resolved positive count from Auto, duration or advanced cycle
   entry during setup before processing. Changes
   invalidate affected preprocessing, FFT/BCA, QC, harmonic-selection, and
   Stats artifacts through the shared protocol fingerprint.
   For an existing project with no field, recover a candidate only from
   trustworthy project/run provenance, show its source and derived duration,
   and require explicit confirmation before the next processing run. If no
   trustworthy value exists, require manual entry. Preserve old outputs with
   their historical identity; never relabel them as produced from the newly
   confirmed value.
4. Before processing, compare every selected recording, condition, and
   repetition's marker-derived usable span with the declared target. Identify
   the limiting repetition. Cap longer spans to the declared target; never pad
   a short span or let a cohort-majority heuristic redefine the protocol.
5. A shorter or incompatible span is an explicit protocol mismatch requiring
   resolution through the existing review workflow before comparable group
   outputs can finalize. Report expected and available cycles, markers, sample
   span, derived seconds, and exact-bin compatibility.
6. Keep marker-derived boundaries and QC-12's exact FFT-bin rule authoritative.
   The strict-majority grid may remain a secondary corruption/legacy check,
   but the declared project target becomes the reference for managed projects.
7. Preserve raw marker count, deduplicated marker count, marker-interval count,
   realized sample count/duration, and realized analyzed cycles separately for
   each repetition. For example, 145 boundary markers delimit 144 complete
   cycles; exact-bin flooring may retain fewer. Do not aggregate unrelated
   repetition minima/maxima into one apparent interval.

## Owners and Acceptance

Implement project schema/import/manual-entry ownership in `Main_App/projects/`
and the project setup GUI. Route the expected target through preflight and
`Main_App/processing/fft_crop_utils.py`, processing provenance, FullFFT grid QC,
review dialogs, caches, and fingerprints. Preserve the shortest-common-span
calculation only after each repetition has been checked against the declared
target; do not let one short repetition silently reduce valid siblings.

Cover manual and Studio-imported projects, save/reopen, 144 cycles at 1.2 Hz
(120 seconds), 145 markers delimiting 144 cycles, shorter protocols, exact
target spans, extra markers, a short repetition, systematic
truncation, incompatible sample counts, repeated conditions, legacy projects,
protocol edits, and unchanged valid output. Update project-I/O, FFT-crop,
preprocessing, post-processing/export, GUI, and methods-reporting contracts
as part of the implementation. Run focused non-GUI checks and document a visible
GUI smoke path; Qt execution remains CI-only.
