# Embedded Visual ROI Editor for FPVS Toolbox

## Status

Active. The first implementation was committed on 2026-09-03 as
`8d84b216` on `codex/sssep-roi-selector`, branched from FPVS
`codex/v3-release` at `f586652e0bf9920eb42ce9e8a75b5b08f2717f31`.
That commit delivered the reusable BioSemi64 map, ordered selection state,
row-launched modal editor, and cached-consumer refresh seam.

A same-branch follow-up now supersedes the first implementation's page design.
The ROIs tab is now visual-first: the interactive scalp map is embedded on the
left and an ordered, color-coded list of named ROIs is embedded on the right.
The prior comma-list front page, per-row **Select...** actions, separate modal,
and **Quick Add** card are no longer the user workflow. Commit `4f46b4bc`
established that embedded surface. The current refinement removes its enclosing
card, montage/preset toolbar, visible count/heading rows, and redundant project-
root action; labels the fixed map **BioSemi 64**; enlarges its hit targets; and
makes LOT, ROT, and Central protected built-in draft rows. Registered Qt
execution and the visible installed-application smoke remain pending under
repository policy.

Planning baselines:

- FPVS Toolbox branch point: `f586652e0bf9920eb42ce9e8a75b5b08f2717f31`
- first ROI-selector implementation: `8d84b216`
- SSSEP source reference: `d19d585517d0328eee965935688ba9ba161fd0d0`
- SSSEP electrode-map provenance: `roi-explorer.js` commit
  `3b797ad45fdecf688a9d82b869a6b7a908f7a555` and the BioSemi cap coordinate
  sheet cited by the source module

## Executive Outcome

Replace the contents of **Settings > ROIs** with one embedded visual editor:

- a scalable, nose-up BioSemi64 scalp map on the left;
- an ordered list of named ROIs on the right;
- protected, membership-editable LOT, ROT, and Central built-ins;
- one presentation-only color per ROI;
- segmented color rings on an electrode when it belongs to multiple ROIs;
- direct pointer and keyboard toggling for the active ROI;
- name-only text editing; and
- an occurrence-preserving list for configured legacy labels that cannot be
  drawn on the map.

The editor remains an in-memory Settings draft. Only the outer **Save** action
writes the existing ROI preferences or enters the established harmonic
recalculation/rollback workflow. This redesign must not introduce a settings
migration, change ROI mathematics, change scientific presets, or change any
workbook or plot-output contract.

## Decision History and Current Direction

| Decision | Current direction |
| --- | --- |
| First implementation | Commit `8d84b216` added a map in a row-scoped modal while retaining text rows and Quick Add. Its map, ordered state, tests, and consumer-refresh work are the follow-up baseline. |
| Follow-up surface | Embed the map as the primary ROI-tab surface; remove the visible comma-list editor, row selector buttons, modal workflow, and separate Quick Add card. |
| Page layout | One flat map-left/list-right split with no ROI `SectionCard`. A content-native scroll area may be used for the ROI list, but the Settings page must not become page-scrollable. |
| Active ROI | Selecting a row on the right makes that ROI active. A map toggle changes only that ROI and never removes the electrode from another ROI. |
| Overlap visualization | Draw separate ordered color-ring segments for every ROI containing an electrode. Do not blend colors, warn against overlap, or enforce exclusivity. |
| Color persistence | Colors and internal row identities are presentation-only and deterministic within the editor. They are never written to `SettingsManager`. |
| Text editing | Keep text entry for the ROI name only. Electrode membership is edited on the map. Existing noncanonical labels appear as individual retained occurrences with explicit removal controls, not as a comma field. |
| Built-ins | Always materialize LOT, ROT, and Central in the editor draft from the exact shared FPVS catalog when missing. Protect their names and rows, but keep electrode membership editable. |
| Canonical storage | Keep `SettingsManager` and the existing `[rois]` / `[roi_presets]` INI schema. No project-metadata or color-schema additions. |
| Dormant preset compatibility | Remove preset controls from the ROI screen. Preserve existing `[roi_presets]` data and APIs without loading or rewriting them from Settings. |
| Save boundary | All map, name, add, and remove operations edit the current Settings draft. Outer Settings **Cancel** discards them; outer **Save** commits them. |
| Projects root | Show **Change Projects Root...** only in Advanced, not in the ROI or other Settings footers. |
| Downstream behavior | Preserve the first implementation's committed Stats/SNR refresh behavior and Ratio Calculator polling. Never mutate an active worker's snapshotted request. |
| Output contract | No changes to ROI averaging, FullSNR reads, conditions/groups/sessions, plot rendering, 600-DPI PNG/PDF pairs, names, or folders. |

## Current Backbone

FPVS already has the required persistence and analysis backbone:

- `src/Main_App/Shared/settings_manager.py` owns active ROI pairs, montage
  selection, and per-montage custom presets.
- `src/Main_App/processing/roi_settings.py` is the neutral runtime read surface.
- `src/Main_App/gui/settings_panel.py` owns the ROIs tab, Settings Save,
  harmonic-change detection, recalculation, rollback, and cached-consumer
  refresh.
- `src/Main_App/gui/roi_settings_editor.py` owns the ordered draft collection
  composition and its `(name, electrodes)` compatibility API.
- `src/Main_App/gui/roi_visual_editor_state.py` owns stable draft-row identity,
  independent selection ledgers, pair projection, partial-draft checks, and
  deterministic contrast-safe presentation colors.
- `src/Main_App/gui/roi_settings_widgets.py` owns the presentation-only color
  palette, active-ROI controls, action grouping, and keyboard order.
- `src/Main_App/gui/roi_electrode_selector.py` owns the attributed BioSemi64
  map geometry and accessible electrode controls.
- `src/Main_App/gui/roi_electrode_selector_state.py` owns the ordered token
  ledger that preserves legacy duplicates, unmapped labels, and no-op order.
- Plot Generator, Stats, Ratio Calculator, processing QC, and analysis-ready
  exports already consume the saved ROI mapping.

The follow-up gap is presentation and multi-ROI coordination, not persistence
or analysis. `ROISettingsEditor` is the visual embedded collection editor while
preserving `add_entry()`, `get_pairs()`, and `set_pairs()` for Settings callers.

## Target User Workflow

1. Open **Settings > ROIs**. The fixed map is labeled **BioSemi 64** and appears
   immediately on the left; saved ROIs appear in order on the right with a color
   swatch and selection control. The selected custom ROI's name is edited in the
   single name field below the list.
2. Select an ROI row. Its mapped electrodes receive the active ROI fill and
   persistent non-color selection cue. Every electrode also shows the ordered
   color-ring segments for all ROIs that contain it.
3. Click an electrode or focus it and press Space to toggle membership in the
   active ROI only. Membership in other ROIs is unchanged.
4. LOT, ROT, and Central are available as built-ins. Their memberships can be
   edited, but their names and rows cannot be removed. Use **+ New ROI** to add
   a custom ROI.
5. Edit only the ROI name as text. If a loaded ROI contains labels not present
   on the BioSemi64 map, review those labels as separate occurrences on the
   right and remove an occurrence explicitly if desired. Duplicate occurrences
   remain distinct.
6. Use the outer **Cancel** to abandon the full draft, or outer **Save** to
   commit all ROI names and membership lists through the existing Settings
   workflow.
7. After a successful commit, cached Stats and SNR pages refresh and Ratio
   Calculator observes the same committed mapping through its existing polling
   path.

## Locked Compatibility Rules

- Preserve the existing app-level settings location and INI keys:
  `rois.montage`, `rois.names`, `rois.electrodes`, and montage-keyed custom
  presets. ROI settings do not move into `project.json`.
- Preserve saved ROI row order, display names, and electrode order. Mark only
  the last case-insensitive canonical LOT/ROT/Central occurrence as protected,
  matching last-wins consumers, and append only missing built-ins in catalog
  order. Long-form occipito-temporal names remain ordinary custom rows.
- Missing built-ins exist only in the Settings draft until outer Save. The
  initial harmonic signature must use raw persisted pairs so saving injected
  rows enters the established stale/recalculation path; Cancel remains a no-op.
- Give every draft row an opaque internal identity. Do not use the ROI name as
  identity because duplicate ROI names are valid legacy data.
- Use one independent `ROIElectrodeSelectionState` per row. Different ROIs may
  overlap, and a map toggle must never deduplicate or remove membership across
  rows.
- When a selection changes, retain surviving electrodes in their prior order
  and append newly selected canonical electrodes in deterministic BioSemi64
  order. Persist through the existing uppercase normalization contract.
- Preserve duplicate electrode occurrences within an ROI. The map shows one
  position for that ROI; counts remain tooltip/accessibility metadata rather
  than visible layout rows.
- Preserve every existing noncanonical/unmapped label, including repeated
  labels and original occurrence order, until that occurrence is explicitly
  removed or the user explicitly replaces/clears the ROI.
- **Clear Active ROI** must not silently discard retained unmapped labels. It
  requires a second activation after warning about affected labels, then
  reports the completed removal in the draft status.
- The map defines intended ROI membership. Do not disable nodes based on a
  participant's removed electrodes, current QC exclusions, or workbook
  coverage.
- Keep the FPVS LOT, ROT, and Central definitions exactly as stored in
  `Main_App.Shared.roi_presets`. SSSEP's Central membership differs and must
  not replace the FPVS definition.
- Protect each built-in's name and row from editing/removal while allowing map
  membership edits. An emptied built-in is partial and blocks Save.
- Keep dormant custom-preset settings unchanged. The ROI page neither displays
  nor rewrites them.
- Colors, swatches, overlap segments, active-row state, and internal row IDs
  are UI metadata only. `get_pairs()` must return only the current ordered
  `(name, electrodes)` contract.
- A wholly blank placeholder is valid and omitted from persistence. A partially
  defined ROI blocks outer Save, activates the row, and focuses the missing
  name or map input instead of silently dropping work.
  Do not introduce uniqueness rules for names or electrodes.
- No runtime dependency on the SSSEP repository. Retain the reviewed source
  attribution with the copied/adapted coordinate geometry.
- No `QThread` is needed. This is bounded, in-memory UI state; do not add file
  discovery, MNE construction, processing, or export work to the editor.
- Keep `src/Main_App/gui/main_window.py` unchanged unless implementation
  evidence proves unavoidable.
- Fit the supported 1280x900 workspace without a page-level scroll area or
  card-within-card layout. A focused ROI-list scroll area is allowed.

## Non-Goals

- Persisting ROI colors, user-selected palettes, internal row IDs, or overlap
  display metadata.
- Changing ROI means, participant weighting, condition/group/session behavior,
  missing-electrode handling, or harmonic-selection methods.
- Changing FPVS default ROIs or adding new scientifically endorsed presets.
- Adding arbitrary montage design, cap import, sensor-coordinate editing, or
  per-project ROI definitions.
- Adding a general free-text route for new noncanonical electrode labels. This
  follow-up preserves and explicitly removes existing legacy occurrences; it
  removes the prior comma-entry workflow.
- Moving or redesigning `SettingsManager` or the project manifest.
- Changing Plot Generator workers, workbook discovery, renderers, filenames,
  output folders, or figure formats.
- Changing SSSEP code.

## Implementation Plan

### Milestone 0 — First-Phase Baseline

Status: complete in commit `8d84b216`.

- Characterized the settings schema, ordered ROI round trip, duplicate and
  unmapped labels, outer Save/Cancel behavior, and cached SNR gap.
- Added the reusable BioSemi64 map, pure ordered selection state, row-scoped
  modal editor, focused tests, and cached-consumer refresh seam.
- Preserved the original text-row and Quick Add UI as required by the first
  plan revision. That presentation choice is now explicitly superseded.

### Milestone 1 — Embed the Multi-ROI Editor

Status: complete; locally safe verification recorded below.

1. Refactor `ROISettingsEditor` in place into a horizontal map/list editor and
   retain its current Settings-facing API.
2. Maintain one ordered row record with an opaque ID, draft name, independent
   `ROIElectrodeSelectionState`, and UI-only color assignment.
3. Extend `ElectrodeMapWidget` with an atomic presentation update for the
   active selection, aggregate memberships, active color, and accessible
   membership description.
4. Draw ordered segmented rings around electrodes with multiple ROI
   memberships. Keep the native checkable button and non-color active-selection
   cue.
5. Build a right-side list with active selection, swatches, one active-name
   field, retained legacy-label occurrences, and grouped clear/remove actions.
   Keep counts out of the visible layout while preserving them for accessible
   context. Preserve duplicate names and occurrences.
6. Remove the per-row selector action and retire the modal-only UI when no
   active caller remains.

Exit gate: selecting, naming, adding, removing, overlapping, and switching ROIs
works entirely in the embedded draft without schema or order changes.

### Milestone 2 — Built-ins and Settings Integration

Status: complete; locally safe verification recorded below.

1. Remove the Quick Add and preset controls; show a plain **BioSemi 64** label
   using the canonical `biosemi64` key after integration into the QC branch.
2. Materialize missing LOT, ROT, and Central rows from
   `default_roi_presets()` in the Settings draft only.
3. Preserve saved order and protect the last case-insensitive canonical
   occurrence from rename/removal. Keep membership editable and ordered.
4. Preserve dormant custom-preset data without reading or writing it from the
   page.
5. Preserve outer Settings Save/Cancel, harmonic dirty detection,
   recalculation, rollback, and page retirement.
6. Preserve `_refresh_roi_consumers()` and current worker-snapshot boundaries.

Exit gate: built-in protection, blank custom add, outer Cancel, outer Save, and
rollback retain the established behavior through the new page.

### Milestone 3 — Focused Tests and Documentation

Status: implementation complete. Local non-Qt results are recorded below; CI Qt
execution and visible cross-platform smoke remain pending.

1. Replace modal-centric Qt expectations with embedded-editor coverage.
2. Add pure tests for ordered row identity, duplicate names, overlap isolation,
   aggregate membership presentation data, UI-only colors, and occurrence-level
   unmapped removal.
3. Add registered CI Qt coverage for pointer and Space toggling, active-row
   switching, overlap rings, built-in protection, right-list behavior, layout,
   and accessibility.
4. Retain existing settings, processing, Stats, SNR, Ratio, and harmonic
   rollback regressions.
5. Update GUI architecture and user documentation to describe the embedded
   workflow.

Exit gate: locally safe gates pass, registered Qt coverage passes in CI, and the
visible 1280x900 workflow is accepted.

## Expected File Surface

Primary implementation:

- `src/Main_App/gui/roi_settings_editor.py` — embedded map/list coordination
  and Settings compatibility API.
- `src/Main_App/gui/roi_visual_editor_state.py` — GUI-neutral row identity,
  ordered collection behavior, pair projection, partial-draft validation, and
  UI-only color allocation.
- `src/Main_App/gui/roi_settings_widgets.py` — right-side controls, grouped
  actions, presentation colors, and keyboard-order helpers.
- `src/Main_App/gui/roi_electrode_selector.py` — reusable map rendering,
  overlap-ring presentation, and accessible electrode controls; retire
  modal-only composition when unused.
- `src/Main_App/gui/roi_electrode_selector_state.py` — BioSemi64 geometry,
  parser helpers, and the ordered per-ROI token ledger.
- `src/Main_App/gui/settings_panel.py` — flat ROI surface, Advanced-only
  project-root action, and unchanged Save/rollback/consumer-refresh
  orchestration.

Focused tests and docs:

- `tests/gui/test_roi_electrode_selector_state.py`
- `tests/gui/test_roi_electrode_selector_qt.py`
- `tests/gui/test_gui_preproc_dialog.py`
- existing ROI settings, processing, Plot Generator, Stats, and Ratio tests
- `docs/agent/architecture/gui.md`
- `docs/user/tools/snr-plot-generator.md`
- `docs/user/tools/statistics.md`
- `docs/user/tools/ratio-calculator.md`
- this active plan

## Acceptance Criteria

- The ROI tab opens directly to a nose-up map on the left and an ordered named
  ROI list on the right; no comma-list electrode editor, row-level selector
  button, separate selector modal, Quick Add card, preset toolbar, or enclosing
  ROI card remains in the normal workflow.
- The GUI labels the fixed geometry **BioSemi 64** while retaining the internal
  `biosemi64` persistence key; historical `10-10` values remain read aliases.
- All 64 `DEFAULT_ELECTRODE_NAMES_64` channels appear exactly once at the
  expected coordinates.
- Every node is pointer- and keyboard-operable and has an accessible name,
  tooltip/description, focus indication, and non-color active-selection cue.
- Selecting an ROI row changes only the active editing context. Clicking a map
  node changes membership only in that active ROI.
- Overlapping electrodes show one ordered color segment for every containing
  ROI, and their accessible description identifies every membership without
  relying on color alone.
- Duplicate ROI names remain independent through stable internal identities.
  Duplicate electrode and unmapped-label occurrences survive a no-op round
  trip.
- Existing noncanonical labels remain visible as distinct occurrences and are
  removed only through an explicit occurrence action or explicit ROI
  replacement/clear.
- Presentation colors and internal IDs never enter `get_pairs()`, the INI file,
  the harmonic signature, processing, or outputs.
- Distinct draft IDs do not cycle through the base palette, and every generated
  node fill keeps at least 4.5:1 contrast with its white electrode label.
- LOT, ROT, and Central are always present in the draft. Their names and rows
  are protected; their membership remains editable and must stay nonempty.
- Existing custom-preset configuration remains byte/logically unchanged by
  ordinary Settings saves even though preset controls are absent.
- Outer Settings Cancel leaves persisted settings unchanged. Outer Save uses
  the current schema and harmonic recalculation/rollback path.
- Cached SNR and Stats pages refresh after a committed change; Ratio Calculator
  sees the same mapping; active worker requests remain snapshots.
- No ROI calculation, workbook schema, output directory, filename, DPI,
  PNG/PDF pairing, participant weighting, or scientific default changes.
- The page fits and remains usable at 1280x900 on Windows; the shared
  implementation remains compatible with CachyOS.
- **Change Projects Root...** appears only in Advanced.

## Verification Plan

### Initial audits

```console
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
```

The path audit may report unrelated untracked files under `outputs/`. Do not
clean, edit, or treat those user files as part of this feature.

### Local safe gates

Run after the embedded follow-up is implemented:

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

Do not record these as passing until they have run against the follow-up. Do not
run pytest-qt or an offscreen Qt subprocess locally unless the user explicitly
approves a safe visible environment.

### Registered CI Qt coverage

The follow-up coverage must verify:

- pointer and Space-key toggling for the active ROI;
- active-row selection and duplicate-name isolation;
- overlap segments and accessible multi-membership descriptions;
- color/ID exclusion from persistence;
- exact no-op ordering and legacy duplicate preservation;
- occurrence-level noncanonical-label removal;
- blank custom add, protected built-in removal/rename guards, and remove
  fallback;
- outer Settings Save/Cancel/reopen and rollback;
- cached SNR-page refresh; and
- usable geometry at the supported workspace size.

### Visible manual smoke

1. Launch FPVS Toolbox normally on Windows 11 at 1280x900.
2. Open **Settings > ROIs** and confirm the embedded map/list layout fits
   without a page scrollbar or clipping.
3. Switch among LOT, ROT, and Central. Toggle nodes with pointer and Space and
   confirm only the active ROI changes.
4. Put one electrode in multiple ROIs and confirm every ring segment, legend
   color, tooltip membership, and active non-color cue remains understandable.
5. Exercise blank add, name editing, duplicate names, protected built-in rows,
   custom remove, and removal of one repeated legacy-label occurrence.
6. Cancel Settings and reopen it; confirm no draft persisted.
7. Save a no-op and confirm there is no false harmonic recalculation prompt.
   Save a real edit in a processed project and exercise existing
   recalculate/decline/rollback behavior.
8. Confirm cached SNR and Stats pages and Ratio Calculator show the committed
   mapping in the same app session.
9. Generate one `(All ROIs)` SNR run from representative data and confirm the
   existing names, folder, and matching PNG/PDF outputs.
10. Repeat the layout/accessibility smoke on CachyOS when available; otherwise
    record that remaining platform risk.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Duplicate names target the wrong ROI | Use an opaque row identity everywhere inside the draft; names remain editable display/storage values only. |
| A node toggle removes membership from another ROI | Give every row an independent selection state and route map changes only to the active row. |
| Overlap is hidden by one fill color | Draw ordered segmented membership rings and list all memberships in tooltip/accessibility text. |
| Colors accidentally become data | Keep color allocation in the GUI presentation model and assert that pairs, INI, signature, and processing payloads contain no color or row ID. |
| Visual round trip reorders electrodes | Retain the existing ordered token ledger; append only newly selected map nodes in canonical order. |
| Legacy labels disappear without a text field | Render each configured occurrence explicitly and require an occurrence-level remove or explicit replace/clear action. |
| Clearing silently drops legacy entries | Require a second activation when a clear would remove retained unmapped occurrences. |
| Missing defaults silently change scientific inputs | Inject them only into the draft; compare against raw persisted pairs and commit through the normal recalculation/rollback path. |
| Page becomes too dense | Use one flat split surface, grouped actions, names-only rows, a one-row ROI footer, and scrolling only within the ROI list. Paint membership arcs inside disjoint native node bounds. |
| Scope expands into scientific/output code | Treat worker, aggregation, renderer, schema, filename, or default-membership edits as stop-and-review events. |

Rollback remains schema-free: reverting the current refinement to `4f46b4bc`
restores the first embedded layout without migrating or rewriting saved ROI
data.

## Progress

First implementation:

- [x] Persistence, preset, consumer, and output backbones characterized.
- [x] Attributed BioSemi64 map and ordered selection state implemented.
- [x] Row-modal integration and cached Stats/SNR refresh committed in
      `8d84b216`.
- [x] First-implementation documentation, local safe gates, and independent
      review completed as recorded below.

Embedded visual-first follow-up:

- [x] Product direction and compatibility constraints recorded.
- [x] Embedded map-left/list-right ROI editor implemented.
- [x] Color-coded ROI rows and overlap-ring presentation implemented.
- [x] Name-only text editing and occurrence-preserving legacy-label controls
      implemented.
- [x] Preset controls removed; dormant preset data remains compatible.
- [x] LOT, ROT, and Central are protected built-in draft rows.
- [x] BioSemi 64 labeling, enlarged map targets, and flat ROI layout implemented.
- [x] Project-root action confined to Advanced.
- [x] Partial drafts block Save instead of being silently omitted.
- [x] Follow-up local safe gates completed and recorded.
- [x] Follow-up registered CI Qt coverage authored and registered.
- [ ] Follow-up registered CI Qt coverage executed.
- [ ] Visible installed-application smoke completed.

## Historical Receipt — First Implementation (`8d84b216`)

The following results apply to the first row-modal implementation only; they
must not be represented as verification of the embedded follow-up:

- GUI focused gate: passed; 8 selector-state tests passed.
- Processing focused gate: 375 passed, 1 skipped.
- Stats focused gate: 384 passed.
- Direct project-I/O, Plot Generator, and Ratio Calculator safe bundles: 121,
  110, and 7 tests passed respectively.
- ROI/state/settings focused bundle: 15 passed.
- Verification registry validation, changed-file Ruff/compilation, strict
  MkDocs build, protected/source-localization audits, and `git diff --check`
  passed.
- Full locally safe suite: 1,930 passed and 3 skipped; one unrelated
  Publication Maps layout assertion failed by 0.190 pixels and reproduced in
  isolation. No Publication Maps source or test was changed.
- Several drivers were blocked by eight pre-existing machine-path findings in
  the untracked `outputs/` tree; those user files were left untouched.
- Registered pytest-qt coverage was not run locally under repository policy.

## Historical Receipt — Embedded Visual-First Commit (`4f46b4bc`)

The following results apply to the embedded surface through `4f46b4bc`, before
the flat/protected-built-in refinement:

- `.venv\Scripts\python.exe .agents/scripts/verify.py --scope gui --tier
  focused` passed the GUI audit, changed-file Ruff, compilation, and 13
  GUI-neutral selector/collection tests.
- Verification configuration passed for all 15 scopes. Both changed Qt files
  remain registered in `tests/qt_test_files.txt`.
- Direct locally safe bundles passed: project I/O/settings, 159; processing,
  375 with 1 skip; Plot Generator, 110; Stats, 384; Ratio Calculator, 7; and
  the combined ROI state/settings bundle, 18.
- The exact-tree non-Qt suite completed with 1,935 passed and 3 skipped. Its
  only failure was the pre-existing Publication Maps repeated-layout assertion
  whose left text edge is `-0.190014` pixels; the same unrelated failure was
  present before this follow-up, and no Publication Maps file was changed.
- The repository precommit driver stopped before its static/test stages on the
  same eight pre-existing hard-coded machine paths under the untracked
  `outputs/` tree. Those user files were not edited or staged; the equivalent
  changed-file static checks and full locally safe pytest run were executed
  directly.
- Strict MkDocs, protected/source-localization audits, Stats audits,
  `git diff --check`, and three independent final reviews passed.
- Registered pytest-qt coverage was not executed locally under repository
  policy. It defines the embedded pointer/keyboard workflow, stable duplicate
  rows, overlap presentation, destructive confirmations, Save/Cancel behavior,
  disjoint minimum-size hit targets, and worst-case 1280x900 shell containment.
- The visible Windows 11/DPI/theme smoke and CachyOS smoke remain pending. The
  manual path above is the residual visual acceptance gate.
- Unrelated working-tree changes in the execution-plan index/future plans and
  `outputs/` remain outside this feature and are intentionally excluded from
  the follow-up commit.

## Final Refinement Verification Receipt

The flat/protected-built-in refinement is complete on
`codex/sssep-roi-selector`.

- `.venv\Scripts\python.exe .agents/scripts/verify.py --scope gui --tier
  focused` passed the GUI audit, changed-file Ruff, compilation, and all 16
  GUI-neutral selector/collection tests.
- Direct locally safe bundles passed: project I/O/settings, 123; processing,
  375 with 1 skip; Plot Generator, 110; Stats, 384; Ratio Calculator, 7; and a
  focused ROI settings/downstream bundle, 25.
- The exact-tree non-Qt suite completed with 1,940 passed and 3 skipped. Its
  only failure is the unchanged Publication Maps repeated-layout assertion
  whose left text edge is `-0.190014` pixels. No Publication Maps source or
  test changed in this work.
- Strict MkDocs, protected/source-localization and Stats audits, changed-file
  Ruff/compilation, and `git diff --check` passed.
- Project-I/O, Plot Generator, Ratio Calculator, and repository drivers stop at
  the same eight pre-existing hard-coded machine paths under the untracked
  `outputs/` tree. Those user files were not edited or staged; their registered
  test bundles were run directly.
- Registered pytest-qt coverage was updated but not executed locally under
  repository policy. It defines the flat surface, BioSemi 64 label, protected
  built-ins, pointer/keyboard membership editing, tab traversal, grouped
  actions, enlarged disjoint hit targets, Save/Cancel behavior, raw-vs-draft
  harmonic signatures, and dormant-preset preservation.
- The visible Windows 11/DPI/theme smoke and CachyOS smoke remain pending. The
  manual path above is the residual visual acceptance gate.
- Unrelated working-tree changes in the execution-plan index/future plans and
  `outputs/` remain outside this feature and will be excluded from the commit.


## QC Branch Integration (2026-09-07)

Merged ROI-selector history through `525ad6fa` into the QC scientific protocol
branch, based on `6b0e8e55`. Both histories are retained in the merge.

Conflict resolutions retain the current protocol editor, Experimental QC tabs,
Dataset Exclusions manager, settings worker ownership, and the BioSemi64 /
anatomical-label persistence safeguards. The visual map uses the current
`biosemi64` key and displays BioSemi 64; no electrode mapping, default ROI
membership, statistical algorithm, or existing project setting is migrated.
The old `10-10` key remains a SettingsManager read-compatibility input only.

Both initial ROI-dependent signatures now use persisted pairs before the
editor injects missing defaults. A saved draft addition therefore triggers the
current frequency-QC rebuild route, while complete defaults and no-op edits do
not. New non-Qt integration tests exercise actual settings persistence, editor
collection state, constructor baseline assignments, and recalculation routing.

The incoming page retirement also required a lifetime fix: harmonic success
accepts only after both Settings workers release, including the fallback when
shared progress presentation is unavailable. Result/error handlers can process
thread-finished events inside modal loops; the UI bridge now defers release
and its own retirement until those handlers return. New non-Qt and registered
CI-only cases cover ordinary and nested completion, failure, and cleanup.

Verification on the merged working tree:

- `.venv/Scripts/python.exe .agents/scripts/verify.py --scope processing --tier focused`:
  1,511 passed, 5 skipped; existing synthetic-signal warnings only.
- The same driver with `--scope gui`: 284 non-Qt tests passed; GUI audit,
  changed-file Ruff, and compilation passed.
- The same driver with `--scope stats`: 430 tests passed; Stats audits passed.
- Project-I/O, Plot Generator, and Ratio Calculator focused drivers stop at
  eight existing machine-path findings in unrelated untracked `outputs/`.
  Their registered non-Qt test targets were run directly together: 351 passed.
- `--scope repo --tier precommit` stops at those same eight path findings.
  The unrelated output files are excluded from the merge.
- Independent conflict/lifetime review passed. No local Qt workflow ran.

Additional integration coverage: `tests/gui/test_roi_settings_invalidation.py`
(15 tests total) and `tests/gui/test_settings_worker_lifetime_static.py`
(12 tests, registered in the GUI focused scope). The retained
`tests/gui/test_gui_preproc_dialog.py` and incoming
`tests/gui/test_roi_electrode_selector_qt.py` remain registered for CI;
the former now covers both normal and nested harmonic-worker completion with
no shared progress page. Plot Generator and Ratio Calculator GUI refresh
coverage remains registered for CI as before.

Visible smoke remains required: at 1280x900 open Settings > ROIs, edit one
ROI with pointer/Space, inspect overlap rings, and Cancel/reopen. Save an edit,
verify cached Stats/SNR/Ratio consumers refresh, and confirm Advanced still
opens Dataset Exclusions. In a processed project, exercise ROI changes with
rebuild-now and deferred rebuild, including a missing built-in draft. Finish a
harmonic-only rebuild and confirm Settings returns home after worker cleanup.
The existing detailed Windows/CachyOS visual checklist above still applies.

Final handoff checks: all staged Python files pass Ruff and compilation;
`git diff --cached --check` passes. The strict MkDocs build command
`.venv/Scripts/python.exe -m mkdocs build --strict --site-dir .codex-tmp/roi-merge-docs`
is blocked by two pre-existing pages absent from navigation:
`reference/missing-condition-outputs.md` and `reference/spectral-data-files.md`.
Both pages already exist at the pre-merge HEAD, and `mkdocs.yml` is unchanged.
No publishing or project-data mutation was performed during validation.
