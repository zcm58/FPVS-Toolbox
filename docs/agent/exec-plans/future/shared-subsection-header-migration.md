# Shared Subsection Header Migration

## Status

Partially complete baseline. Commit `417f4b37` introduced the shared
`SubsectionHeaderLabel` contract, routed `SectionCard` titles through it, wired
the shared QSS helper into the theme/style-token stylesheets, and migrated the
first curated Main App, Stats, Plot Generator, and Ratio Calculator headings.

This remains a future plan for any additional curated subsection-heading
migration. Do not treat every plain `QLabel(...)` as remaining work.

## Target

Shared title and subsection header presentation across PySide6 GUI surfaces.

Primary component owner:

- `src/Main_App/gui/widgets/labels.py`
- `src/Main_App/gui/widgets/cards.py`
- `src/Main_App/gui/components/__init__.py`
- `src/Main_App/gui/theme.py`
- `src/Main_App/gui/style_tokens.py`

Primary GUI surfaces:

- `src/Main_App/gui/ui_main.py`
- `src/Main_App/gui/settings_panel.py`
- `src/Main_App/gui/sidebar.py`
- `src/Tools/Stats/ui/`
- `src/Tools/Plot_Generator/`
- `src/Tools/Ratio_Calculator/`
- `src/Tools/Individual_Detectability/`
- `src/Tools/Average_Preprocessing/New_PySide6/`

## Summary

The app needs one shared edit point for subsection title presentation: font,
size, color, weight, padding, and related QSS should be controlled from the
shared subsection-header component layer. Top-level `SectionCard` titles are
now centralized mechanically through `CardHeader.title_label`. Free-floating
labels still require a curated pass because many plain `QLabel(...)` instances
are ordinary form labels, status text, helper text, table contents, or
button/sidebar text rather than subsection titles.

The remaining goal is to migrate only additional confirmed subsection headers
to `SubsectionHeaderLabel` without restyling normal form labels.

## Current Architecture Evidence

- `SectionCard` is the shared component-layer card primitive in
  `src/Main_App/gui/widgets/cards.py`.
- `CardHeader.title_label` is a `SubsectionHeaderLabel`, so `SectionCard`
  titles already share the subsection-header widget contract.
- `SectionCard` is re-exported through `Main_App.gui.components`.
- Tools build their own layouts independently, but many top-level subsections
  already use `SectionCard("...")`.
- Local headings can still be built independently with `QLabel("...")` and
  manual font changes. These must be reviewed before conversion.
- `SubsectionHeaderLabel` and the QSS helper live in
  `src/Main_App/gui/widgets/labels.py`.
- `SubsectionHeaderLabel` is re-exported from `Main_App.gui.components` and
  `Main_App.gui.widgets`.
- `build_subsection_header_stylesheet()` is included by both
  `src/Main_App/gui/theme.py` and `src/Main_App/gui/style_tokens.py`.

## Detection Strategy

Use two inventories.

### Structured Inventory

Find shared section cards:

```powershell
rg -n "SectionCard\(" src/Main_App src/Tools -g "*.py"
```

Expected classification:

- `SectionCard(...)`: already centralized through `CardHeader.title_label`.
- `SectionCard` title text should not need per-surface font styling.

### Heuristic Inventory

Find local label headings and manual styling:

```powershell
rg -n --fixed-strings "QLabel(" src/Main_App src/Tools -g "*.py"
rg -n --fixed-strings "setBold(True)" src/Main_App src/Tools -g "*.py"
rg -n --fixed-strings "setProperty(\"caption\"" src/Main_App src/Tools -g "*.py"
rg -n --fixed-strings "SubsectionHeaderLabel" src/Main_App src/Tools -g "*.py"
```

Classify each hit as one of:

- `already-centralized`: `SectionCard` titles or `SubsectionHeaderLabel`.
- `candidate-heading`: plain `QLabel` or helper-built label that visually acts
  as a subsection, table, or local group heading.
- `not-heading`: form labels, field labels, helper paragraphs, status text,
  table content, empty spacer labels, sidebar button text, hero/welcome text,
  progress/log body text, dialog body text, or button labels.

Do not convert `not-heading` labels.

## Migrated Baseline Scope

Commit `417f4b37` migrated the first curated visible headings and added focused
smoke coverage for the touched surfaces.

The following labels are on the shared subsection header layer:

Home page:

- `Processing Options`
- `Condition`
- `Trigger ID`
- `Log`

Statistical Analysis, Basic tab:

- `File I/O`
- `Included Conditions`
- `Manual Exclusions`
- `Significant Results Summary:`

Statistical Analysis, Advanced tab:

- `Summed BCA definition`
- `Outlier Flagging`
- `Comparison Exports`
- `Last Export`
- `ROI Context`

SNR Plot tool:

- `File I/O`
- `Plot Parameters`
- `Advanced`
- `Legend labels (optional)`
- `Log Output`
- `Condition A`
- `Condition B`
- `ROI`
- `Axis Ranges`

Ratio Calculator:

- `Conditions`
- `Condition A`
- `Condition B`
- `Condition A Folder`
- `Condition B Folder`
- `Condition A Label`
- `Condition B Label`
- `Output Folder`
- `Run Label`
- `Participant exclusions (optional)`
- `ROIs (read-only)`
- `Harmonic settings`
- `Run`

Sidebar:

- `Workspace Tools`
- `Utilities`

This is not the full final list. Continue the pass only as the user confirms
additional text that should count as a subsection header.

## Behavior To Preserve

- Do not change processing behavior, file dialogs, project paths, exports,
  worker wiring, or result formats.
- Do not change tab names unless explicitly requested.
- Do not restyle ordinary form labels such as `Path:`, `Filter:`, `Method:`,
  `Excel Files Folder:`, `X Range:`, or field labels unless the user explicitly
  confirms them as subsection headers.
- Preserve existing object names, signal connections, button properties,
  section-card layout spacing, scroll behavior, and visible/manual workflows.
- Do not introduce Tkinter, PyQt, or new GUI frameworks.
- Do not add fallback styling paths that can silently diverge from
  `SubsectionHeaderLabel`.

## Implementation Plan

### Phase 1: Freeze The Shared Contract

Status: complete in `417f4b37`.

1. Confirmed `SubsectionHeaderLabel` owns widget-level defaults:
   - point-size delta
   - font weight
   - alignment
   - `subsectionHeader` dynamic property
2. Confirmed `build_subsection_header_stylesheet()` owns QSS-level defaults:
   - color
   - CSS font weight
   - padding
3. Confirmed `CardHeader.title_label` is a `SubsectionHeaderLabel`.
4. Removed separate subsection-heading QSS paths that would silently diverge.
5. Updated `tests/gui/test_ui_components_smoke.py` to pin this contract.

### Phase 2: SectionCard Audit

Status: baseline complete because all `SectionCard` titles now route through
`CardHeader.title_label`; still rerun the structured inventory before future
surface-specific edits.

1. Run the structured inventory command.
2. For each `SectionCard(...)`, verify the title is intended to be a subsection
   title.
3. If a surface hides a `SectionCard` header, record that as intentional and do
   not re-show it unless requested.
4. Add or update focused smoke assertions for surfaces the user explicitly
   names.

### Phase 3: Local Heading Audit

Status: started. Continue only with confirmed candidate headings.

1. Run the heuristic inventory commands.
2. Create a short migration table with columns:
   - file
   - line
   - text
   - current widget/helper
   - classification
   - action
3. Convert only confirmed `candidate-heading` labels to
   `SubsectionHeaderLabel`.
4. Keep form labels and body/helper labels as plain `QLabel`.
5. Remove any local bold-label helper that exists only for subsection headings.

### Phase 4: Surface-Specific Passes

Status: started. Home/shell, Statistical Analysis, SNR Plot, and Ratio
Calculator have initial converted headings. Remaining surfaces should be scoped
one group at a time.

Use one surface group per small change set:

1. Home and shell:
   - `src/Main_App/gui/ui_main.py`
   - `src/Main_App/gui/sidebar.py`
   - `src/Main_App/gui/settings_panel.py`
2. Statistical Analysis:
   - `src/Tools/Stats/ui/`
3. SNR Plot:
   - `src/Tools/Plot_Generator/`
4. Ratio Calculator:
   - `src/Tools/Ratio_Calculator/`
5. Remaining embedded tools:
   - `src/Tools/Individual_Detectability/`
   - `src/Tools/Average_Preprocessing/New_PySide6/`

Stop after each group and report exactly which visible strings were migrated.

### Phase 5: Guardrails

Add or update tests and docs so future GUI edits do not reintroduce ad hoc
heading styles:

- Component contract tests should assert `SectionCard.header.title_label` is a
  `SubsectionHeaderLabel`.
- Focused GUI smoke tests should assert explicitly named headers are
  `SubsectionHeaderLabel`.
- Architecture docs should say section-card titles and local subsection headers
  use the same component/style contract.
- Consider a lightweight audit script only after the curated allowlist is
  stable. It should flag manual heading patterns for review, not auto-fail on
  all `QLabel(...)` usage.

## Verification Plan

Do not run offscreen Qt workflows locally in this repo. Use non-GUI checks and
document a visible smoke path.

Run focused checks after each surface group:

```powershell
.\.venv1\Scripts\python.exe -m py_compile <touched Python files>
.\.venv1\Scripts\python.exe -m ruff check <touched Python files> --ignore F401,F405
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check gui
git diff --check
```

Visible/manual smoke path:

1. Launch the app normally.
2. Confirm each migrated header uses the same visual presentation.
3. Change one constant or stylesheet value in `labels.py`.
4. Relaunch and confirm all migrated headers update together.
5. Confirm ordinary form labels did not take on subsection-header styling.

## Reporting Requirements

Future agents using this plan must report:

- Which surface group was migrated.
- Exact visible strings converted.
- Exact files touched.
- Which `QLabel(...)` candidates were intentionally left alone and why.
- Whether all converted labels now route through `SubsectionHeaderLabel`.
- Commands run and results.
- Manual smoke steps completed or skipped, with residual risk.

## Manual Verification Before Activation

Before editing, rerun the detection commands because GUI surfaces are changing
actively. Treat the user-confirmed label list as authoritative over heuristics.
If a label is ambiguous, ask before converting it.
