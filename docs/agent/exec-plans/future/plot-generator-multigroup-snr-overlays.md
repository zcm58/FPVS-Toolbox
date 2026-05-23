# Plot Generator Multi-Group SNR Overlays

## Status

Future plan. Not active implementation work.

## Target

- `src/Tools/Plot_Generator/gui.py`
- `src/Tools/Plot_Generator/selection_state.py`
- `src/Tools/Plot_Generator/generation_workflow.py`
- `src/Tools/Plot_Generator/worker_config.py`
- `src/Tools/Plot_Generator/aggregation.py`
- `src/Tools/Plot_Generator/rendering.py`
- `tests/plot_generator/test_plot_generator_multigroup_smoke.py`

## Current State

Plot Generator already has partial multi-group support:

- `selection_state.py` reads project manifest groups, shows the group overlay
  controls, builds `subject_groups`, `selected_groups`,
  `enable_group_overlay`, and `multi_group_mode` worker kwargs.
- `worker_config.py` carries group-overlay settings.
- `aggregation.py` builds per-group ROI curves from the collected subject data
  and warns about selected files without group assignments.
- `rendering.py` accepts `group_curves` for single-condition SNR plots.
- `tests/plot_generator/test_plot_generator_multigroup_smoke.py` pins the
  current group-control and group-curve smoke behavior.

Current limitation to verify before activation: comparison mode disables group
overlay controls, so "multiple groups on one SNR plot" currently appears to be
single-condition group overlay only, not condition-A-vs-condition-B grouped
comparison.

## Goal

Make multi-group SNR overlays a first-class, tested Plot Generator workflow.
Users should be able to generate a single SNR plot per condition/ROI with one
average curve per selected group, using project manifest group assignments.

If condition comparison plus group overlays is desired, implement it only after
the single-condition grouped plot behavior is pinned and the visual design is
explicitly chosen.

## Non-Goals

- Do not change SNR, FullSNR, FFT Amplitude fallback, ROI averaging, BCA, or
  scalp-map math unless a test proves the existing behavior is wrong.
- Do not change generated filenames or output formats except to add explicitly
  scoped group-overlay suffixes if required.
- Do not add silent fallback behavior for missing groups, unknown subjects, or
  malformed project manifests. Surface warnings in the log and finished payload
  where appropriate.
- Do not run offscreen Qt workflows locally.

## Open Decisions Before Activation

1. Should the feature remain single-condition only, or should it support
   condition comparison with separate curves per group and condition?
2. Should output filenames include selected group names, a generic
   `group_overlay` suffix, or keep the current filename shape?
3. Should all groups be checked by default, or should the user explicitly choose
   groups before enabling the overlay?
4. How should a subject without a group assignment affect the final status:
   warning only, partial failure count, or both?

## Suggested Slices

1. Baseline and decision capture:
   - Confirm the current manifest shape for groups and participants.
   - Re-run the existing multigroup smoke tests.
   - Record whether this plan is single-condition only or includes comparison
     mode.

2. Test fixtures and contracts:
   - Add or improve `tests/plot_generator/conftest.py` helpers for project
     manifests, grouped participants, ROI data, and fake worker plot capture.
   - Keep tests readable so future agents do not rebuild fixtures repeatedly.

3. Single-condition group overlay hardening:
   - Pin selected-group ordering, unchecked group exclusion, all-groups default,
     unknown-subject warnings, and finished payload failure/warning behavior.
   - Ensure group overlays work for one ROI and `ALL_ROIS_OPTION`.

4. Rendering and legend contract:
   - Pin legend labels, color assignment, baseline line, oddball markers,
     y-axis scaling, and generated PNG/SVG output when group curves are present.
   - Keep existing non-group plots byte-shape and labels stable where practical.

5. Optional comparison-mode expansion:
   - Only activate this slice if the decision is to support group overlays while
     comparing two conditions.
   - Define the curve naming and legend shape before implementation.
   - Preserve current comparison behavior when group overlay is off.

6. Documentation and manual smoke:
   - Update `src/Tools/Plot_Generator/AGENTS.md` if ownership or verification
     commands change.
   - Update user-facing SNR Plot Generator docs only if the visible workflow
     changes.
   - Document a visible/manual smoke path for the group overlay workflow.

## Verification Plan

Use focused checks first:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\selection_state.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\worker_config.py src\Tools\Plot_Generator\aggregation.py src\Tools\Plot_Generator\rendering.py
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_multigroup_smoke.py -q
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_generation_outcome.py tests\plot_generator\test_plot_generator_legend_labels.py tests\plot_generator\test_plot_generator_export_svg_smoke.py -q
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
```

For GUI behavior, do not run offscreen Qt locally. Use non-GUI checks plus a
documented visible/manual smoke path unless the user explicitly approves a safe
visible GUI test environment.

## Reporting Requirements

Future agents using this plan must report:

- Whether grouped plots are single-condition only or include comparison mode.
- Manifest group shape tested.
- Selected group ordering and unknown-subject behavior.
- Generated filenames and formats verified.
- Legend/color behavior verified.
- Commands run and results.
- Any skipped visible GUI smoke and residual risk.
