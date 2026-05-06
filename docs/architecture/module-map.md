# Module Map

Use this as a quick orientation map before opening files. Run the relevant audit script first when the task matches a skill; use this file to choose the next narrow file or doc to open.

Common first commands:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Main App

- `src/Main_App/PySide6_App/GUI/main_window.py`: main PySide6 shell/coordinator. It has been appropriately downsized; do not target it for further refactor unless the user explicitly scopes that work.
- `src/Main_App/PySide6_App/GUI/event_map.py`: event-map row construction, binding, Enter-key handling, and entry adapters used by `MainWindow` wrappers.
- `src/Main_App/PySide6_App/GUI/`: menus, header/sidebar assembly, settings panel, style tokens, and shell-specific widgets. Active imports should prefer `Main_App.gui`.
- `src/Main_App/gui/`: canonical import surface for main-window, settings-panel, menu, sidebar, icon, style-token, theme, widget, operation-guard, and update-manager GUI modules. `widgets/` owns reusable PySide6 presentation primitives, `theme.py` owns the shared FPVS palette/stylesheet helpers, `op_guard.py` owns the non-blocking GUI operation guard, `project_workflows.py` owns project open/create/load/save GUI orchestration, `processing_inputs.py` owns processing input validation, file/mode UI state, and parameter assembly, `processing_workflows.py` owns processing run start/stop/queue/finalization GUI orchestration, `post_export_workflows.py` owns GUI-side post-processing worker launch/error routing and export completion handling, `tool_workflows.py` owns settings/update/tool/help/about action orchestration, and `shell_status.py` owns launch reveal, status bar, busy indicator, GUI log routing, and processing-start notices; `main_window.py` is appropriately downsized and should not be targeted for further refactor unless the user explicitly scopes that work.
- `src/Main_App/PySide6_App/widgets/`: temporary compatibility wrappers for `Main_App.gui.widgets`.
- `src/Main_App/PySide6_App/Backend/`: active preprocessing implementation and remaining processing-controller implementation. `processing.py`, project model, project manager, preprocessing settings, and metadata modules are temporary compatibility wrappers for canonical Main App packages; `loader.py` is only a compatibility wrapper for the shared BDF loader.
- `src/Main_App/exports/`: canonical export adapter import surface. `post_export_adapter.py` bridges process/worker payloads into shared post-processing exports.
- `src/Main_App/PySide6_App/adapters/`: temporary compatibility wrappers for adapter imports during package retirement.
- `src/Main_App/PySide6_App/workers/`: Qt worker and multiprocessing bridge implementations. Active imports should prefer `Main_App.workers`.
- `src/Main_App/PySide6_App/utils/`: compatibility helpers. Theme helpers are now owned by `Main_App.gui.theme`, the GUI operation guard is owned by `Main_App.gui.op_guard`, and bundled-resource path helpers are owned by `Main_App.Shared.paths`; active preprocessing audit imports should prefer `Main_App.diagnostics`.
- `src/Main_App/Shared/paths.py`: resource path helper for source and frozen bundles.
- `src/Main_App/PySide6_App/diagnostics/`: existing event-time lock implementation. Active imports should prefer `Main_App.diagnostics`.
- `src/Main_App/Performance/`: process-runner and multiprocessing support; imports shared FFT crop helpers.
- `src/Main_App/processing/`: canonical import surface for active EEG preprocessing and processing entry-point ownership. `processing.py` owns the stable no-op `process_data` coordinator, while preprocessing still delegates to the existing PySide6 backend implementation during the package-layout migration.
- `src/Main_App/io/`: canonical import surface for active BDF loading. It delegates to the existing shared loader implementation during the package-layout migration.
- `src/Main_App/projects/`: canonical owner for project model, project manager workflows, project metadata scanning, projects-root helpers, and preprocessing settings normalization.
- `src/Main_App/workers/`: canonical import surface for Qt workers, process runner, and multiprocessing environment helpers. It delegates to existing PySide6 worker and Performance implementations during the package-layout migration.
- `src/Main_App/diagnostics/`: canonical import surface for runtime toolbox diagnostics such as preprocessing audit summaries and event-time lock reports. It observes/reports app state and must not own repo-evaluation checks.
- `src/Main_App/Shared/`: shared current-app settings, user-message helpers, BDF loader, processing mixin, FFT crop helpers, and post-processing export behavior.
- `src/Main_App/Legacy_App/`: retired historical package. Do not recreate it.

Current `Legacy_App` runtime couplings:

- No active runtime imports should point at `Main_App.Legacy_App`; no tracked files should remain under `src/Main_App/Legacy_App/`.

- `src/Main_App/PySide6_App/Backend/loader.py`: thin wrapper for `Main_App.Shared.load_utils`; current runtime imports should use `Main_App.io.load_utils`.

## Tools

- `src/Tools/Stats/`: active statistics UI, pipeline, analysis engines, reporting, I/O, CLI, and shared helpers grouped by function. Removed `Tools.Stats.PySide6` and `Tools.Stats.Legacy` import paths are not supported.
- `src/Tools/Plot_Generator/`: SNR/FFT plot generation.
- `src/Tools/Ratio_Calculator/`: ratio computation, export, and plotting.
- `src/Tools/Individual_Detectability/`: individual-level detectability workflow.
- `src/Tools/Average_Preprocessing/New_PySide6/`: active PySide6 average-preprocessing UI.
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_core.py`: UI-agnostic average-preprocessing behavior used by the PySide6 tool.
- `src/Tools/Image_Resizer/`: image resizing utility.
- `scripts/agent_audit.py` and `.agents/skills/*/scripts/`: repo-evaluation and agent harness checks, not runtime toolbox diagnostics.
- `scripts/manual_diagnostics/`: developer-run project/data investigation utilities, not runtime toolbox APIs.

## Dead Or Quarantined

- Source Localization/eLORETA: removed from active runtime; `src/Tools/SourceLocalization/**` must remain empty of source files unless restoration is explicitly scoped.
- `src/quarantine/**`: ignored quarantine tree retained outside active runtime.
