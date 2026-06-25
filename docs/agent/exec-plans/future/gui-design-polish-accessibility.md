# GUI Design Polish and Accessibility

## Status

Future plan. Documentation/planning pass only.

This plan captures recommendations from the repo-local frontend design skills:

- `frontend-design`
- `web-design-guidelines`
- `emil-design-eng`

Those skills are advisory inputs only. All future implementation must follow
the FPVS Toolbox PySide6 rules in `AGENTS.md`, `docs/agent/design-docs/FRONTEND.md`,
and `docs/agent/architecture/gui.md`.

## Target

Primary shared GUI owners:

- `src/Main_App/gui/style_tokens.py`
- `src/Main_App/gui/theme.py`
- `src/Main_App/gui/typography.py`
- `src/Main_App/gui/components/`
- `src/Main_App/gui/widgets/`

Primary main-shell surfaces:

- `src/Main_App/gui/ui_main.py`
- `src/Main_App/gui/sidebar.py`
- `src/Main_App/gui/header_bar.py`
- `src/Main_App/gui/processing_inputs.py`
- `src/Main_App/gui/processing_workflows.py`
- `src/Main_App/gui/project_workflows.py`
- `src/Main_App/gui/settings_panel.py`

Primary embedded and tool surfaces:

- `src/Tools/Stats/ui/`
- `src/Tools/Plot_Generator/`
- `src/Tools/Ratio_Calculator/`
- `src/Tools/Publication_Maps/`
- `src/Tools/Publication_Report/`
- `src/Tools/Individual_Detectability/`
- `src/Tools/Average_Preprocessing/New_PySide6/`
- `src/Tools/LORETA_Visualizer/`

## Summary

FPVS Toolbox already has a strong PySide6 component base: shared style tokens,
typography roles, `SectionCard`, `ActionRow`, `StatusBanner`, path/action
helpers, keyboard-capable sidebar buttons, and workflow-specific controller
modules. The next GUI polish pass should not replace that architecture. It
should make the existing system feel more intentional, accessible, and easier
to operate in repeated research workflows.

The design direction is a restrained scientific desktop interface: dense,
scannable, and workflow-first, with one FPVS-specific visual signature rather
than decorative spectacle. The app should feel like EEG/FPVS analysis software,
not a generic blue-gray admin panel.

## Current Architecture Evidence

- `src/Main_App/gui/style_tokens.py` owns shared colors, spacing, sidebar
  dimensions, and main shell styles.
- `src/Main_App/gui/theme.py` applies the shared FPVS stylesheet to app and
  tool windows.
- `src/Main_App/gui/typography.py` owns global font family and role sizes.
- `src/Main_App/gui/components/` re-exports shared presentation contracts.
- `src/Main_App/gui/widgets/cards.py` owns `SectionCard` and `CardHeader`.
- `src/Main_App/gui/widgets/buttons.py` owns `make_action_button()` and
  `make_remove_button()`.
- `src/Main_App/gui/widgets/status.py` owns `StatusBanner`.
- `src/Main_App/gui/sidebar.py` implements custom sidebar buttons with
  `Qt.StrongFocus` and keyboard activation.
- `src/Main_App/gui/ui_main.py` builds the landing page, processing setup,
  processing activity page, progress table, and log panel.
- `docs/agent/design-docs/FRONTEND.md` explicitly says frontend-design advice
  must be translated into PySide6 contracts and must not override the repo's
  desktop-app constraints.

## Observed Opportunities

### Accessibility Metadata

No active GUI/tool code currently appears to use `setAccessibleName()` or
`setAccessibleDescription()`. Many controls already have stable object names,
tooltips, and shared factories, so accessibility metadata can be added in a
small number of shared places.

Candidate shared owners:

- `make_action_button()`
- `make_remove_button()`
- `PathPickerRow`
- `StatusBanner`
- `SidebarButton`
- reusable table/list setup helpers if introduced later

### Focus Visibility

The sidebar supports keyboard activation, but the shared styles should make
keyboard focus obvious. Button, tool button, tab, sidebar, list, and table
focus styling should be standardized through shared QSS tokens.

Known focus evidence:

- `SidebarButton` sets `Qt.StrongFocus` in `src/Main_App/gui/sidebar.py`.
- Shared QSS currently styles hover/pressed states for buttons and focus states
  for some inputs.
- `processing_files_table` is read-only and explicitly sets `Qt.NoFocus`.

### Inline Validation and Status

Many fixable input problems still surface as modal `QMessageBox` warnings or
critical dialogs. Modal dialogs should remain for destructive decisions,
blocking failures, and hard errors. Missing field, invalid input, and
recoverable workflow guidance should move toward inline `StatusBanner`
messages where the user can correct the problem in place.

Candidate surfaces:

- Main preprocessing input validation
- Plot Generator required-folder and axis-limit validation
- Stats missing-folder/ROI/settings validation
- Ratio Calculator required-field and output-folder validation
- Publication Maps/Report selection validation
- Individual Detectability required-field validation

### Interface Copy

Command labels and placeholder text are functional but uneven. Future cleanup
should use specific verbs and consistent vocabulary:

- Prefer `Choose Folder` over `Browse...`.
- Prefer `Open Output Folder` over `Open...`.
- Prefer `Generate Plot` or `Generate Scalp Maps` over generic `Generate`
  when context is not obvious.
- Prefer `Save Settings` over `OK`.
- Prefer `Reset Defaults` over `Reset to Default settings`.
- Use the Unicode ellipsis character only where the repo deliberately accepts
  non-ASCII in touched text; otherwise preserve ASCII and make copy clearer
  without broad typography churn.

Copy changes must preserve workflows, settings keys, object names used by
tests, and output formats.

### FPVS Visual Identity

The current palette is a competent blue/gray desktop palette. A future visual
polish pass should make one restrained FPVS-specific aesthetic move while
keeping the operational tool feel:

- Add a subtle signal or harmonic motif to the landing/header treatment.
- Consider token names and colors tied to FPVS concepts such as signal,
  harmonic, scalp-map, noise floor, success, warning, and rejected data.
- Avoid one-note palettes, heavy gradients, decorative blobs, or marketing-page
  composition.
- Keep cards as top-level subsection boundaries and preserve the flat embedded
  tool layout rule.

### Motion and Perceived Performance

Existing motion is mostly restrained:

- Main progress bars animate value changes at 200 ms.
- `BrainPulseWidget` uses a looping 2600 ms decorative animation.
- Busy spinners are used during long work.

Future changes should keep repeated workflow actions snappy and avoid animation
for high-frequency keyboard-triggered actions. Decorative looping animation
should have a reduced-motion path, either via an app setting or OS-aware guard
if a safe PySide6 implementation is available.

### Dense Data Surfaces

Tables and lists are central to the app. The design pass should improve
inspection without adding visual noise:

- Use tabular numeric alignment where possible.
- Preserve row density and scan speed.
- Add accessible summaries for read-only status tables that intentionally do
  not take focus.
- Keep keyboard navigation for tables/lists that users inspect or edit.
- Avoid hiding important status only in tooltips.

## Goals

- Improve accessibility metadata and keyboard focus visibility across shared
  GUI primitives.
- Standardize command labels, validation text, and status copy around user
  actions.
- Move recoverable validation from modal interruption to inline banners where
  appropriate.
- Introduce a restrained FPVS-specific visual identity through shared tokens
  and one signature motif.
- Add or document reduced-motion behavior for decorative/looping animations.
- Preserve all processing behavior, project I/O, file formats, defaults,
  settings keys, object names, worker boundaries, and output paths.
- Keep implementation centralized in shared component/style contracts before
  touching local surfaces.

## Non-Goals

- Do not convert FPVS Toolbox to a web, React, Tailwind, or browser UI.
- Do not add Tkinter, CustomTkinter, PyQt, or web frontend dependencies.
- Do not redesign scientific workflows, preprocessing order, statistical
  methods, file formats, or project-root behavior.
- Do not add nested card layouts or marketing-style hero pages.
- Do not make broad copy changes that alter task meaning, persistence keys, or
  test-pinned labels without scoped review.
- Do not run offscreen Qt workflows locally.
- Do not restore removed Source Localization/eLORETA runtime surfaces.

## Open Questions Before Activation

1. Should the first implementation pass prioritize accessibility/focus polish,
   copy cleanup, or FPVS visual identity?
2. Should accessible names be derived automatically from button text/tooltips
   in shared factories, or set explicitly at each call site for maximum
   specificity?
3. Which modal validation cases should stay modal because they protect against
   destructive or expensive operations?
4. Should reduced motion be controlled by a user setting, OS setting, or both?
5. How bold should the FPVS visual signature be: landing/header only, sidebar
   selection motif, or subtle section-divider motif across the app?
6. Should button label changes be allowed to update existing GUI smoke tests,
   or should copy cleanup be limited to unpinned labels first?

## Suggested Slices

### Slice 1: Shared Accessibility Metadata

1. Add optional `accessible_name` and `accessible_description` parameters to
   shared button/path/status factories where useful.
2. Set default accessible names from visible text for text buttons.
3. Set explicit accessible names for icon-only or symbol-only controls such as
   remove, clear log, open folder, copy path, refresh, and swap.
4. Add focused component smoke coverage for accessible names/descriptions.
5. Verify no workflow behavior, signal wiring, object names, or visual layout
   changes.

### Slice 2: Shared Focus Styling

1. Add shared QSS tokens for visible focus on:
   - `QPushButton`
   - `QToolButton`
   - `QTabBar::tab`
   - `#SidebarButton`
   - editable/list/table controls where appropriate
2. Preserve existing hover, pressed, disabled, selected, and processing-locked
   states.
3. Confirm focus styles are visible against both light content surfaces and the
   dark sidebar.
4. Add or update focused smoke tests that inspect dynamic properties and style
   contract hooks.
5. Document visible/manual smoke steps for keyboard traversal.

### Slice 3: Inline Recoverable Validation

1. Inventory modal validation calls with:

   ```powershell
   rg -n "QMessageBox\.(warning|critical|information)|show_error\(|show_warning\(|show_info\(" src/Main_App src/Tools -g "*.py"
   ```

2. Classify each message as:
   - `recoverable-inline`
   - `destructive-confirmation`
   - `hard-failure-modal`
   - `completion-summary`
3. Migrate only `recoverable-inline` cases to local `StatusBanner` or shared
   message helpers.
4. Keep destructive confirmations and hard failures modal.
5. Add focused tests around enabled state, message text, and no-dialog paths
   where existing tests can cover them without offscreen GUI execution.

### Slice 4: Copy and Vocabulary Cleanup

1. Build a copy inventory for common verbs and ambiguous labels:

   ```powershell
   rg -n "\"OK\"|\"Browse\.\.\.\"|\"Open\.\.\.\"|\"Generate\"|\"Reset to Default settings\"|\"Error\"" src/Main_App src/Tools -g "*.py"
   ```

2. Propose a vocabulary table before implementation:
   - choose/open/save/export/generate/run/cancel/copy/reset
   - folder/file/project/workbook/scalp map/report/log
3. Update one surface at a time, preserving object names and signal wiring.
4. Keep labels that are part of tests or user docs stable unless tests/docs are
   updated in the same slice.
5. Prefer plain, specific action labels over clever or promotional copy.

### Slice 5: FPVS Visual Identity Tokens

1. Draft a compact token map in `style_tokens.py`:
   - primary signal color
   - harmonic/accent color
   - scalp-map/visualization accent
   - quiet page/surface neutrals
   - warning/error/success states
2. Apply the token pass through `theme.py` and `style_tokens.py`, not per-surface
   QSS.
3. Add one restrained FPVS-specific motif to the landing or header area:
   - harmonic tickline
   - subtle waveform divider
   - scalp-map contour accent
4. Keep the main app first screen usable and project-focused.
5. Verify contrast manually and with focused style-token review.

### Slice 6: Motion and Reduced-Motion Controls

1. Inventory active GUI animations:

   ```powershell
   rg -n "QPropertyAnimation|BusySpinner|BrainPulseWidget|setDuration\(" src/Main_App src/Tools -g "*.py"
   ```

2. Keep progress value smoothing for long-running operations unless it causes
   perceived lag.
3. Add reduced-motion handling for decorative looping animation first.
4. Avoid animation on keyboard-triggered high-frequency actions.
5. Document visible/manual smoke steps because offscreen Qt workflows must not
   be run locally.

### Slice 7: Dense Data Surface Polish

1. Inventory `QTableWidget`, `QListWidget`, and read-only result/status
   surfaces.
2. Add accessible summaries or adjacent status labels where a read-only table
   intentionally has `Qt.NoFocus`.
3. Preserve table density, sort order, and selection behavior.
4. Use tabular-number presentation where available and practical.
5. Avoid turning dense research workflows into decorative card-heavy layouts.

## Verification Plan

Run focused non-GUI checks first. Use the repo-local virtual environment if
available in the active checkout; if `.venv1` is absent, use the available repo
venv and report that substitution.

Recommended commands after implementation slices:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\theme.py src\Main_App\gui\style_tokens.py src\Main_App\gui\typography.py
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check gui
.\.venv1\Scripts\python.exe -m pytest tests\gui\test_ui_components_smoke.py -q
```

For touched tool surfaces, add the nearest focused non-GUI checks from
`docs/agent/quality/test-selection.md`.

Do not run pytest-qt/offscreen GUI workflows locally. Provide a visible/manual
smoke path instead, such as:

1. Launch the app normally in a visible Windows session.
2. Create or open a project.
3. Use keyboard traversal through landing actions, sidebar, preprocessing
   inputs, settings, Stats, Plot Generator, Ratio Calculator, and any touched
   surface.
4. Confirm focus rings are visible, command labels are clear, inline validation
   appears next to the relevant controls, and long-running work remains
   non-blocking.
5. Confirm reduced-motion behavior if the slice touches decorative animation.

## Documentation Plan

Update docs only when implementation changes structure, ownership, shared
component contracts, or user-visible workflows:

- `docs/agent/architecture/gui.md` for shared component/style ownership changes.
- `docs/agent/design-docs/FRONTEND.md` if frontend-skill translation rules
  change.
- The nearest scoped `AGENTS.md` for tool-specific GUI ownership changes.
- User docs only if labels, workflows, validation behavior, or visual outputs
  change in a way users need to understand.

For a pure style-token or copy pass that does not alter workflow semantics,
state why no architecture/user docs were needed in the handoff.

## Reporting Requirements

Future agents using this plan must report:

- Which slice was activated.
- Exact GUI surfaces and shared components touched.
- Which frontend-design recommendations were translated and which were
  deliberately ignored as web-only.
- Accessibility metadata and focus behavior added.
- Modal validation cases migrated or intentionally preserved.
- Copy labels changed and any test/docs updates required by those labels.
- Motion/reduced-motion behavior verified.
- Verification commands run and results.
- Visible/manual smoke path for GUI behavior not executed locally.
