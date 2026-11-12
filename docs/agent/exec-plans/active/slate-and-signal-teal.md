# Slate & Signal Teal for FPVS Toolbox

## Status

Applied in source on `codex/slate-signal-teal`. The approved Windows Qt
smoke checks passed. Cross-platform coverage remains in CI.

## Target

Apply the palette to the PySide6 shell, navigation, shared controls, and
workflow chrome. Keep the Toolbox icon and existing typography. The app uses
Fusion light by default, with a dark header and sidebar. Preserve the
platform menu appearance described in the [GUI architecture](../../architecture/gui.md).

Use [style_tokens.py](../../../../src/Main_App/gui/style_tokens.py) for shared
roles, [theme.py](../../../../src/Main_App/gui/theme.py) for Qt palette and
stylesheet application, and the [shared components](../../../../src/Main_App/gui/components/)
for existing buttons, fields, and status banners.

## Palette

| Role | Color | Toolbox use |
| --- | --- | --- |
| Masthead | `#222F3B` | Dark header and sidebar chrome |
| Paper | `#F3F6F8` | Light workspace |
| Panel | `#FFFFFF` | Forms and data surfaces, and text on filled teal actions |
| Ink | `#1D2A34` | Primary text on light surfaces |
| Muted | `#4D626D` | Metadata and secondary text on light surfaces |
| Action | `#00646C` | Primary actions and links on light surfaces |
| Selection | `#DDEEF0` | Selected rows and controls on light surfaces |
| Dividers | `#CBD9DE` | Section and table rules |
| Controls | `#6A7C87` | Input and control boundaries |
| Light focus | `#805C23` | Focus indicator on light surfaces |
| Signal on dark | `#25B8C4` | Selection accent on dark chrome, paired with light text |

Keep status colors tied to success, warnings, errors, and destructive
actions. Preserve labels and other cues for those states. Keep scientific
palettes with their figures and tools, including condition and group colors,
spectra, scalp maps, and QC encodings. Preserve preprocessing and statistical
contracts, project formats, and exported figures and tables.

## Implementation

1. Map the selected roles onto the shared Qt palette and tokens. Inventory
   hardcoded chrome colors in the header, sidebar, widgets, and tool pages.
   Review foreground and background pairs for each state before replacing a
   value. Use the existing light theme and dark shell roles. Adding a full
   desktop dark mode or appearance preference requires a separate decision.
2. Apply the palette to shared navigation, fields, buttons, and selection
   states in the main window. Review a project workspace with keyboard focus
   and both light and dark system menu appearances. Confirm that disabled
   controls and status messages remain legible.
3. Extend the shared roles to representative embedded tools and dialogs,
   starting with Preprocessing/QC and Stats. Replace tool-local chrome
   colors only where shared roles serve the same purpose. Record the
   implemented appearance in the existing [frontend guidance](../../design-docs/FRONTEND.md).

## Audit findings and changes

- Settings used a single row of seven tabs. It now has Studio-style category
  navigation and a shared Save/Cancel row. The existing page host still routes
  shortcuts and validation to the correct page. Application separates project
  files and cache actions, analysis defaults, and diagnostics.
- The first visible run found that the Settings navigation and ROI pane
  together forced the dialog to 1116 px wide. The ROI actions now fit in a
  narrower pane while the map keeps its 600 × 550 minimum and 36 px targets.
- The shared palette now covers the shell, controls, selection, focus, and
  progress. The old blue accents were replaced in shared styles. Settings uses
  teal selection and an ochre focus border with the current font roles.
- Home recording and folder fields have label associations, Run uses a shorter
  status message, and the empty project chooser names the available actions.
  Embedded SNR and Stats use shorter input labels and keep their workflow and
  scientific guidance. Free Harmonic Clustering labels are associated with
  their controls, including the recording-exclusion checkboxes.

## Verification

- The focused GUI gate and repository precommit gate passed locally. The
  GUI gate ran with the repository's native Qt guard in place.
- Targeted project selection and SNR checks passed (27 passed, 1 skipped).
  All 370 targeted FHC checks passed with a short Windows temporary path.
- The strict MkDocs build passed.
- Windows visible Qt smoke passed 41 cases with synthetic projects and
  isolated settings. Coverage included all seven Settings categories at
  1020 × 790, the 1280 × 900 shell, embedded Protocol and QC layouts, ROI
  editing, SNR, Stats, and Free Harmonic Clustering.
- Nine Settings cases also passed at each of `QT_SCALE_FACTOR=1.25` and
  `QT_SCALE_FACTOR=1.5`. This covered control bounds, keyboard navigation,
  and invalid Save returning focus to the field. The scale factors apply to
  the test process.
- Verify contrast on the rendered light and dark surfaces for text, focus,
  and control boundaries. Check hover, selected, disabled, validation, and
  destructive states.
- Use synthetic projects for visible checks at the supported 1280 × 900
  workspace size and at high DPI. Check Home, Settings, menus, Preprocessing/QC,
  and Stats on supported desktop platforms. Verify keyboard order, selection
  and long labels, and inspect a representative figure and export.
- Use the existing Qt smoke suite in CI. Record visible checks separately
  from the automated results.

The [GUI polish plan](../future/gui-design-polish-accessibility.md) covers broader
accessibility and interaction work.
