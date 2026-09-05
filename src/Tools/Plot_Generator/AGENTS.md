The Plot_Generator directory contains the embedded PySide6 tool that builds SNR
line plots from Excel files created by the FPVS Toolbox. The Main App GUI is its
only user-facing entry point. GUI adjustments
and minor bug fixes are allowed. Keep processing code modular and under 500 lines
per file. ROI definitions should be loaded from the existing settings using the
neutral utilities in `Main_App.processing.roi_settings`. Plots should be averaged across participants within
each condition and saved to a user-selected output folder.

Current ownership map:

- `plot_generator.py`: Main App-imported embedded compatibility facade that
  preserves patchable worker/thread hooks; it is not a standalone entry point.
- `gui.py`: `PlotGeneratorWindow` page implementation.
- `generation_workflow.py`: condition queueing, QThread worker launch, progress
  aggregation, and participant-exclusion prompts.
- `generation_lifecycle.py`: cooperative cancel/shutdown, navigation locking,
  worker outcomes, and completion/thread-exit handling.
- `generation_outcome.py`: pure worker-payload normalization and
  completion-summary formatting used by the GUI workflow.
- `ui_sections.py`, `ui_actions.py`, `ui_header.py`, `log_dialog.py`, `gui_settings.py`,
  `selection_state.py`, `project_paths.py`, and `manifest_utils.py`: focused
  GUI, settings, selection, and thin shared-project adapters.
- `worker.py`: `_Worker` QObject shell, signals, stop state, timing, run
  orchestration, finished payload emission, and compatibility re-exports for
  older imports.
- `worker_config.py`: `_Worker` constructor payload dataclass.
- `excel_inputs.py`: thin shared participant-identity adapter plus
  frequency-column helpers.
- `full_snr_reader.py`: companion-aware shared workbook session, with the
  direct `.xlsx` XML reader retained for legacy FullSNR/FullFFT inputs,
  selected-frequency parsing, ROI electrode filtering, and load subtimings.
- `data_collection.py`: shared dataset-index consumption, source-data
  collection, and required-sheet failure handling.
- `aggregation.py`: selected ROI resolution, ROI averaging, group curves, and
  unknown-subject warnings.
- `analysis_context.py`: managed-project versus legacy-folder resolution,
  validated batch-index reuse, frozen processing rates, and the active-workbook
  provenance boundary.
- `source_data.py` and `output_interface.py`: in-memory contributor/sample-size
  bookkeeping plus managed analysis-context checks for direct figure output.
- `source_identity.py`: immutable read-time source-workbook snapshots,
  companion array snapshots, fingerprints, and verification of the exact
  contributing artifacts. A declared companion must remain valid throughout
  capture and publication; an Excel spectral notice is never a fallback.
- `spectral_qc.py`: post-processing, report-only electrode-level spectral
  artifact flagging and FullFFT evidence assembly for SNR plots.
- `spectral_qc_workflow.py`: worker-side spectral-QC orchestration and audit
  records without expanding the QObject shell.
- `spectral_qc_alerts.py`: plain-language GUI alert summaries for SNR spectral
  QC findings and whole-participant spectral exclusion candidates.
- `rendering.py`: line and overlay plot rendering plus Matplotlib `Agg`
  configuration; `render_naming.py` owns widget-free, collision-safe artifact
  stems.
- `session_controls.py`: pure canonical session-selector state;
  `session_selection.py` owns its GUI binding and request validation, while
  `session_rendering.py` owns the figure-only fixed-order interpretation caveat.
- `session_aggregation.py`, `session_workflow.py`, and `session_rendering.py`:
  recording-keyed group/session aggregation, worker-thread collection, and
  stable-group faceted session figures.

v2.1 project contract:

- Repeated-session projects must make the plotted dimension explicit. Ordinary
  condition plotting selects exactly one canonical session; session comparison
  selects one condition and two canonical sessions. Never pool repeat visits
  in a participant-keyed dictionary.
- Repeated-session curves join source data through canonical `recording_id` and
  require stable `group_id`, `session_id`, session label, and `visit_index`.
  Missing identity is a hard stop; do not infer it from workbook names or
  folders.
- Session figures stack stable groups vertically in one journal-width column
  and overlay sessions within each group. Each group panel uses the normal SNR
  figure width and height allocation. Show participant `n`, visit indices, and
  the fixed-order phase/order/time confounding caveat in the figure only; omit
  the caveat from the compact GUI controls.

- `Main_App.projects.dataset_index` is the sole owner of processed-workbook
  discovery and participant/group identity. Plot Generator may keep thin
  compatibility wrappers, but it must not parse `project.json`, infer group
  membership from paths, or maintain a separate workbook scanner.
- `project.json` is canonical for group assignments. Prefer participant
  `group_id` and resolve labels/folder names through `project.groups`; legacy
  participant `group` values are compatibility input only.
- In multi-group project mode, the SNR Plots input folder should come
  from the project manifest's resolved Excel subfolder. Do not let saved
  SNR Plots `input_folder` settings override that canonical project root.
  Group Options should only activate when that canonical Excel root is selected.
- Multi-group plotting is a one-condition, group-overlay workflow. The group
  overlay is mandatory for canonical multi-group projects; hide the condition
  overlay checkbox and never emit an implicit pooled all-groups curve. The A/B colors, custom legend
  labels, and peak labels map to the first and second selected groups; groups
  three and higher use deterministic automatic colors, distinct marker shapes,
  and their canonical display labels.
- Group-overlay legends show the number of participants contributing finite SNR
  values to each ROI as `n=...`. A selected group with no usable data for an ROI
  is named in the log and completion warnings and omitted from that figure. If
  every selected group is empty for an ROI, skip the figure rather than
  rendering a pooled all-participant curve.
- Filter intentionally unselected groups before all workbook and spectral-QC
  reads. Track those workbooks as internal dispositions and log them as
  information, not completion warnings.
- Record project-index participant-condition exclusions as structured,
  noncontributing internal dispositions even though they are intentionally
  absent from the active workbook cohort.
- Treat every non-finite FullSNR value (`NaN`, `+inf`, or `-inf`) as missing for
  electrode, participant, and group means.
- Read already-calculated FullSNR from the declared NumPy companion when
  present. Never recreate it from FullFFT. Both spectral sheets in a plot run
  must use the captured input snapshot, and source checks must validate the
  workbook's same-directory companion declaration as well as workbook bytes.
- Read processing-owned Spectral Eligibility through the shared condition
  companion reader. Include that companion in captured and verified source
  identities; a missing or invalid declaration must block publication rather
  than fall back to a workbook notice. Old Excel-only inputs remain readable.
- Group-overlay PNG/PDF pairs append `_group_overlay` to the normal
  `<title or condition> - <ROI>` stem so they cannot overwrite the corresponding
  non-group figure. Preserve normal single-condition filenames.
- Preserve canonical project group IDs behind selected display labels;
  presentation labels must not become group identity.
- Never average FullSNR workbooks positionally when their selected frequency
  grids differ. Skip and report the incompatible workbook instead.
- Never draw a two-condition overlay unless the two accepted condition grids
  also match. Report the mismatch and write no overlay rather than plotting
  condition B values against condition A's physical frequencies.
- Resolve the selected input folder through the shared dataset index before
  reading source workbooks. Managed projects must use the current neutral
  FullFFT provenance's frozen project-protocol rates and exact workbook family;
  missing or stale provenance is a hard stop. For managed projects, derive the
  displayed harmonic annotations from the common processing-owned `Spectral
  Eligibility` domain, excluding presentation-rate harmonics, and never from
  the Stats profile's selected list. The initial x-domain comes from that
  technical domain or the project passband/Nyquist fallback and is clamped to
  the observed FullSNR grid before rendering. Unmanaged folders may retain the
  documented legacy settings fallback but must not borrow exclusions or QC
  output routing from an unrelated active GUI project. Rebuild the managed
  dataset index and revalidate the originally captured rates, technical
  eligibility, cohort, source, frequency-QC, and processing/export identities
  when publishing provenance-bearing artifacts.
- An **All Conditions** run may pass the immutable dataset index built by its
  first worker to later sequential workers. Index construction must remain on
  the worker thread, every worker must still configure its own analysis
  context, and publication-time provenance revalidation must rebuild current
  project state rather than trusting the reused index.
- A managed-provenance failure must return the affected canonical project root
  and actionable stale reason to the embedded page. The page emits the shared
  post-processing-required request; only the Main App shell may show the shared
  modal and launch its existing post-processing pipeline. Plot Generator must
  not create a second post-processing worker or rerun EEG preprocessing.
- Cancellation is cooperative. A visible cancel requests worker stop, suppresses
  queued conditions and normal completion, and keeps generation/navigation
  locked until the worker thread actually exits. Collection, QC, rendering, and
  figure saving need explicit cancellation checkpoints. A cancellation received
  after a figure pair is saved keeps and reports those completed files while
  still suppressing later queued conditions.
- The embedded page must expose a nonblocking active-generation/shutdown
  contract. App close requests cooperative cancellation and is deferred until
  the worker thread has actually exited; never synchronously wait on the GUI
  thread or destroy a running `QThread`.
- Publication output is figures only: write matching PNG and PDF files directly
  to the selected output folder. Do not create per-run subfolders, plotted-
  source spreadsheets, spectral-QC workbooks, or JSON manifests.
- Keep the embedded SNR page free of page-level scrolling. Use the compact
  title-only header, hide idle status/progress rows, and keep detailed run
  messages in the focused generation-log dialog opened by **View Log**.
- Spectral QC is report-only. If no cells can be evaluated because participant
  or shared-electrode coverage is insufficient, record the evidence as
  unavailable with a reason; never present zero evaluated cells as a completed
  negative QC result. Surface flags and evidence limitations in the completion
  warning without creating an export workbook.
- A post-run offer to add whole-participant exclusions may modify only the same
  managed project whose frozen provenance produced the flags. Suppress that
  offer for unmanaged folders, a different browsed project, or missing/mixed
  run identity; never write exclusions into whichever GUI project happens to
  be active. The confirmation defaults to No; an accepted change marks
  frequency-domain outputs stale and routes through the same shared
  post-processing-required action.
- Plot Generator is SNR-line-plot only. Scalp maps belong to the dedicated
  scalp plotting tool; do not reintroduce scalp-map GUI controls, BCA/Z scalp
  data collection, MNE topomap rendering, or Plot Generator scalp helper modules.
- Multi-group Excel files live under
  `<Excel Root>/<Condition>/<Group>/<Participant>_<Condition>_Results.xlsx`.
  Discovery may recurse within a condition folder, but group membership should
  come from `project.json`, not from output folder names.
- When a project manifest provides participant IDs, Excel subject matching must
  prefer those IDs before legacy `P#` parsing so names like `E2P2final` do not
  collapse to `P2` and lose group assignments.
- Single-group projects have no `groups` metadata and keep the flat
  `<Excel Root>/<Condition>/...xlsx` layout.

Keep `_Worker` importable from `Tools.Plot_Generator.worker`. New worker helper
logic should go in the focused helper modules above and remain PySide6-free
unless it belongs in the QObject shell.

Use the root `AGENTS.md` platform/environment policy and the initial audits in
`docs/agent/agent-index.md`. Use their output to decide what to read next.

For Plot Generator worker or rendering changes, start with:

```console
python .agents/scripts/verify.py --scope plot-generator --tier focused
```

The driver selects `.venv1` or `.venv`, runs locally safe worker/rendering
checks, and leaves Plot Generator pytest-qt coverage to CI by default.

Future feature/fix plans:

- `docs/agent/exec-plans/future/plot-generator-multigroup-snr-overlays.md`
  covers first-class multi-group SNR overlays.

This tool will be used to generate publication quality figures within the FPVS Toolbox. Users should have the ability
to edit the plot title, x and y labels, and the scale of the x and y axes.

The plot generator should read the user-defined ROIs from the settings menu and generate plots for each ROI
individually. The user must choose an Excel file from which to pull data. This will typically be the same as the
output folder in the main app GUI where the Excel data is saved after processing .BDF files.

Publication figure exports should follow `docs/agent/quality/figure-generation.md`:
write matching 600 DPI PNG/PDF outputs and use `Main_App.exports.figure_style`
for Arial figure typography instead of GUI typography or local Matplotlib font
defaults.

Inside this folder, you'll find subfolders of varying names. The names of each of these folders represent the FPVS
conditions that were run. Within each subfolder, there will be Excel files named like "P3 Fruit vs Veg_Results".
You'll have one Excel file per participant per condition.

The app should read all of these Excel files for each condition and generate an average ROI plot for each condition
across all the participants, then plot that data. To further clarify, if you have 30 participants and 5 conditions,
You should generate one plot per condition per ROI. If the user defines 4 ROIs like "frontal, central, parietal,
occipital", then you have 4 ROIs * 5 conditions = 20 plots.
