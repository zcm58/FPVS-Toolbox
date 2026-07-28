The Plot_Generator directory contains the embedded PySide6 tool that builds SNR
line plots from Excel files created by the FPVS Toolbox. The Main App GUI is its
only user-facing entry point. GUI adjustments
and minor bug fixes are allowed. Keep processing code modular and under 500 lines
per file. ROI definitions should be loaded from the existing settings using the
utilities in `Tools.Stats`. Plots should be averaged across participants within
each condition and saved to a user-selected output folder.

Current ownership map:

- `plot_generator.py`: Main App-imported embedded compatibility facade that
  preserves patchable worker/thread hooks; it is not a standalone entry point.
- `gui.py`: `PlotGeneratorWindow` page implementation.
- `generation_workflow.py`: condition queueing, QThread worker launch/cancel,
  progress aggregation, and completion handling.
- `ui_sections.py`, `settings_dialog.py`, `gui_settings.py`,
  `selection_state.py`, `project_paths.py`, and `manifest_utils.py`: focused
  GUI, settings, selection, and thin shared-project adapters.
- `worker.py`: `_Worker` QObject shell, signals, stop state, timing, run
  orchestration, finished payload emission, and compatibility re-exports for
  older imports.
- `worker_config.py`: `_Worker` constructor payload dataclass.
- `excel_inputs.py`: thin shared participant-identity adapter plus
  frequency-column helpers.
- `full_snr_reader.py`: direct `.xlsx` XML reader for the FullSNR fast path,
  including selected-frequency parsing, selected-ROI electrode
  filtering, and FullSNR load subtimings.
- `data_collection.py`: shared dataset-index consumption, FullSNR-only source
  data collection, and required-sheet failure handling.
- `aggregation.py`: selected ROI resolution, ROI averaging, group curves, and
  unknown-subject warnings.
- `spectral_qc.py`: post-processing, report-only electrode-level spectral
  artifact flagging and FullFFT evidence assembly for SNR plots.
- `spectral_qc_alerts.py`: plain-language GUI alert summaries for SNR spectral
  QC findings and whole-participant spectral exclusion candidates.
- `spectral_qc_report.py`: Quality Check workbook export for SNR plot spectral
  QC reports.
- `rendering.py`: line and overlay plot rendering plus Matplotlib `Agg`
  configuration.

v2.1 project contract:

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
- Multi-group plotting is a one-condition, group-overlay workflow. Hide the
  condition overlay checkbox in multi-group mode; the existing
  A/B colors, legend labels, and peak labels map to the first and second
  selected groups.
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

Use `.venv1` when it exists. On a development machine that only has `.venv`,
substitute `.venv` in the commands below.

Before broad manual inspection, run:

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use script output to decide what to read next.

For Plot Generator worker or rendering changes, start with:

```powershell
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

