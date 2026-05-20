# Module Map

Use this as a quick orientation map before opening files. Run the relevant audit script first when the task matches a skill; use this file to choose the next narrow file or doc to open.

Common first commands:

```powershell
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Main App

- `src/Main_App/gui/`: canonical GUI package for the main-window shell, settings panel, event map, menu/sidebar/header/icon helpers, style tokens, theme, reusable widgets, operation guard, and update manager. `ui_main.py` owns landing/main page assembly; `event_map.py` owns event-map row construction, binding, Enter-key handling, and entry adapters; `icons.py`, `header_bar.py`, `file_menu.py`, and `menu_bar.py` own shell/menu presentation helpers; `sidebar.py` owns sidebar construction and sidebar button presentation; `widgets/` owns reusable PySide6 presentation primitives, `theme.py` owns the shared FPVS palette/stylesheet helpers, `op_guard.py` owns the non-blocking GUI operation guard, `project_workflows.py` owns project open/create/load/save GUI orchestration, `processing_inputs.py` owns processing input validation, file/mode UI state, and parameter assembly, `processing_workflows.py` owns processing run start/stop/queue/finalization GUI orchestration, `post_export_workflows.py` owns GUI-side post-processing worker launch/error routing and export completion handling, `tool_workflows.py` owns settings/update/tool/help/about action orchestration, and `shell_status.py` owns launch reveal, status bar, busy indicator, GUI log routing, and processing-start notices; `main_window.py` is appropriately downsized and should not be targeted for further refactor unless the user explicitly scopes that work.
- `src/Main_App/exports/`: canonical export adapter import surface. `post_export_adapter.py` bridges process/worker payloads into shared post-processing exports.
- `src/Main_App/Shared/paths.py`: resource path helper for source and frozen bundles.
- `src/Main_App/Performance/`: process-runner and multiprocessing support; imports shared FFT crop helpers.
- `src/Main_App/processing/`: canonical package for active EEG preprocessing and processing entry-point ownership. `preprocess.py` owns the active preprocessing implementation, `processing.py` owns the stable no-op `process_data` coordinator, and `processing_controller.py` owns raw-file discovery, batch-file preparation, and the compatibility processing route.
- `src/Main_App/io/`: canonical import surface for active BDF loading. It delegates to the existing shared loader implementation during the package-layout migration.
- `src/Main_App/projects/`: canonical owner for project model, project manager workflows, project metadata scanning, projects-root helpers, and preprocessing settings normalization.
- `src/Main_App/updates/`: canonical non-GUI updater backend for typed release
  contracts, GitHub Releases selection, installer downloads, and installer
  launch. GUI scheduling and presentation remain in `src/Main_App/gui/update_manager.py`
  and `src/Main_App/gui/update_dialog.py`.
- `src/Main_App/workers/`: canonical package for Qt workers, process runner wrappers, and multiprocessing environment helpers.
- `src/Main_App/diagnostics/`: canonical owner for runtime toolbox diagnostics such as preprocessing audit summaries and event-time lock reports. It observes/reports app state and must not own repo-evaluation checks.
- `src/Main_App/Shared/`: shared current-app settings, user-message helpers, BDF loader, processing mixin, FFT crop helpers, and post-processing export behavior.
- `src/Main_App/Legacy_App/`: retired historical package. Do not recreate it.
- `src/Main_App/PySide6_App/`: retired historical package designation. Do not recreate it.

Current `Legacy_App` runtime couplings:

- No active runtime imports should point at `Main_App.Legacy_App`; no tracked files should remain under `src/Main_App/Legacy_App/`.

## Tools

- `src/Tools/Stats/`: active statistics UI, pipeline, analysis engines, reporting, I/O, CLI, and shared helpers grouped by function. Removed `Tools.Stats.PySide6` and `Tools.Stats.Legacy` import paths are not supported.
- `src/Tools/Plot_Generator/`: SNR/FFT plot generation.
- `src/Tools/Ratio_Calculator/`: ratio computation, export, and plotting.
- `src/Tools/Individual_Detectability/`: individual-level detectability workflow.
- `src/Tools/Average_Preprocessing/New_PySide6/`: active PySide6 average-preprocessing UI.
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_core.py`: UI-agnostic average-preprocessing behavior used by the PySide6 tool.
- `src/Tools/Image_Resizer/`: image resizing utility.
- `.agents/scripts/audit/agent_audit.py` and `.agents/skills/*/scripts/`: repo-evaluation and agent harness checks, not runtime toolbox diagnostics.
- `scripts/manual_diagnostics/`: developer-run project/data investigation utilities, not runtime toolbox APIs.

## Dead Or Quarantined

- Source Localization/eLORETA: removed from active runtime; `src/Tools/SourceLocalization/**` must remain empty of source files unless restoration is explicitly scoped.
- `src/quarantine/**`: ignored quarantine tree retained outside active runtime.
