The Plot_Generator directory contains the standalone PySide6 tool that builds SNR
or BCA line plots from Excel files created by the FPVS Toolbox. GUI adjustments
and minor bug fixes are allowed. Keep processing code modular and under 500 lines
per file. ROI definitions should be loaded from the existing settings using the
utilities in `Tools.Stats`. Plots should be averaged across participants within
each condition and saved to a user-selected output folder.

Current ownership map:

- `gui.py`: public `PlotGeneratorWindow` facade.
- `generation_workflow.py`: condition queueing, QThread worker launch/cancel,
  progress aggregation, and completion handling.
- `ui_sections.py`, `settings_dialog.py`, `gui_settings.py`,
  `selection_state.py`, `project_paths.py`, and `manifest_utils.py`: focused
  GUI, settings, selection, and project/manifest helpers.
- `worker.py`: `_Worker` QObject shell, signals, stop state, timing, run
  orchestration, finished payload emission, and compatibility re-exports for
  older imports.
- `worker_config.py`: `_Worker` constructor payload dataclass.
- `excel_inputs.py`: subject ID and frequency-column helpers.
- `data_collection.py`: Excel discovery/loading, FullSNR preference, FFT
  Amplitude SNR fallback, and source data collection.
- `aggregation.py`: selected ROI resolution, ROI averaging, group curves, and
  unknown-subject warnings.
- `scalp_rendering.py` and `scalp_utils.py`: scalp input selection and MNE
  topomap rendering.
- `rendering.py`: line and overlay plot rendering plus Matplotlib `Agg`
  configuration.
- `snr_utils.py`: shared SNR calculation helpers.

v2.1 project contract:

- `project.json` is canonical for group assignments. Prefer participant
  `group_id` and resolve labels/folder names through `project.groups`; legacy
  participant `group` values are compatibility input only.
- Multi-group Excel files live under
  `<Excel Root>/<Condition>/<Group>/<Participant>_<Condition>_Results.xlsx`.
  Discovery may recurse within a condition folder, but group membership should
  come from `project.json`, not from output folder names.
- Single-group projects have no `groups` metadata and keep the flat
  `<Excel Root>/<Condition>/...xlsx` layout.

Keep `_Worker` importable from `Tools.Plot_Generator.worker`. New worker helper
logic should go in the focused helper modules above and remain PySide6-free
unless it belongs in the QObject shell.

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
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\worker.py src\Tools\Plot_Generator\excel_inputs.py src\Tools\Plot_Generator\worker_config.py src\Tools\Plot_Generator\data_collection.py src\Tools\Plot_Generator\aggregation.py src\Tools\Plot_Generator\scalp_rendering.py src\Tools\Plot_Generator\rendering.py
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator -q
```

Future feature/fix plans:

- `docs/agent/exec-plans/future/plot-generator-multigroup-snr-overlays.md`
  covers first-class multi-group SNR overlays.
- `docs/agent/exec-plans/future/plot-generator-scalp-topography-fix.md`
  covers the scalp map/topography diagnosis and fix.

This tool will be used to generate publication quality figures within the FPVS Toolbox. Users should have the ability
to edit the plot title, x and y labels, and the scale of the x and y axes.

The plot generator should read the user-defined ROIs from the settings menu and generate plots for each ROI
individually. The user must choose an Excel file from which to pull data. This will typically be the same as the
output folder in the main app GUI where the Excel data is saved after processing .BDF files.

Inside this folder, you'll find subfolders of varying names. The names of each of these folders represent the FPVS
conditions that were run. Within each subfolder, there will be Excel files named like "P3 Fruit vs Veg_Results".
You'll have one Excel file per participant per condition.

The app should read all of these Excel files for each condition and generate an average ROI plot for each condition
across all the participants, then plot that data. To further clarify, if you have 30 participants and 5 conditions,
You should generate one plot per condition per ROI. If the user defines 4 ROIs like "frontal, central, parietal,
occipital", then you have 4 ROIs * 5 conditions = 20 plots.


