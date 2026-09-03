# SSSEP-Style Visual ROI Selector for FPVS Toolbox

## Status

Active; implementation is complete locally and awaits registered CI Qt plus
visible installed-application acceptance. Work was performed on 2026-09-03 on
`codex/sssep-roi-selector`, branched from FPVS
`codex/v3-release` at `f586652e0bf9920eb42ce9e8a75b5b08f2717f31`.
The feature is explicit v3 scope in `active/v3-release-readiness.md`; the final
installed-application acceptance pass must include the ROI workflow.

Planning baseline:

- FPVS Toolbox target: `f586652e0bf9920eb42ce9e8a75b5b08f2717f31`
- SSSEP source reference: `d19d585517d0328eee965935688ba9ba161fd0d0`
- SSSEP electrode-map provenance retained from `roi-explorer.js` commit
  `3b797ad45fdecf688a9d82b869a6b7a908f7a555` and the BioSemi cap coordinate
  sheet cited by the source module.

## Executive Outcome

Add the SSSEP nose-up, clickable BioSemi64 electrode map to **Settings > ROIs**
so a user can build or edit an FPVS ROI visually instead of having to type every
comma-separated electrode name.

This is an additive visual editor for the ROI model FPVS already has. FPVS will
continue to own persistence, presets, harmonic invalidation, downstream ROI
averaging, and plot export. The port must not introduce an SSSEP settings file,
change ROI mathematics, change workbook schemas, or change figure filenames.

Expected delivery shape: three focused implementation slices plus documentation
and release verification. Scientific risk is low because no numerical path
changes; GUI-state and settings-compatibility risk is moderate and is addressed
by the transaction, ordering, and live-refresh gates below.

## Executive Decisions

| Decision | Direction |
| --- | --- |
| What is being ported | The scalable electrode map, keyboard-accessible selection behavior, selection summary, preset application, Clear, Use, and Cancel interaction. |
| What is not being ported | SSSEP's `.sssep_rois.json`, launcher settings, FFT loader, workers, plot math, TENS terminology, dark-theme QSS, or saved-plot output flow. |
| Canonical ROI storage | Keep `SettingsManager` and the existing `[rois]` / `[roi_presets]` INI schema. No migration and no new project metadata. |
| Save boundary | The selector edits a draft. Only the outer Settings Save writes preferences or enters the existing harmonic recalculation/rollback flow. |
| Preset source | Use FPVS's existing montage-aware LOT, ROT, Central, and custom presets. Do not copy SSSEP's preset memberships or add its Fronto-central example. |
| Channel universe | Show the canonical FPVS BioSemi64 electrodes and preserve any already-configured noncanonical labels in a separate fallback list/text field. Do not scan workbooks or run MNE from the dialog. |
| Existing editor | Retain the current name and comma-list rows as a compatibility/fallback surface; add a compact visual-selector action for each row. |
| Downstream behavior | Refresh cached ROI consumers after Settings commits, but do not mutate an active plot worker's snapshotted request. |
| Output contract | No changes to ROI averaging, FullSNR reads, conditions/groups/sessions, plot rendering, 600-DPI PNG/PDF pairs, names, or folders. |

## Current Backbone and Actual Gap

FPVS already has the feature's data and analysis backbone:

- `src/Main_App/Shared/settings_manager.py` owns default ROI definitions,
  active ROI pairs, montage selection, and per-montage custom presets.
- `src/Main_App/processing/roi_settings.py` is the neutral runtime read surface.
- `src/Main_App/gui/settings_panel.py` owns the ROIs tab, Quick Add presets,
  Settings Save, harmonic-change detection, recalculation, and rollback.
- `src/Main_App/gui/roi_settings_editor.py` already preserves ordered ROI rows
  and translates their comma-separated fields into `(name, electrodes)` pairs.
- `src/Tools/Plot_Generator/` already filters FullSNR data by ROI, averages
  electrodes within participant, averages participants within the selected
  condition/group, and writes publication PNG/PDF pairs.
- Stats, Ratio Calculator, processing QC, and analysis-ready exports already
  read the same saved ROI definitions.

The missing product surface is a visual electrode picker. The current editor is
free text only. There is also one adjacent integration defect to close: the Main
Window caches the SNR Plot Generator page, while that page loads `roi_map` only
when constructed. Saving a new ROI after SNR Plots has already been opened can
therefore leave its ROI combo and mapping stale until the page is recreated.

## Source-to-Target Map

| SSSEP source | FPVS target/adaptation |
| --- | --- |
| `sssep_batch/roi_selection_gui.py::_ElectrodeMap` | New focused GUI module, proposed as `src/Main_App/gui/roi_electrode_selector.py`; port geometry, scaling, painting, accessible toggle buttons, and keyboard behavior. |
| `sssep_batch/roi_selection_gui.py::RoiSelectionDialog` | FPVS `AppDialog` using shared actions, status presentation, typography, and light-theme tokens; no direct persistence. |
| SSSEP `_ELECTRODES` coordinate table | Retain with attribution and assert one-to-one case-insensitive coverage of `config.DEFAULT_ELECTRODE_NAMES_64`. It is a selection aid only, never an analysis montage. |
| SSSEP `_PRESETS` | Do not copy. Inject default/custom preset data from the existing FPVS montage catalog. |
| SSSEP `.sssep_rois.json` library | Do not port. Continue using `SettingsManager` and stage custom-preset changes until outer Save. |
| SSSEP Settings ROI list | Integrate the modal into the existing `ROISettingsEditor` rows and preserve `get_pairs()`, `set_pairs()`, and `add_or_update_entry()` behavior. |
| SSSEP saved FFT plotting stack | Do not port. FPVS Plot Generator, Stats, Ratio Calculator, and exports remain the consumers. |
| SSSEP offscreen subprocess GUI tests | Translate into registered FPVS pytest-qt coverage for CI plus local pure-state tests and a visible manual smoke path. |

## Target User Workflow

1. The user opens **Settings > ROIs** and sees the existing ordered ROI rows and
   Quick Add preset controls.
2. Each row has a compact **Select electrodes...** action. The existing
   `+ Add ROI` action still creates a row; the same selector can open immediately
   for a newly added row if that does not disturb the established object-name
   and keyboard order contracts.
3. The modal opens with the row's current name and electrodes. The map is
   nose-up, shows all 64 canonical BioSemi positions, and supports pointer and
   keyboard activation. Selection state must remain understandable without
   relying on color alone.
4. Choosing an existing FPVS default or custom preset updates the draft map and
   reports any unavailable/unmapped members. Existing Quick Add behavior remains
   available in this first release; consolidating duplicate preset affordances
   is a separate polish decision.
5. **Use Selection** updates only the targeted Settings row. **Cancel**, window
   close, or Escape is a strict no-op. **Clear** changes only the modal draft.
6. The user may still type or retain a noncanonical electrode label in the
   comma-list field. Reopening and accepting the map must not silently delete it.
7. Only **Save** on the outer Settings surface persists ROI pairs and custom
   presets. If the ROI change affects the current Legacy harmonic-selection
   signature, the established recalculate/decline/rollback workflow remains in
   control.
8. Existing SNR Plots, Stats, and Ratio Calculator pages refresh their ROI
   options after the commit. A newly selected ROI is usable in the same app
   session without a restart.

## Locked Compatibility Rules

- Preserve the existing app-level settings location and INI keys:
  `rois.montage`, `rois.names`, `rois.electrodes`, and montage-keyed custom
  presets. ROI settings do not move into `project.json`.
- Preserve ROI order, ROI display names, and electrode order when the user makes
  no effective change. The harmonic settings signature contains ordered tuples;
  a visual round trip must not create a false recalculation prompt.
- When a selection changes, retain surviving electrodes in their prior order
  and append newly selected canonical electrodes in deterministic BioSemi64
  order. Persist through the existing uppercase normalization contract.
- The selector requires a nonblank name and at least one electrode before it can
  apply a draft. It must not normalize or deduplicate existing row content as a
  side effect: legacy duplicate ROI names or electrode entries must survive a
  no-op visual round trip. Stricter uniqueness rules would be a separate data-
  compatibility change and are outside this plan.
- Different ROIs may overlap; overlap is scientifically valid and must not be
  warned away or deduplicated across ROIs.
- Existing noncanonical/unmapped labels must remain visible, editable, and
  selected until the user explicitly removes them. The visual picker must never
  silently narrow old settings to the 64 drawn nodes.
- The map defines intended ROI membership. Do not disable nodes based on a
  participant's removed electrodes, current QC exclusions, or one workbook's
  coverage.
- Keep the current FPVS LOT, ROT, and Central definitions exactly as stored in
  `Main_App.Shared.roi_presets`. SSSEP's Central membership differs and must not
  overwrite the FPVS scientific defaults.
- No runtime dependency on the SSSEP repository. Copy/adapt the reviewed code
  into FPVS with attribution.
- No `QThread` is needed: this is bounded, in-memory UI state. Do not add file
  discovery, MNE montage construction, processing, or export work to the dialog.
- Keep `src/Main_App/gui/main_window.py` unchanged unless implementation
  evidence proves unavoidable; it must not receive new functions for this work.
- The modal may use content-native scrolling, but the Settings page must still
  fit the supported 1280x900 workspace without page-level scrolling or nested
  cards.

## Non-Goals

- Changing ROI means, participant weighting, condition/group/session behavior,
  missing-electrode handling, or harmonic-selection methods.
- Changing the FPVS default ROIs or adding new scientifically endorsed presets.
- Adding arbitrary montage design, cap import, sensor-coordinate editing, or
  per-project ROI definitions.
- Moving or redesigning the Settings system, `SettingsManager`, or project
  manifest.
- Changing Plot Generator workers, workbook discovery, renderers, filenames,
  output folders, or figure formats.
- Changing SSSEP code.

## Implementation Plan

### Milestone 0 — Activate and Characterize

Status: complete. Existing schema/order behavior and the cached-consumer gap
are covered by focused tests and code-path receipts; no local Qt session was
used for the pre-change reproduction.

1. Move this plan to `docs/agent/exec-plans/active/` and record the working
   branch and current revisions.
2. Characterize current ROI round trips for ordering, casing, duplicate names,
   incomplete rows, custom presets, outer Save/Cancel, and Legacy harmonic dirty
   detection before modifying the GUI.
3. Add the missing ROI-focused tests to the verification registry:
   - `tests/settings/test_roi_preset_settings.py` under `project-io`;
   - `tests/processing/test_roi_settings.py` under `processing`.
4. Record the pre-change visible workflow at 1280x900 and confirm the SNR page
   stale-ROI reproduction: open SNR Plots, save a changed ROI, return to the
   cached SNR page, and observe its old selection state.

Exit gate: the current settings schema and the stale-consumer bug are covered by
tests or an explicit reproducible receipt.

### Milestone 1 — Port the Selector as a Focused FPVS Component

Status: implementation and pure-state verification complete; registered CI Qt
interaction/layout verification remains pending.

1. Add `src/Main_App/gui/roi_electrode_selector.py`, kept below the repository's
   500-line module target. Split a pure selection-state/catalog helper only if
   needed to stay focused and locally testable.
2. Port the SSSEP 64-node polar geometry, scalable head outline, orientation
   labels, and native checkable `QToolButton` hit targets. Preserve the source
   attribution in code.
3. Build the modal on `Main_App.gui.components.AppDialog`, `SurfaceSize`, shared
   action rows/buttons, `StatusBanner`, typography, and style tokens. Adapt the
   presentation to the FPVS light theme rather than copying SSSEP's dark QSS.
4. Accept constructor data rather than reading settings:
   - available/canonical channel labels;
   - current name and ordered electrode tuple;
   - FPVS default/custom presets for the active montage;
   - configured noncanonical labels that require preservation.
5. Expose a small draft API such as `selected_electrodes()` and
   `selection_name()`. Public results change only when the dialog is accepted.
6. Keep map selection, preset selection, summary text, missing/unmapped text,
   Clear, validation, and action enabled states synchronized.
7. Add pure state tests for canonical coverage, case-insensitive identity,
   stable no-op order, deterministic appended order, unknown-label preservation,
   legacy duplicate preservation, and preset subset behavior. Register
   `tests/gui/test_roi_electrode_selector_state.py` explicitly in
   `[scopes.gui].tests` in `.agents/verification.toml`.

Exit gate: the dialog is settings-agnostic, theme-compliant, accessible, and
proven not to reorder or discard an unchanged ROI.

### Milestone 2 — Integrate Settings Without Replacing Its Model

Status: implementation complete; Settings Save/Cancel/reopen coverage is
registered for CI Qt and remains pending there.

1. Extend `ROISettingsEditor` with one selector action per row. Seed the modal
   from the row's current fields and update that row only on accept.
2. Keep typed comma lists and the visual map bidirectionally compatible. The
   text field remains the route for a new noncanonical label; the dialog lists
   and preserves such labels on later edits.
3. Have `SettingsDialog` supply canonical BioSemi64 labels and the existing
   montage-aware default/custom preset collection. Do not duplicate preset
   membership inside the selector module.
4. Preserve `get_pairs()`, `set_pairs()`, `add_or_update_entry()`, ROI order,
   remove behavior, object names relied on by tests, and the current Quick Add
   preset workflow.
5. Add inline validation for blank names and empty selections. Preserve the
   current manual editor/storage semantics for duplicate ROI names and duplicate
   electrodes, including no-op round trips; do not silently omit, normalize, or
   deduplicate a row created or edited through the selector.
6. Confirm selector Cancel does not alter the row, Settings Cancel does not
   alter the manager/disk, and Settings Save continues through the existing
   persistence and harmonic recalculation/rollback code.

Exit gate: add, edit, preset, manual fallback, remove, cancel, save, reopen, and
rollback all preserve the existing settings contract.

### Milestone 3 — Refresh Cached Consumers and Prove End-to-End Use

Status: implementation and locally safe consumer regressions complete; cached
page interaction coverage remains pending in CI Qt.

1. Add a focused public ROI-refresh method to the Plot Generator page or its
   selection mixin. It must reload through `Main_App.processing.roi_settings`,
   rebuild the combo, preserve the selected ROI when still valid, otherwise
   fall back to `(All ROIs)`, and rerun readiness validation.
2. Invoke the refresh after a successful outer Settings commit and when the
   cached SNR page is reactivated if needed for resilience. Do not update an
   already-running worker request.
3. Preserve the existing Stats refresh path and confirm Ratio Calculator's
   existing dynamic refresh still sees the same mapping. Do not add parallel
   ROI caches.
4. Characterize one single ROI and `(All ROIs)` through Plot Generator using
   the pre-existing worker and output tests. The only changed input should be
   the saved ROI mapping.
5. Confirm a no-ROI configuration produces actionable readiness feedback rather
   than launching a meaningless SNR job; do not invent a fallback ROI.

Exit gate: a saved ROI is available to every current consumer in the same app
session, while worker payloads, calculations, and output identities are
unchanged.

### Milestone 4 — Documentation and Release Closeout

Status: in progress. Documentation, local safe gates, and independent code
review are complete. CI Qt, visible 1280x900 Windows smoke, packaged-app
acceptance, and the optional CachyOS smoke remain.

1. Update `docs/agent/architecture/gui.md` with ownership of the focused
   selector module, its draft-only boundary, and the cached-consumer refresh
   contract. Root `ARCHITECTURE.md` need not change if ownership stays entirely
   inside the existing `Main_App.gui` and `Main_App.processing` boundaries;
   record that decision in the handoff.
2. Update `docs/user/tools/snr-plot-generator.md` to direct users to the visual
   selector in Settings and explain that ROIs are app-level definitions used by
   one/all-ROI plots.
3. Update Stats and Ratio Calculator user guidance only where it currently
   explains ROI definition. Do not imply that visual selection changes raw EEG
   preprocessing.
4. Add a concise note to `src/Tools/Plot_Generator/AGENTS.md` only if the new
   live-refresh method becomes part of its durable public contract.
5. Complete local safe gates, CI Qt coverage, visible smoke, and the final plan
   progress/verification record before moving or removing the completed plan
   according to repository policy.

## Expected File Surface

Primary implementation:

- `src/Main_App/gui/roi_electrode_selector.py` — new visual map/dialog owner.
- `src/Main_App/gui/roi_settings_editor.py` — row-level launch and accepted-draft
  synchronization.
- `src/Main_App/gui/settings_panel.py` — inject catalog/presets and refresh
  existing consumers after commit; do not add selector implementation here.
- `src/Tools/Plot_Generator/gui.py` and/or `selection_state.py` — focused
  `refresh_rois()` seam only.
- `.agents/verification.toml` — add the pure selector-state test to
  `[scopes.gui].tests` and register the existing ROI settings tests in their
  focused scopes.
- `tests/qt_test_files.txt` — register only the new CI Qt interaction test.

Primary tests:

- `tests/gui/test_roi_electrode_selector_state.py` — new locally safe pure-state
  contract.
- `tests/gui/test_roi_electrode_selector_qt.py` — new CI-only interaction and
  layout smoke, or equivalent focused additions to the existing registered
  Settings test.
- `tests/gui/test_gui_preproc_dialog.py` — row integration, Quick Add parity,
  harmonic dirty/recalculation, and rollback.
- `tests/settings/test_roi_preset_settings.py` — unchanged schema and preset
  round trip.
- `tests/processing/test_roi_settings.py` — neutral consumer contract.
- `tests/plot_generator/test_plot_generator_gui.py` or a focused sibling —
  cached-page ROI refresh.
- Existing Plot Generator aggregation/rendering tests remain regression gates,
  not rewrite targets.

Documentation:

- `docs/agent/architecture/gui.md`
- `docs/user/tools/snr-plot-generator.md`
- narrowly relevant Stats/Ratio guidance if needed
- this execution plan while active

## Acceptance Criteria

- All 64 `DEFAULT_ELECTRODE_NAMES_64` channels appear exactly once at the
  expected nose-up coordinates, with a test that the map catalog and canonical
  FPVS channel catalog are set-equal case-insensitively.
- Every map node is pointer- and keyboard-operable and has an accessible name,
  tooltip/description, focus indication, and non-color selected indication.
- Opening and accepting an unchanged ROI preserves its name, electrode order,
  effective casing contract, and harmonic signature.
- Existing duplicate ROI names or duplicate electrode entries survive an
  unchanged visual round trip; this feature does not migrate legacy settings.
- Add/Edit updates only the intended row. Selector Cancel, Escape, and close are
  no-ops. Outer Settings Cancel leaves persisted settings unchanged.
- FPVS default/custom presets populate the map from one existing source of
  truth. No SSSEP preset silently replaces an FPVS definition.
- Existing noncanonical labels survive open/accept/save; users can still edit
  them through the retained text fallback.
- Saving a real ROI change uses the existing settings location/schema and the
  existing Legacy harmonic recalculation, decline, stale, and rollback paths.
- A cached SNR page sees committed ROI additions, edits, and removals without a
  restart. Its current selection is preserved when valid and safely reset when
  removed.
- Stats, Ratio Calculator, processing QC, and analysis-ready exports read the
  same committed mapping without new adapters or divergent caches.
- No Plot Generator worker, ROI calculation, workbook sheet/schema, output
  directory, filename, DPI, PNG/PDF pairing, or participant weighting changes.
- Settings and the focused modal fit and remain usable at 1280x900 on Windows;
  the shared implementation remains compatible with CachyOS.

## Verification Plan

### Initial audits

```console
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
```

The current path audit may report unrelated untracked files under `outputs/`.
Do not clean, edit, or treat those user files as part of this feature.

### Local safe gates

Run in order, letting the verification driver choose `.venv1` or `.venv`:

```console
python .agents/scripts/verify.py --scope gui --tier focused
python .agents/scripts/verify.py --scope project-io --tier focused
python .agents/scripts/verify.py --scope processing --tier focused
python .agents/scripts/verify.py --scope plot-generator --tier focused
python .agents/scripts/verify.py --scope stats --tier focused
python .agents/scripts/verify.py --scope ratio-calculator --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
git diff --check
```

Do not run the `figures` scope unless implementation touches a renderer or
figure-style contract; that would be scope expansion and must be called out.

### CI Qt coverage

Register the selector interaction test in `tests/qt_test_files.txt`. CI must
cover:

- pointer and Space-key toggling;
- accessible names and checked/focus state;
- map geometry and responsive dialog layout;
- current-row targeting and manual/map synchronization;
- FPVS default and custom preset application;
- unknown-label preservation;
- blank-name/empty-selection validation and legacy duplicate preservation;
- Use versus Cancel semantics;
- Settings Save/Cancel/reopen;
- cached SNR-page refresh.

Per repository policy, do not run pytest-qt or an offscreen Qt subprocess on a
local development machine unless the user explicitly approves a safe visible
environment.

### Visible manual smoke

1. Launch FPVS Toolbox normally on Windows 11 at 1280x900.
2. Open **Settings > ROIs**, edit LOT visually, cancel, and confirm the row is
   unchanged.
3. Reopen the selector, toggle electrodes with both pointer and Space, apply,
   and confirm the row summary changes without clipping or losing focus cues.
4. Exercise Quick Add, a custom preset, a typed unmapped label, Add, Edit, and
   Remove. Confirm the unmapped label survives a visual round trip.
5. Cancel Settings and reopen it; confirm nothing was persisted.
6. Save a no-op edit and confirm there is no false harmonic recalculation
   prompt. Save a real ROI edit in a processed project and exercise the existing
   recalculate/decline/rollback choices.
7. Open SNR Plots before and after the Settings change. Confirm the cached page
   refreshes its ROI list and mapping without restarting the app.
8. Open Stats and Ratio Calculator and confirm they show the same ROI names and
   membership.
9. Generate one `(All ROIs)` SNR run from representative data and confirm the
   existing plot names and matching PNG/PDF files are written directly to the
   established SNR output folder.
10. Repeat the selector layout/accessibility smoke on CachyOS when that
    environment is available; otherwise record it as the remaining platform
    risk.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Visual round trip reorders electrodes and triggers unnecessary recalculation | Lock no-op tuple identity; retain prior order and append only new nodes deterministically. |
| SSSEP presets overwrite FPVS defaults | Inject only the FPVS preset catalog and add exact-membership regression tests. |
| Existing custom/noncanonical labels disappear | Keep the comma-list fallback and a visible unmapped-selection list; test open/accept/save preservation. |
| Cached Plot Generator uses stale ROI data | Add and test an explicit refresh seam after commit/reactivation. |
| Selector creates a second settings store | Keep the component persistence-free; all writes remain in outer `SettingsManager.save()`. |
| Dark SSSEP styling clashes with FPVS | Rebuild presentation with `AppDialog`, shared components, typography, and FPVS tokens; port behavior and geometry only. |
| UI becomes too dense | Keep the 64-node map in a focused modal and retain the page's existing top-level cards and 1280x900 fit. |
| Cross-platform/DPI geometry drift | Use scalable coordinates, native controls, pure geometry tests, CI Qt tests, and visible Windows/CachyOS smoke. |
| Scope expands into scientific/output code | Treat any worker, aggregation, renderer, schema, or filename edit as a stop-and-review event. |

Rollback is straightforward because the persisted ROI schema is unchanged. A
revert of the new dialog, row action, and consumer refresh returns FPVS to the
manual editor without migrating or rewriting user data.

## Progress

- [x] Cross-repo architecture and behavior comparison completed.
- [x] FPVS persistence, preset, downstream consumer, and output backbones
      confirmed.
- [x] SSSEP selector source, coordinate provenance, draft behavior, and tests
      identified.
- [x] FPVS-specific preset mismatch and cached SNR-page refresh gap identified.
- [x] Plan promoted to `active/` and implementation branch created.
- [x] Current settings and stale-consumer behavior characterized.
- [x] Visual selector implemented and locally safe state tests passing.
- [x] Settings integration and transactional behavior implemented, including
      cached-page retirement so canceled drafts cannot leak into a later Save.
- [x] Cached Stats and SNR consumers refresh after commits/rollbacks; Ratio
      Calculator's existing signature watcher remains the live refresh owner.
- [x] Documentation, focused local gates, strict docs build, and independent
      selector/integration reviews complete.
- [ ] Registered CI Qt coverage and visible installed-app smoke complete.

## Implementation Receipt — 2026-09-03

- Added the attributed, settings-agnostic BioSemi64 selector and pure ordered
  state helper. No runtime dependency on the SSSEP repository was introduced.
- Preserved no-op name/electrode text exactly at the row boundary. The state
  ledger preserves original order, case, canonical/noncanonical duplicates,
  and unknown labels; real selection additions use deterministic BioSemi64
  order before existing uppercase persistence normalization.
- Added row-scoped visual actions, FPVS montage-aware default/custom preset
  injection, plain-text legacy-label presentation, keyboard/focus metadata,
  and a persistent non-color selected-node cue. Selector dialogs are disposed
  after use, and the embedded Settings page is rebuilt from committed settings
  after Save or Cancel.
- Added `PlotGeneratorWindow.refresh_rois(manager=None)`, actionable empty-ROI
  readiness, independent cached Stats/SNR refresh after commit or rollback,
  and preserved Ratio Calculator's existing signature polling. Worker ROI
  requests remain copied snapshots.
- Schema, ROI averaging/math, scientific defaults, workbook formats, figure
  rendering, output folders/names, DPI, and PNG/PDF pairing are unchanged.

Local verification:

- GUI focused gate: passed; 8 selector-state tests passed.
- Processing focused gate: 375 passed, 1 skipped.
- Stats focused gate: 384 passed.
- Direct project-I/O, Plot Generator, and Ratio Calculator safe bundles: 121,
  110, and 7 tests passed respectively (their drivers stop before tests at the
  pre-existing path-audit findings below).
- ROI/state/settings focused bundle: 15 passed; verification registry validation,
  changed-file Ruff/compilation, strict MkDocs build, protected/source-localization
  audits, and `git diff --check` passed.
- Full locally safe suite: 1,930 passed and 3 skipped; one unrelated
  Publication Maps difference-layout assertion failed by 0.190 pixels and
  failed again in isolation, while its non-difference sibling passed. No
  Publication Maps source or test was changed for this feature.
- Project-I/O, Plot Generator, Ratio Calculator, and repo-precommit drivers are
  blocked by the same eight pre-existing machine-path findings in the untracked
  `outputs/` tree. Those user files were left untouched.
- `tests/gui/test_roi_electrode_selector_qt.py` and the expanded registered GUI
  tests cover map interaction/accessibility/layout, presets and duplicates,
  unknown-label editing, transactional dismissal, Settings Save/Cancel/reopen,
  cached SNR refresh, and active-worker snapshot behavior. They were not run
  locally under the repository's Qt policy.

## Implementation Reporting Requirements

Each implementation handoff must report:

- exact files changed;
- whether the settings schema, ROI math, scientific defaults, or output contract
  changed (expected answer: no);
- how no-op order and noncanonical labels were preserved;
- how cached SNR, Stats, and Ratio Calculator state was refreshed or verified;
- commands run and their results;
- CI-only Qt tests registered;
- visible/manual smoke completed or skipped, with residual risk;
- any unrelated pre-existing working-tree changes left untouched.
