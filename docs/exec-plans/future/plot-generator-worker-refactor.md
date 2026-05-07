# Plot Generator Worker Refactor

## Status

Future plan. This work has not started.

## Target

`src/Tools/Plot_Generator/worker.py`

## Summary

`worker.py` currently combines the QObject worker shell, worker configuration,
Excel file scanning and reading, SNR fallback calculation, subject ID inference,
ROI aggregation, group overlays, scalp input preparation, topomap rendering,
line/overlay plotting, output recording, failure tracking, and timing
diagnostics. This slows future plot-generation work because data preparation and
rendering are tightly coupled to Qt signal plumbing.

Do not change generated plot content, filenames, image formats, or Excel-reading
rules in this plan. The goal is a behavior-preserving worker split.

## Behavior To Preserve

- `_Worker` remains importable from `Tools.Plot_Generator.worker` for the GUI.
- The worker keeps the same `progress` and `finished` signals.
- Finished payloads keep `condition`, `overlay`, `generated_paths`, and
  `failed_items`.
- PNG and SVG outputs remain generated with current filenames and save settings.
- FullSNR sheets remain preferred; FFT Amplitude sheets continue to use the
  current SNR fallback calculation.
- Frequency range selection, oddball marker selection, ROI averaging,
  group-overlay filtering, unknown-subject warnings, scalp map generation, and
  timing summary messages remain stable.
- Matplotlib remains configured for noninteractive `Agg` rendering.
- Worker code must not read or mutate GUI widgets directly.

## Suggested Seams

Prefer one seam per PR. Keep `worker.py` as a compatibility facade until GUI
imports are deliberately migrated.

1. Small pure helpers:
   - Move `_infer_subject_id_from_path`, `_frequency_pairs_from_columns`, and
     `_select_frequency_pairs` to `src/Tools/Plot_Generator/excel_inputs.py`.
   - This is the lowest-risk slice; add/confirm unit tests for filename parsing
     and frequency column filtering.

2. Worker configuration:
   - Introduce `src/Tools/Plot_Generator/worker_config.py` with a dataclass that
     mirrors the current `_Worker.__init__` parameters.
   - Only do this after tests pin default oddball, group-overlay, scalp, legend,
     and project-root behavior. Keep `_Worker.__init__` compatible with current
     callers while delegating to the dataclass internally.

3. Excel collection and SNR fallback:
   - Move `_count_excel_files`, `_list_excel_files`, and `_collect_data` to
     `src/Tools/Plot_Generator/data_collection.py`.
   - Preserve recursive `.xlsx` discovery under a condition folder, FullSNR
     preference, FFT Amplitude fallback via `calc_snr_matlab`, BCA/Z scalp sheet
     reading, ROI electrode matching, failure messages, and progress offsets for
     overlay mode.

4. ROI/group aggregation:
   - Move `_selected_roi_names`, `_aggregate_roi_data`,
     `_build_group_curves`, and `_warn_unknown_subjects` to
     `src/Tools/Plot_Generator/aggregation.py`.
   - Preserve all-subject averaging, selected-group ordering, unknown-subject
     exclusion warnings, and `ALL_ROIS_OPTION` handling.

5. Scalp rendering helpers:
   - Keep data preparation in existing `scalp_utils.py`.
   - Move `_prepare_scalp_inputs`, `_scalp_oddball_frequencies`,
     `_format_scalp_title`, and `_plot_scalp_map` to
     `src/Tools/Plot_Generator/scalp_rendering.py`.
   - Preserve MNE version compatibility fallbacks for `cnorm`, `vlim`, and
     `vmin`/`vmax`, colorbar placement, title fallback behavior, and units.

6. Plot rendering:
   - Move `_plot` and `_plot_overlay` to
     `src/Tools/Plot_Generator/rendering.py`.
   - Preserve figure sizes, gridlines, oddball markers, legends, y=1 SNR line,
     title formatting, scalp layout, save DPI, SVG export, and generated-path
     recording.

7. Worker shell:
   - After the pure pieces are extracted, keep `_Worker` in `worker.py` as the
     thin QObject shell owning signals, stop state, timing, `_run`, and finished
     payload emission.
   - Avoid making helper modules depend on PySide6.

## Suggested Final Shape

- `src/Tools/Plot_Generator/worker.py` with `_Worker` as a thin Qt shell.
- `src/Tools/Plot_Generator/worker_config.py`
- `src/Tools/Plot_Generator/excel_inputs.py`
- `src/Tools/Plot_Generator/data_collection.py`
- `src/Tools/Plot_Generator/aggregation.py`
- `src/Tools/Plot_Generator/scalp_rendering.py`
- `src/Tools/Plot_Generator/rendering.py`

## What Future Agents Should Inspect First

1. `src/Tools/Plot_Generator/AGENTS.md`
2. `src/Tools/Plot_Generator/worker.py`
3. `src/Tools/Plot_Generator/gui.py` for worker construction and payload use
4. `src/Tools/Plot_Generator/scalp_utils.py`
5. `src/Tools/Plot_Generator/snr_utils.py`
6. Plot Generator tests under `tests/test_plot_generator_*`

Before editing, run:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Verification Plan

Run focused worker/plot tests first:

```powershell
python -m py_compile src\Tools\Plot_Generator\worker.py
python -m pytest tests\test_plot_generator_fft_snr.py tests\test_plot_generator_full_snr_roi.py tests\test_plot_generator_baseline.py -q
python -m pytest tests\test_plot_generator_export_svg_smoke.py tests\test_plot_generator_gridlines.py tests\test_plot_generator_oddballs_from_xmax.py -q
python -m pytest tests\test_plot_generator_generation_outcome.py tests\test_plot_generator_multigroup_smoke.py tests\test_plot_generator_scalp_utils.py -q
python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_refactor_smoke.py -q
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
```

Add pure unit tests for extracted helpers when practical before moving larger
rendering methods.

## Reporting Requirements

Future agents using this plan must report:

- Which seam was activated and why.
- Exact helpers/methods moved and their old/new module paths.
- Whether `_Worker` remains the GUI-facing import.
- Generated output formats and filenames verified.
- Excel sheet/fallback behavior verified.
- Commands run and results.
- Any skipped image/GUI smoke tests and residual risk.

## Manual Verification Before Activation

This plan was created from read-only inspection of the current worker: it
contains top-level subject/frequency helpers, `_Worker` with Qt signals, timing
and failure helpers, oddball/ROI/group helpers, scalp input/render helpers,
Excel collection, `_run`, `_plot`, and `_plot_overlay`. Recheck those symbols
before activation because Plot Generator worker behavior is output-sensitive.
