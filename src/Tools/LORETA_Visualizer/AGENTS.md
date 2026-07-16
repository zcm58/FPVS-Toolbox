# LORETA Visualizer Agent Rules

## Start Here

This directory owns the embedded LORETA 3D visualizer, its prepared-payload
contract, and its source producers. Run the focused gate before broad reading:

```powershell
python .agents/scripts/verify.py --scope loreta --tier focused
```

The driver selects `.venv1` or `.venv` and does not run Qt tests locally. Read
`ARCHITECTURE.md` for the current module inventory, data flow, and output
schemas. Do not consult retired Source Localization code for additional context.

Implementation should remain inside `src/Tools/LORETA_Visualizer/`. The only
normal integration edits outside it are the Main App page factory, sidebar,
icon, cached-page cleanup, focused tests, and agent/user documentation. The
active Hauk source-PSD plan additionally permits one GUI-neutral Main App
time-domain derivative writer plus narrow process-runner, processing-ledger,
and post-processing-worker integration. Source estimation must still remain in
this tool's `source_producers/`; do not spread it into Main App, Stats,
preprocessing, project I/O, diagnostics, or unrelated tool packages.

## Hard Boundary

- This is a new visualization branch, not a continuation of retired Source
  Localization/eLORETA. Do not import, inspect, or copy from
  `Tools.SourceLocalization` or an optional `src/quarantine/**` tree.
- Never recreate `src/Tools/SourceLocalization/**`,
  `src/Main_App/Legacy_App/**`, or `src/Main_App/PySide6_App/**`.
- Rendering, anatomical loading, payload adaptation, and numerical source
  estimation are separate responsibilities. The GUI, renderer, importer,
  fsaverage helpers, and display bridges must never compute inverse solutions,
  frequency statistics, source estimates, condition effects, cluster tests, or
  anatomical ROI statistics.
- Numerical methods live only in `source_producers/` and emit validated prepared
  payload/manifest JSON. New methods are sibling producers behind that shared
  contract; they are not renderer modes.
- Do not change preprocessing order, Stats methods, BDF loading, project
  manifests, exports, diagnostics, or app-wide project I/O for visualizer work.
- Update this architecture guidance and any matching active execution plan
  before adding a new numerical method, source input path, project integration,
  or interaction model. Create an active plan first when that work is a
  non-trivial refactor or feature slice and no matching plan exists.

## Retained Beta Method Contracts

- `l2_mne_hauk_source_psd_cortical_normal_v1` is the default time-domain-first
  L2-MNE beta producer. It consumes signed, repetition-averaged EEG Raw FIF
  derivatives and calls MNE source PSD with `pick_ori="normal"` so the cortical
  surface-normal component is selected before power-to-amplitude conversion,
  harmonic aggregation, and participant-first z scoring. This orientation
  estimator matches the Hauk source-spectrum approach more closely than the
  historical pooled-orientation implementation, without claiming exact study
  reproduction.
- `l2_mne_hauk_source_psd_v1` is retained as the explicit legacy L2-MNE mode.
  The Source Map Options GUI may select it for a rebuild to reproduce older
  maps that used MNE's pooled free-orientation source-PSD output. The two modes
  keep distinct method identities, provenance, and cache entries.
- `eloreta_volume_hauk_source_psd_vector_norm_v1` is the current time-domain
  eLORETA sibling. It consumes the same signed FIF derivatives, complete-case
  cohort, saved oddball harmonics, exact FFT-bin plan, and neighboring-bin
  z-score algorithm, but forms complex periodic-Hann coefficients only at the
  exact required bins, calls MNE `apply_inverse(..., pick_ori="vector")`, and
  reduces each three-component source coefficient as
  `sqrt(sum(abs(Cxyz)^2))`. It must compute and cache its own participant source
  amplitudes and z-score arrays. Never reuse L2-MNE source arrays or the
  cortical cluster mask as eLORETA values. The historical
  `eloreta_volume_hauk_source_psd_v1` identity remains readable as a
  legacy, orientation-basis-dependent result and must not be relabeled as the
  corrected vector-norm method.
- The source-PSD methods intentionally support EEG with the MNE `fsaverage`
  template and Toolbox BioSemi64 geometry. MEG, individual MRI,
  participant-specific coregistration, and mixed-modality fusion are out of
  scope rather than missing fallbacks.
- Time-domain L2-MNE and eLORETA consume committed FIF derivatives directly.
  They must not read `FullFFT Amplitude (uV)`, require the Stats-ready workbook,
  or silently fall back to either amplitude-workbook source producer.
- Exact project-selected oddball harmonic bins remain authoritative. Nearest-bin
  substitution is forbidden. The intentional Toolbox noise rule uses offsets
  `-10..-2` and `+2..+10`, drops one minimum and one maximum finite amplitude
  per source, and uses population SD. This nine-candidate-bins-per-side rule is
  a documented Toolbox adaptation where it differs from interpretations of the
  Hauk reference implementation.
- Source-ready time-domain derivatives are durable generated project outputs
  under `6 - Source Localization/Source-Ready Time Domain v1/`. They are EEG
  only, signed volts, exact-length, and average repetitions before any FFT.
  Main App serialization must not compute inverse solutions or source metrics.
  Existing valid signed FIF/JSON derivatives can be reused when changing the
  L2 orientation mode or rebuilding corrected eLORETA maps; reprocessing the
  sensor data is not required merely to regenerate source maps.
- Source-PSD project orchestration uses the versioned
  `complete_case_all_canonical_conditions_v1` eligibility policy. A completed
  participant with any missing canonical condition or an explicitly incomplete
  derivative is omitted from every source condition and recorded as
  source-ineligible in the prepared manifest, participant sidecar, validation
  report, logs, and GUI status. Do not add these source-only omissions to the
  general participant exclusion workbook. Retained derivatives remain strict;
  corruption or incompatibility declared complete is still a hard failure.
- The beta L2-MNE cortical-surface producer remains swappable and explicitly
  method-labeled (for example `l2_mne_cortical_surface_beta`). Project export
  reads existing flat or condition/group topography workbooks, uses the external
  MNE/fsaverage BioSemi64 template forward model, and writes project-local
  prepared payloads.
- The amplitude-workbook Hauk-style L2-MNE z-score export remains readable as a
  legacy/exploratory beta and method-labeled (for example
  `l2_mne_cortical_surface_hauk_zscore_beta`) with
  `source_value_unit: z-score`. It must use raw `FullFFT Amplitude (uV)` target
  and neighboring-bin topographies, apply the same inverse model to target and
  noise bins, and fail clearly when required bins are absent. Never derive
  source z-scores from Summed BCA or compact selected-harmonic summaries.
- The L2-MNE Hauk estimator remains MNE-native with `method="MNE"`, `loose=0.2`,
  `depth=None`, `fixed=False`, no dSPM/sLORETA/eLORETA normalization, and
  `lambda2 = 1 / 9`.
- Participant-first Hauk z-scores are the default: preserve each included
  participant's target/noise topographies, estimate and z-score each
  participant independently, then aggregate group raw mean, median, and 20%
  trimmed mean payloads. The participant sidecar is retained for future
  individual viewing. The older group-first model is a deprecated advanced
  fallback only and stays out of normal Source Map Options.
- `Flagged Participants.xlsx` exclusions apply by default. Source Map Options
  may explicitly include flagged participants for comparison and pass that
  choice to the producer; the modal must not calculate source values.
- Participant-first cluster-permutation masks are computed only in
  `source_producers/`, stored in payload metadata, and are the primary
  publication display mask. The renderer may obey saved mask indices but never
  calculate t statistics, sign flips, clusters, or p-values.
- Source lateralization remains a descriptive producer-side companion derived
  from already-computed participant/group maps. It writes CSV/JSON right-minus-
  left and lateralization-index rows, including whole-hemisphere summaries and
  a primary `desikan_killiany_temporal_hauk` ROI from combined inferior,
  middle, and superior temporal labels per hemisphere. Producers preserve
  fsaverage vertex IDs/hemisphere labels and read fsaverage `aparc` labels;
  renderer/display coordinates never define anatomical ROIs. Coordinate-defined
  LOT/ROT rows remain transparent QC/fallback output. This never replaces
  sensor-space BCA lateralization statistics.
- Project Hauk exports retain `source_validation_report.json` and
  `source_validation_report.md`. The report summarizes already-written
  manifests, payloads, participant sidecars, and lateralization files; it must
  not recalculate sources, masks, statistics, or renderer-derived facts.
- The amplitude-workbook eLORETA volume branch remains importable as a
  legacy/exploratory beta. It uses the participant-first FullFFT z-score
  contract and writes `volume_points` under
  `6 - Source Localization/eLORETA Volume Beta/`; it is not a fallback for the
  time-domain method and must retain its legacy method identity.
- The time-domain eLORETA producer writes independently calculated
  `volume_points` under
  `6 - Source Localization/eLORETA Hauk Source PSD Beta/` with method identity
  `eloreta_volume_hauk_source_psd_vector_norm_v1`. The older
  `eloreta_volume_hauk_source_psd_v1` method identity is historical and
  orientation-basis-dependent.
- Volume cluster masks are recomputed in volume source space with method-neutral
  `cluster_mask_source_indices`. Never reuse or mutate the L2 cortical mask.
- When a project has no current source-PSD manifest, the normal background
  rebuild generates both the time-domain L2-MNE and eLORETA methods. If one
  current method already exists, the GUI loads that valid partial result rather
  than automatically rebuilding solely because its sibling is absent. Normal
  manual and post-processing rebuilds still target both methods. Existing
  amplitude-derived L2-MNE/eLORETA manifests remain viewable with explicit
  legacy/exploratory labeling. Source Map Options exposes one normal rebuild
  action plus the L2 cortical-orientation choice; it does not expose eLORETA
  vector pooling as a display or numerical choice. The GUI may switch loaded
  manifests for display; source estimation stays producer-owned, and rendering
  remains calculation-agnostic.

## Retained Display And Fallback Behavior

- Opaque cortical paint is display-only. It may interpolate prepared cortical
  values onto the higher-resolution pial mesh and apply saved masks or a
  user-selected cutoff; it must not alter source values.
- The split-hemisphere publication view remains the default cortical display.
  Use topology-matched inflated meshes when available and pial split surfaces
  otherwise. Project the same prepared pial/source values, allow independent
  hemisphere rotation, restore the publication layout on Reset, and permit
  `curv`/`sulc` gray-white underlays. This is not a new statistical mask.
- Prepared z-score JSON keeps signed values. Saved cortical masks show masked
  activation over gray cortex. Disabling a mask is exploratory and affects only
  display/export. With no saved mask, the manual cutoff is the exploratory
  fallback. Empty exact small-sample masks warn that the mask cannot be
  resolved; adequately powered empty Hauk masks warn that no vertices survived.
  Neither case changes saved values or computes renderer statistics.
- Non-surface z-score display may use saved
  `cluster_mask_source_indices`; positive-only filtering is allowed only when
  the mask is disabled or unavailable.
- Transparent volume display uses a display-smoothed grid/contour clipped to the
  current brain surface, not source-point glyphs. Clipping and interpolation do
  not change saved payload values or statistics.
- eLORETA volume payloads may also render on orthogonal fsaverage MRI slices.
  Slice rendering is display/export-only, uses prepared points, and standardizes
  anatomy planes across the loaded conditions for the current
  method/summary/mask state. It must keep the same mask/exploratory filtering as
  volume display, crop to anatomy bounds, use comparable Gaussian-neighbor
  smoothing, and surface visible errors when anatomy, template generation, or
  the all-condition reference is unavailable.
- Transparent mesh modes use plain alpha blending. Do not re-enable VTK depth
  peeling without visible validation on supported Windows/VTK driver stacks;
  depth peeling has made translucent meshes disappear on a supported machine.
- Missing PyVista/VTK/MNE/fsaverage must produce inline status and the retained
  synthetic fallback instead of crashing the Main App. Synthetic conditions,
  dummy activation, fixtures, and examples remain deterministic, local,
  clearly labeled, and unavailable as normal live-data selector choices.

## Ownership Rules

- `gui.py` owns the embedded PySide6 page, controls, worker wiring, and status.
  `method_info.py` owns explanatory copy and links only.
- `renderer.py` owns actors, camera, opacity, mesh/paint/volume/split display,
  and explicitly disabled depth peeling. It owns no source math.
- `fsaverage_mesh.py` locates, reads, decimates, and transforms anatomical
  meshes. Combined meshes stay pial; inflated meshes and curvature underlays are
  split-view canvases only.
- `source_payloads.py`, `transforms.py`, `scalar_fields.py`,
  `cortical_paint.py`, `volume_overlay.py`, and `volume_slices.py` may validate,
  transform, normalize, filter, interpolate, and color already-computed values
  for display. They must not calculate source or inferential results.
- `prepared_payload_importer.py` validates controlled prepared JSON and adapts
  it for display. It must not discover project outputs. Its bounded cache is
  keyed by path, mtime/size, and transform signature and must not leak caller
  metadata mutations.
- `prepared_payload_validator.py` owns format/schema constants and cross-field
  rules; it must not render, inspect projects, or calculate sources. Keep small
  checked-in synthetic examples and JSON Schemas aligned without implying that
  the renderer owns source math.
- `source_producers/` owns calculation, project input adapters, source-space
  statistics, anatomical label mapping, lateralization, and validation-report
  assembly. Producers must not import `gui.py`, `renderer.py`,
  `fsaverage_mesh.py`, `prepared_payload_importer.py`, `source_payloads.py`,
  `transforms.py`, or `scalar_fields.py`.
- Project input adapters are read-only. They may read existing workbooks and QC
  summaries but must not update Stats metadata, alter workbooks/exclusions, or
  use local real-project paths in tests.

## Cache And Project I/O

- Preserve the untracked repository-root `.fpvs_cache/`. Automatic fsaverage
  installs and transient archives belong under
  `.fpvs_cache/mne/MNE-fsaverage-data/`, never `%TEMP%`, AppData, `src/`,
  `docs/`, package data, or an optional quarantine tree.
- Reject configured fsaverage candidates under source, docs, temp, or common
  admin-protected system folders; ignore stale generic MNE settings there so the
  root-local cache can be used.
- Prepared display meshes may be cached under
  `.fpvs_cache/loreta_visualizer/meshes/`, keyed by source fingerprints,
  surface, decimation, and schema.
- MRI slice display requires cached `fsaverage/mri/brain.mgz` and retains its
  visualizer-only 0.5 mm display template under
  `.fpvs_cache/loreta_visualizer/mri_templates/`. That underlay must never
  replace or mutate fsaverage or become a producer/toolbox dependency.
- Project source exports stay under the active project root and reject silent
  output escapes. Do not write visualizer settings or source outputs into
  `project.json` unless a future plan explicitly scopes that migration.
- Missing source-ready FIF/preprocessing inputs must produce a clear
  prerequisite message for current time-domain builds. Missing FullFFT/Stats
  inputs must do so for explicitly invoked legacy amplitude-workbook builds.
  Legacy workbook discovery supports both flat and condition/group layouts.

## GUI, Worker, And Export Rules

- Use PySide6 only. Long, network-backed, source-build, fsaverage, and real-data
  work runs in `QThread` or `QRunnable`; workers communicate by signals and must
  not touch widgets.
- Keep source rebuild/import controls in Source Map Options. Keep figure actions
  in the Export Figures modal, with one side-panel entry point.
- Do not run local offscreen Qt workflows. Qt tests are CI-only by default;
  document a visible/manual smoke path for changed interactions.
- Publication exports follow
  `docs/agent/quality/figure-generation.md`: matching 600-DPI PNG/PDF outputs
  and `Main_App.exports.figure_style` Arial typography.
