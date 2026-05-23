# Plot Generator Scalp Topography Fix

## Status

Future plan. Not active implementation work.

## Target

- `src/Tools/Plot_Generator/scalp_utils.py`
- `src/Tools/Plot_Generator/scalp_rendering.py`
- `src/Tools/Plot_Generator/data_collection.py`
- `src/Tools/Plot_Generator/rendering.py`
- `src/Tools/Plot_Generator/gui.py`
- `src/Tools/Plot_Generator/ui_sections.py`
- `src/Tools/Plot_Generator/plot_settings.py`
- `tests/plot_generator/test_plot_generator_scalp_utils.py`
- Plot Generator rendering/export tests under `tests/plot_generator/`

## Current State

Scalp maps are optional Plot Generator outputs:

- `data_collection.py` reads `BCA (uV)` and `Z Score` sheets when scalp maps
  are enabled.
- `scalp_utils.py` summarizes each subject by summing BCA values at oddball
  frequencies whose Z score passes `ODDBALL_THRESHOLD`, then aligns averaged
  values to MNE's BioSemi64 montage.
- `scalp_rendering.py` renders topomaps with MNE and has compatibility
  fallbacks for `cnorm`, `vlim`, and `vmin`/`vmax`.
- `rendering.py` lays out line plots with optional scalp maps and saves PNG/SVG.
- GUI settings persist scalp inclusion, color bounds, and title templates.

The exact scalp map/topography defect is not pinned in a failing test yet. The
first implementation slice must reproduce the issue from a real or synthetic
minimal workbook before changing behavior.

## Goal

Make scalp map and topography output reliable, diagnosable, and testable while
preserving existing plot generation behavior for line plots.

The completed fix should answer:

- which electrodes are included;
- which oddball frequencies contribute;
- how BCA and Z Score sheets are combined;
- how missing or unmapped electrodes are reported;
- how MNE topomap parameters are chosen across supported MNE versions;
- whether PNG and SVG exports render the scalp maps correctly.

## Non-Goals

- Do not change the core SNR line plot behavior.
- Do not change BCA/Z scalp math until the defect is reproduced and the desired
  topography behavior is specified.
- Do not add silent fallback behavior that hides missing sheets, missing
  electrodes, bad montage names, or MNE rendering failures.
- Do not restore Source Localization/eLORETA or add bundled MRI template data.
- Do not run offscreen Qt workflows locally.

## Open Questions Before Activation

1. What is the observed defect: wrong electrode positions, blank topomap,
   flipped/topographically implausible values, missing colorbar, bad scale,
   export-only issue, or runtime exception?
2. Are input Excel electrode labels always BioSemi64 names, or do real projects
   use aliases that need explicit normalization?
3. Should scalp maps show whole-head topography for the selected ROI's source
   data, or mask/zero electrodes outside the selected ROI?
4. Should values be summed across significant oddball harmonics per electrode,
   averaged across participants, or normalized before group averaging?
5. Should scalp maps support group overlays, condition comparison, or only the
   current condition/ROI plot shape?

## Suggested Slices

1. Reproduce and document the defect:
   - Capture the smallest workbook or synthetic fixture that demonstrates the
     scalp/topography issue.
   - Add a failing non-GUI test around `scalp_utils.py`,
     `scalp_rendering.py`, or generated-image inspection where possible.
   - If the issue is visual only, save a small manual verification artifact
     outside source control and document the visible smoke path.

2. Pin scalp input semantics:
   - Add tests for electrode label normalization, duplicate electrode handling,
     missing BCA/Z sheets, missing frequency columns, Z threshold behavior, and
     oddball-vs-base harmonic exclusion.
   - Decide and test whether non-ROI electrodes are retained, masked, or zeroed.

3. Harden topomap rendering:
   - Isolate MNE topomap option selection so version compatibility is tested
     without repeating broad `try/except TypeError` chains.
   - Surface MNE rendering failures in the worker log and finished payload.
   - Preserve Matplotlib `Agg` rendering for worker output.

4. Verify image/export behavior:
   - Add focused tests that generated PNG/SVG files contain non-empty rendered
     content when scalp maps are enabled.
   - Keep existing line-plot dimensions, labels, oddball markers, and output
     filenames stable unless the defect requires a scoped adjustment.

5. GUI and settings cleanup:
   - Update validation only if the scalp workflow needs additional required
     inputs.
   - Preserve existing settings keys for include-scalp, bounds, and title
     templates unless migration is explicitly required.

6. Documentation and handoff:
   - Update `src/Tools/Plot_Generator/AGENTS.md` if ownership or verification
     commands change.
   - Update user-facing SNR Plot Generator docs if the scalp-map workflow,
     input requirements, or interpretation changes.

## Verification Plan

Use focused non-GUI checks first:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\scalp_utils.py src\Tools\Plot_Generator\scalp_rendering.py src\Tools\Plot_Generator\data_collection.py src\Tools\Plot_Generator\rendering.py
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_scalp_utils.py -q
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_export_svg_smoke.py tests\plot_generator\test_plot_generator_generation_outcome.py -q
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
```

For visual topography behavior, prefer deterministic image/file checks where
possible. If visual confirmation is still required, use a visible/manual smoke
path and do not set `QT_QPA_PLATFORM=offscreen`.

## Reporting Requirements

Future agents using this plan must report:

- Exact reproduced defect and input workbook/fixture shape.
- Electrode label and montage assumptions.
- Oddball frequency, BCA, and Z threshold behavior verified.
- Whether non-ROI electrodes are shown, masked, or zeroed.
- MNE compatibility behavior verified.
- PNG/SVG output checks run.
- Any skipped visual/manual smoke and residual risk.
