# Shared GUI Component Layer Inventory

Status: Slice 0 inventory completed on 2026-05-15. Updated through Slice 4 on
2026-05-16 after normalizing the public component export contract, adopting the
first runtime `ActionRow` surface, and pinning section/path/status contracts for
low-risk auxiliary tools.

Scope: inventory of shared GUI primitives, consumers, duplicate local patterns,
and migration candidates. Slice-specific sections below record implementation
updates as shared components are adopted.

## Current Component Exports

| Component or pattern | Current owner module | Current consumers | Duplicate local implementations | Stable object names and signals | Theme tokens or local style strings | Worker, path, message, or export behavior | Migration risk | Recommended slice |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `make_action_button` | `src/Main_App/gui/widgets/buttons.py`, re-exported by `Main_App.gui.components` | Main window UI, Settings, Plot Generator, Ratio Calculator, Stats UI, Image Resizer, Individual Detectability, Advanced Averaging | Many local button rows still manually assemble buttons and spacing; sidebar uses custom `SidebarButton`; some Stats actions create buttons dynamically | Existing button text, `variant`, variant boolean property, `compact`, and connected slots must remain stable | Styled through app stylesheet selectors for `primary`, `secondary`, `tertiary`, and `danger` | Connected slots may launch workers, subprocess tools, exports, or dialogs | Low for export cleanup; medium when migrating dynamic action groups | 2 for export tests, 3 for action-row consolidation |
| `SectionCard` and `CardHeader` | `src/Main_App/gui/widgets/cards.py`, re-exported by `Main_App.gui.components` | Main window UI, Settings, Plot Generator, Ratio Calculator, Stats UI, Image Resizer, Individual Detectability, Advanced Averaging | Direct `QGroupBox`, `QFrame`, and local section-builder patterns remain in older tool surfaces | Object names such as `processing_group`, `event_map_group`, `log_group`, `ratio_calculator_*`, `image_resizer_*`, and `individual_detectability_*` must remain stable | Uses `SECTION_PADDING`; card header exposes `cardHeader` and title-label property | Presentation-only; must not absorb processing, export, project mutation, or worker logic | Low for new surfaces; medium for existing dense Stats/Ratio/Plot sections | 4 |
| `make_form_layout` | `src/Main_App/gui/widgets/forms.py`, re-exported by `Main_App.gui.components` | Main window UI, Settings, Plot Generator, Ratio Calculator, Stats UI, Image Resizer, Individual Detectability | Local `QFormLayout` setup still appears where older surfaces own custom layout behavior | Label alignment, field growth policy, and row order must remain stable | Standard spacing and `Qt.AlignRight | Qt.AlignVCenter` labels | Presentation-only; field parsing and validation stay in owning surface | Low | 2 for explicit export contract, 4 for touched sections |
| `PathPickerRow` | `src/Main_App/gui/widgets/forms.py`, re-exported by `Main_App.gui.components` | Plot Generator, Image Resizer, Individual Detectability | Ratio Calculator, Stats, Main App processing inputs, and Average Preprocessing still build path rows with direct `QLineEdit` plus `QFileDialog` buttons | Existing line-edit names, button labels, filters, default dirs, and Cancel no-op behavior must remain stable | Uses action-button styling and row spacing | High path risk: project-root discipline, dialog filters, environment-derived defaults, open-folder actions | Medium | 4, with project-path audit |
| `StatusBanner` | `src/Main_App/gui/widgets/status.py`, re-exported by `Main_App.gui.components` | Ratio Calculator, Stats UI, Image Resizer, Individual Detectability | Main window status bar/busy label and some tool log/status labels are local; Plot Generator console/status remains custom | Text timing, severity variant, `setText`, `text`, and `statusVariant` must remain stable | Styled by `statusVariant`; uses inline banner padding | Worker progress/error/finished slots update banners in tool windows | Medium when connected to worker state | 4 or 5 |
| `SurfaceSize` and `configure_window_surface` | `src/Main_App/gui/components/surfaces.py` | Plot Generator, Ratio Calculator, Stats main window, Individual Detectability, Advanced Averaging | Several dialogs/windows still set title, size, and minimums directly | Window title, minimum size, and `fpvsSurface` property must remain stable | App surface styling uses `fpvsSurface` | Presentation-only; no worker or path behavior | Low | 2 for import contract, 4 for touched windows |
| `AppDialog` | `src/Main_App/gui/components/surfaces.py` | Component smoke tests; no broad runtime consumers found in the inventory | Existing dialogs still subclass `QDialog` directly | Modal behavior and root-layout margins must remain stable before adoption | `fpvsSurface` plus fixed dialog margins | Dialog message and validation behavior stay in owners | Low but currently unused | 5 unless a new dialog needs it |
| `show_info`, `show_warning`, `show_error`, `confirm` | `src/Main_App/gui/components/messages.py` | Image Resizer and Individual Detectability use part of the helper set; smoke tests cover delegation | Main App, Settings, Plot Generator, Ratio Calculator, Stats, and Advanced Averaging still use `QMessageBox` directly | Modal vs non-modal behavior, titles, default buttons, and button roles must remain stable | Native `QMessageBox`; no theme token beyond app stylesheet | High behavior risk where confirmation or completion dialogs affect run/export flow | Medium | 3, only for touched dialogs |
| `ActionRow` and `make_action_row` | `src/Main_App/gui/components/actions.py` | Component smoke tests; Image Resizer actions panel | Many surfaces still build local `QHBoxLayout` action rows with manual stretch/spacing | Button order, alignment, shortcuts, and connected slots must remain stable | Row spacing only | Presentation-only; does not own action behavior | Low | 3 |

## Slice 2 Export Contract

`Main_App.gui.components.__all__` is now the explicit public export contract for
the shared component layer. Component consumers should import from
`Main_App.gui.components`, not from lower-level widget owner modules, unless an
existing compatibility path has a specific reason to do so.

The current export set is:

- `ActionRow`
- `AppDialog`
- `BrainPulseWidget`
- `BusySpinner`
- `CardHeader`
- `PathPickerRow`
- `SectionCard`
- `StatusBanner`
- `SurfaceSize`
- `confirm`
- `configure_window_surface`
- `make_action_button`
- `make_action_row`
- `make_form_layout`
- `show_error`
- `show_info`
- `show_warning`

Slice 2 tests pin that export tuple, direct consumer import style, and a narrow
subprocess check proving `import Main_App.gui.components` does not create a
`QApplication`.

## Slice 3 Action Row Adoption

`src/Tools/Image_Resizer/pyside_resizer.py` is the first runtime surface moved
to `make_action_row`. The migrated panel is intentionally small and preserves:

- visible labels: `Process`, `Cancel`, and `Open Folder`;
- button order: process, cancel, open folder;
- variants: primary process button and danger cancel button;
- initial enabled states: cancel and open-folder disabled;
- existing signal connections to `_start`, `_cancel`, and `_open_folder`;
- worker/thread behavior, image processing, path behavior, and message helpers.

The focused smoke coverage in `tests/gui/test_image_resizer_gui.py` now asserts
that the Image Resizer actions panel uses `ActionRow` while preserving button
labels, variants, and enabled states.

## Slice 4 Section, Path, And Status Contracts

Slice 4 kept the implementation narrow and focused on Image Resizer plus
Individual Detectability. Both tools already used shared `SectionCard`,
`PathPickerRow`, and `StatusBanner` components, so the slice added stable hooks
and tests instead of changing path selection behavior.

Runtime hooks added:

- `image_resizer_input_row`
- `image_resizer_output_row`
- `image_resizer_status`
- `individual_detectability_input_root_row`
- `individual_detectability_output_root_row`
- `individual_detectability_status`

Focused smoke coverage now asserts:

- expected section-card object names remain present;
- path rows are shared `PathPickerRow` instances with stable object names;
- status widgets are shared `StatusBanner` instances with stable object names,
  text, and `statusVariant`;
- file-dialog Cancel is a no-op for Image Resizer input/output folder selection;
- file-dialog Cancel is a no-op for Individual Detectability input/output root
  selection and does not update `_last_dir`.

No file-dialog titles, defaults, path writes, worker signals, or generated
outputs changed.

## Current Runtime Consumers

Active consumers found by the Slice 0 search:

- `src/Main_App/gui/ui_main.py`
- `src/Main_App/gui/settings_panel.py`
- `src/Tools/Plot_Generator/ui_sections.py`
- `src/Tools/Plot_Generator/settings_dialog.py`
- `src/Tools/Ratio_Calculator/gui.py`
- `src/Tools/Stats/ui/stats_window_support.py`
- `src/Tools/Stats/ui/stats_manual_exclusion_dialog.py`
- `src/Tools/Image_Resizer/pyside_resizer.py` (uses `PathPickerRow`,
  `SectionCard`, `StatusBanner`, message helpers, and `ActionRow`; Slice 4
  pins path/status object names and Cancel no-op behavior)
- `src/Tools/Individual_Detectability/main_window.py` (uses `PathPickerRow`,
  `SectionCard`, `StatusBanner`, message helpers; Slice 4 pins path/status
  object names and Cancel no-op behavior)
- `src/Tools/Average_Preprocessing/New_PySide6/main_window.py`

The inventory also found `src/Tools/Stats/ui/stats_window_ui.py`,
`stats_window_actions.py`, and `stats_window_exclusions.py` using component names
through the Stats support/mixin import structure. Treat Stats UI migration as
high-context work and use the Stats future plans before moving those methods.

## Duplicate Local Patterns

| Pattern | Current locations | Risk and suggested handling |
| --- | --- | --- |
| Direct `QMessageBox` calls | Main App project/processing/tool workflows, Settings, Plot Generator, Ratio Calculator, Stats UI, Average Preprocessing | Do not sweep-convert. Convert only when a touched workflow already needs message cleanup, because confirmation defaults and completion dialogs are behavior. |
| Direct `QFileDialog` path pickers | Main App processing inputs, Plot Generator, Ratio Calculator, Stats, Image Resizer, Individual Detectability, Average Preprocessing | Good Slice 4 candidate only when path defaults, filters, Cancel, project-root behavior, and open-folder behavior are covered. |
| Manual button rows | Main window run row, Plot Generator bottom actions, Ratio run/actions, Stats export/action rows, Advanced Averaging action rows | Good future candidate after the Image Resizer runtime adoption test. Preserve order, labels, enabled states, and signal wiring. |
| Local status/log panels | Main App status bar, Plot Generator console, Ratio run panel, Stats status/log, Image Resizer progress, Individual Detectability run panel | Keep domain-specific logs local. Centralize only reusable status-banner/progress presentation. |
| Local style strings | Plot Generator color swatch buttons, Main App debug label, status-bar busy label, sidebar stylesheet, header stylesheet | Do not force into components unless repeated. Color swatches and sidebar visual behavior are intentionally local for now. |
| Custom sidebar buttons | `src/Main_App/gui/sidebar.py` | Intentionally local. The sidebar owns keyboard/mouse behavior, selection bar, icon tinting, and navigation grouping. |

## Risk-Ranked Migration Candidates

1. Low risk: strengthen `Main_App.gui.components` export/import tests for no
   side effects, public `__all__`, and existing component smoke contracts.
2. Low risk: adopt `ActionRow` in a touched small dialog or tool settings dialog
   where button order and slots are simple.
3. Medium risk: normalize message helpers in Image Resizer or Individual
   Detectability because they already use shared message helpers partially.
4. Medium risk: migrate touched path rows to `PathPickerRow` only with
   project-path audit and Cancel/no-op tests.
5. High risk: Stats UI component migration. It has dense worker, export,
   reporting, and status lifecycle behavior and should follow Stats-specific
   future plans.
6. High risk: Ratio Calculator GUI path/status/run workflow migration. It is
   already planned separately and should preserve worker signal behavior,
   validation banner behavior, participant exclusion state, and output paths.
7. High risk: Plot Generator worker/rendering behavior. Component work should
   avoid generated plot content, filenames, and Excel-reading behavior.

## Intentionally Local Patterns

- Direct Qt widgets for simple labels, line edits, combo boxes, check boxes,
  tables, and splitters remain acceptable.
- Sidebar custom navigation remains local because it owns selection state,
  keyboard activation, icon tinting, and persistent layout.
- Color swatch buttons in Plot Generator remain local because their dynamic
  inline background color is domain-specific.
- Main App status bar and launch-reveal behavior remain local because they
  coordinate app shell state rather than reusable tool-window presentation.
- Stats result/export/reporting UI remains local until a Stats-specific slice is
  active.

## Verification Notes

Commands run:

- `python .agents/scripts/audit/agent_audit.py` - PASS.
- `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` - PASS.
- `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` - PASS.
- `python -m pytest tests/gui/test_ui_components_smoke.py -q` - PASS, 9 passed.
- `rg "from Main_App\\.gui\\.components|from Main_App\\.gui\\.widgets" src/Main_App/gui src/Tools -g "*.py"` - PASS.
- `rg "QAction|QMessageBox|QFileDialog|QProgressDialog|statusBar\\(|setStyleSheet|setObjectName" src/Main_App/gui src/Tools -g "*.py"` - PASS.
- `rg "customtkinter|CustomTkinter|tkinter" src -g "*.py"` - PASS; matches were standalone/quarantine references, not active GUI imports.
- `rg "Main_App\\.Legacy_App|Tools\\.SourceLocalization|Main_App\\.PySide6_App" src -g "*.py"` - PASS; no active matches returned.

No tests were added or updated because Slice 0 is inventory-only.
