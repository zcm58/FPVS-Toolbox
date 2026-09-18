The Publication_Maps directory owns the embedded **Scalp Maps** tool. The
current implementation renders condition-level grand-average BCA, SNR, and
z-score scalp maps using the significant-harmonic list saved at processing
completion.

Scalp Maps is an embedded beta tool. Expose it only through the Main App's
central `BETA_TOOL_SPECS` registry so the shared visibility gate and
once-per-session beta acknowledgement apply automatically.

Rules:

- Included harmonics must come from the cache-only
  `Tools.Stats.analysis.canonical_harmonics.load_project_processing_harmonics`
  API. Scalp Maps must never calculate, substitute, or silently refresh the
  processing-time list. Missing or stale metadata is a hard, user-actionable
  reprocess/recalculate error.
- Processed-workbook discovery and participant/group identity must come from
  `Main_App.projects.dataset_index`. Do not scan condition folders recursively,
  infer participant IDs from filenames, or infer groups from output folders.
- Resolve exactly one canonical `group_id` before participant aggregation. An
  all-groups GUI action must run each canonical group separately and publish to
  that group's validated output folder; it must never pool groups implicitly.
- An exactly-two-group comparison is the narrow exception to separate figure
  publication, not to separate aggregation: build each canonical group result
  independently, then display one selected condition side by side with shared
  per-metric color limits. Never pool the groups, calculate a difference map,
  or describe the comparison figure as a statistical test. Comparison mode is
  mutually exclusive with paired-condition mode and publishes only the
  combined PNG/PDF figure pair at the selected base output root.
- Repeated-session projects require an explicit dimension. Condition mode
  filters the canonical workbook cohort to one session. Session comparison
  accepts one or more conditions, exactly two canonical groups, and two
  distinct canonical sessions, then renders each condition independently as
  group columns × session rows with one shared per-metric scale per condition.
- Build repeated-session panels from exact canonical workbook paths and
  `recording_id`/`session_id`/`group_id`/`visit_index` metadata. Never infer a
  visit or phase from a path. Calculate optional comparison-minus-reference
  values within participant before averaging, use a shared diverging scale,
  and retain participant `n` and paired `n` in the panel data for validation.
  Do not display visit indices, participant `n`, or paired `n` in figure
  artwork.
- Do not add legacy fixed-order warnings to repeated-session GUI, help text,
  session state, figure artwork, or bottom footers.
- Apply the shared participant, participant-condition, and frequency-domain
  exclusions before aggregation. Preserve dataset-index duplicate preference
  and diagnostics, and reject empty, unassigned, or ambiguous requested
  cohorts.
- Managed inputs must omit exact workbook paths explicitly marked excluded
  in the current final QC coverage before source validation or reading. A
  retained source-evidence record does not override that exclusion. Preserve
  the participant's other released visits and conditions, audit omitted
  workbook identities, and still reject any other unreleased input.
- Repeated-session grid validation must apply request participant exclusions
  and the completed results' matching frozen QC participant and workbook
  exclusions to its canonical workbook records before checking coverage. Do not reintroduce
  excluded recordings when joining panel values, infer exclusions from absent
  value rows, or reload live QC during panel assembly. An empty requested
  condition × group × session cell or missing values for a non-excluded
  canonical recording remains an error.
- BCA summation and SNR averaging must use the exact selected `"{freq:.4f}_Hz"`
  columns, matching Stats behavior. Do not add nearest-column fallback.
- Compact BCA/SNR/Z values use the shared companion-aware selected-column
  reader; old Excel-only workbooks remain readable. Both declared condition
  and spectral NumPy companions are part of source identity and must validate
  during capture and publication; missing or tampered companions cannot
  silently pass the source checks.
  Native `.fpvs` source declarations use these same readers and companion
  checks; they must not bypass validation because they are not ZIP archives.
- Z-score maps read the `Z Score` sheet, use the exact selected
  `"{freq:.4f}_Hz"` columns, and combine selected harmonics as
  `sum(z) / sqrt(K)` before the condition grand average.
- Keep workbook reading, metric aggregation, and rendering
  in GUI-free modules. `gui.py` may gather settings and launch workers, but
  workers must not touch widgets.
- Preserve signed BCA values through aggregation. Rendered BCA values may clip
  negative values to the low color.
- An unreadable active workbook, missing requested sheet, missing Electrode
  column, or missing exact selected harmonic column is fatal for the requested
  output. Do not publish a silently reduced participant cohort.
- Missing or non-finite montage sensors are missing data. Never replace them
  with numerical zero. Render only finite defined sensors, require the
  documented minimum non-collinear coverage, and exclude missing sensors from
  interpolation and color scaling.
- The active Scalp Maps GUI/worker publishes figure files only. Do not create
  XLSX, CSV, JSON, or other auxiliary output artifacts. Grouped figures must
  not overwrite one another.
- Generation is cooperative and transactional. Cancellation must be checked
  through discovery, reading, aggregation, and rendering; it must produce a
  distinct cancelled outcome and must not publish a partial figure set or a
  normal completion result. Keep the worker/thread and host navigation locked
  until the worker actually returns.
- Visible ordinary figure titles should be condition names only. In two-group comparison
  mode, the selected condition is the overall title and canonical group labels
  are the two column headers. Do not add selected harmonics, subject counts, or
  cache/source provenance to visible figure titles. Repeated-session grids have
  no overall or per-map title. Show canonical session identity once per row in
  the external left label rail, including comparison minus reference for the
  optional difference row. Do not show visit indices or sample sizes.
- Figure geometry belongs to separate renderer-internal layout profiles for
  ordinary single-map, paired-condition, ordinary two-group comparison, and
  repeated-session figures. Their geometry must remain independently editable;
  shared drawing and typography primitives may remain shared. These profiles
  are developer contracts, not user-facing GUI settings, and must not add
  project settings or persistence.
- Single-condition and paired-condition figures should fit a standard US letter
  journal text width: 8.5-inch page minus 1-inch margins = 6.5 inches.
- Repeated-session grids use a compact four-column matrix: external left row
  labels, the two canonical group map columns, and external right colorbars.
  Two-session figures use four GridSpec rows and are 5.8×4.2 inches; enabling
  the opt-in difference row uses six GridSpec rows and 5.8×5.9 inches; its GUI
  checkbox starts unchecked. Do not use tight-bounding-box cropping or an
  explanatory footer. Prefix the measured-width wrapped canonical group
  headers with `(A)` and `(B)`. Box only the two-column map matrix with a thin
  neutral outer frame, retain the divider in the group-column gap, and span
  each row gutter with a horizontal divider. Keep headers and row labels
  outside that frame, keep colorbars to its right, and keep all content
  unclipped and non-overlapping. Center the visible topomap data/head bounds
  vertically in each cell while preserving the renderer's existing y span.
- Paired-condition figures are selected explicitly in the GUI with Condition A
  and Condition B combo boxes populated from the checked condition list.
- Two-group comparison figures are available only when the managed project has
  exactly two canonical groups, **All groups** is selected, and exactly one
  condition is checked. The two canonical group labels are the figure columns.
- When BCA and SNR are selected, paired-condition export should render one
  combined figure: BCA on the first row, SNR on the second row, and, when
  selected, Z Score on the third row, with condition titles only above the first
  row.
- Paired-condition export is paired-only and is the GUI default: when it is
  enabled, render only the combined paired `.png` and `.pdf`, not individual
  condition figures.
- Two-group comparison export is likewise comparison-only: render only the
  combined comparison `.png` and `.pdf`, not the ordinary per-group artifact
  sets for that run.
- Default project input is the active project's Excel root. Default output is
  the selected folder, initially `<results root>/4 - Scalp Maps`.
- Keep the embedded page within the supported 1280×900 workspace without a
  page-level scroll area. Use flat purpose tabs for generation and advanced
  settings; do not nest `SectionCard` surfaces. **Generate Maps** must contain
  condition/session selection, map types, a compact flat map-appearance/range
  subsection, the tool-info action, progress, the generation action, and inline
  status. In repeated-session mode, do not show a redundant valid-ready summary;
  keep validation, running, cancellation, and completion status visible. Do not
  show instructional text pointing to **Advanced Settings**. Keep Generate,
  Cancel, and progress at one control height. **Advanced Settings** owns the
  infrequently used full-width input-data controls, output/history controls,
  and optional combined-figure configuration without a separate two-group
  eligibility paragraph. Preserve the active-project input root, selected
  output root, group-specific routing, and folder-action semantics while moving
  controls.
- Derive project/workflow-specific presentation through the GUI-neutral
  `ui_profile.py` resolver and apply it in one page method. Build Scalp Maps
  widgets once; do not introduce separate single-group, multi-group, or
  repeated-project page classes. Visibility represents workflow capability,
  while existing enabled states continue to represent transient selection
  eligibility. Use one static flat tab hierarchy for every mode: Session
  comparison hides Figure layout, while Condition workflows retain it, showing
  paired-condition controls generally and the two-group option only for exactly
  two canonical groups. Map appearance never moves between tabs or modes.
- Keep generation history out of the embedded page in a focused **View
  Generation Log** modal. Closing or hiding the modal must not clear its live
  history or stop updates; reopening it during or after a run must show the
  complete accumulated history for the current or most recent run. Starting a
  new run may clear that prior run history, matching the existing workflow.
- BCA color endpoints are user-selectable. The fixed BCA range is optional:
  it starts unchecked so BCA maps auto-scale. Enabling it explicitly uses the
  editable `0.0` to `0.4 BCA` values by default.
- SNR uses the same color endpoints. The fixed SNR range is optional: it starts
  checked with a `1.0` to `1.5 SNR` range; unchecked maps auto-scale.
- Shared BCA/SNR scalp-map color stops live in
  `src/Tools/Publication_Maps/colormaps.py`; edit the shared ramp there instead
  of introducing metric-specific copies in Scalp Maps renderers.
- The BCA colorbar label is `Baseline-corrected amplitude (µV)`. Figure fonts
  should use `Main_App.exports.figure_style`, not GUI typography roles or
  one-off Matplotlib defaults.
- The SNR colorbar label is `Signal to Noise Ratio`.
- Z-score maps render values below the configurable z threshold as white. The
  default threshold is `1.64`, and the upper z color limit is always automatic
  from the maximum z-score across the rendered z-score map pair.
- Do not run offscreen Qt workflows locally.

Focused local verification:

```console
python .agents/scripts/verify.py --scope figures --tier focused
python .agents/scripts/verify.py --scope publication-maps --tier focused
```

Add the `stats` scope only when a change touches the shared processing-time
harmonic or numerical contract. Qt execution remains CI-only by default.

Visible exclusion smoke: generate ordinary and repeated-session maps after
accepted participant, recording, and condition exclusions. Check the generation
log lists omitted workbooks, other valid visits and conditions still contribute,
and a wholly empty requested group/session/condition produces a clear error.
