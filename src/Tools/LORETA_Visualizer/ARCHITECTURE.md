# LORETA Visualizer Architecture

This page is the tool-local architecture contract for agents working in
`src/Tools/LORETA_Visualizer/`.

## Purpose

The LORETA Visualizer is an embedded PySide6 tool for interactive 3D display of
an anatomical brain mesh plus prepared source-activation payloads. It supports
both transparent overlay views for volume/deep payloads and opaque cortical
paint views for the current L2-MNE cortical-surface method, including the
default publication-style split-hemisphere layout.
It is a new source-localization visualization branch. It is not a revival,
refactor, or design continuation of the removed `Tools.SourceLocalization`
implementation.

The first durable goal is rendering:

- real-time orbit, zoom, reset, and opacity controls where opacity is relevant;
- driver-tolerant transparent mesh rendering using plain alpha blending rather
  than VTK depth peeling;
- independent left/right hemisphere rotation in publication-style cortical
  display mode;
- an external fsaverage-derived anatomical mesh when available;
- a synthetic fallback mesh when fsaverage is unavailable;
- synthetic scalar source maps for tests/developer rendering validation;
- a payload contract that future real source-localization producers can feed
  without changing renderer internals.

The first implemented source-ready method is a beta L2-MNE cortical surface
producer for FPVS oddball-response maps. It is one method that emits the same
prepared payload/manifest format expected from any later LORETA/eLORETA volume
or mixed source-space producer.

Phase 6C adds the first project-connected beta export path. It uses real
project condition topographies, an external MNE/fsaverage BioSemi64 template
EEG forward model, and the existing prepared payload/manifest bridge so real
project data can be viewed without changing renderer internals.

Current amplitude-derived project source-map readers consume the shared
`Main_App.projects.dataset_index` records for both flat condition workbook
folders and condition/group workbook subfolders. Canonical participant and
group identity comes only from project metadata through that index. Those
legacy/exploratory routes require the Stats-ready workbook and, for z-scores,
`FullFFT Amplitude (uV)` target and neighboring-bin columns; true multi-group
projects are partitioned before source-input aggregation.

The normal Hauk-informed source-PSD routes instead read the processing-time
harmonic selection and durable, signed time-domain derivatives written while
condition epochs are resident. One rebuild generates both L2-MNE cortical and
eLORETA volume outputs. Frequency QC/harmonic selection and Stats-ready export
are sibling downstream consumers: a Stats workbook failure does not by itself
invalidate otherwise complete source-PSD inputs. Existing valid signed
FIF/JSON derivatives can therefore be reused to rebuild source maps after an
orientation-method update; sensor preprocessing need not be repeated solely to
regenerate the maps.

The default L2 method, `l2_mne_hauk_source_psd_cortical_normal_v1`, selects the
cortical surface-normal component with MNE source PSD `pick_ori="normal"`. The
GUI can instead request historical `l2_mne_hauk_source_psd_v1` when a user
needs to reproduce older pooled-orientation maps. Method IDs, provenance, and
caches remain distinct. The cortical-normal estimator is closer to the Hauk
source-spectrum implementation, but this EEG-only fsaverage route is still a
Toolbox adaptation rather than an exact reproduction.

The current eLORETA volume method,
`eloreta_volume_hauk_source_psd_vector_norm_v1`, shares the L2 route's signed
FIF inputs, condition-specific cohorts, selected harmonics, exact frequency-bin plan,
and neighboring-bin z-score algorithm. It nevertheless forms complex
periodic-Hann coefficients at the exact required bins, applies an independent
MNE eLORETA inverse with `pick_ori="vector"` in fsaverage volume source space,
and reduces the resulting three-component coefficient as
`sqrt(sum(abs(Cxyz)^2))` at each source and frequency. It computes separate
participant source-amplitude and z-score arrays; L2-MNE arrays and cortical
masks are never reused as eLORETA values. The old
`eloreta_volume_hauk_source_psd_v1` identity remains readable as a historical,
orientation-basis-dependent result. Both current methods refuse FullFFT
workbooks as fallback source inputs.

## Non-Goals

Outside the dedicated `source_producers/` subpackage, this directory must not
own:

- LORETA, sLORETA, eLORETA, beamformer, MNE inverse, or other source-estimation
  calculations;
- FPVS frequency-domain statistics, harmonic selection, or condition effects;
- preprocessing, BDF loading, Stats methods, project manifests, diagnostics, or
  project-output discovery;
- retired `Tools.SourceLocalization`, `src/quarantine/**`,
  `src/Main_App/Legacy_App/**`, or `src/Main_App/PySide6_App/**` behavior;
- bundled fsaverage or MRI template data in source, docs, quarantine, or
  package data. Automatic fsaverage fetches use the untracked FPVS Toolbox
  root cache instead.

## Ownership

Tool implementation lives inside `src/Tools/LORETA_Visualizer/`.

Allowed outside this directory are the narrow shell integrations described by
this contract: Main App sidebar/page/icon wiring, project-page cleanup, focused
tests, and documentation. Update any matching active execution plan when one
exists.

## Data Flow

The renderer consumes display-ready objects. Calculation outputs must be
prepared and validated before they reach `renderer.py`.

```text
Swappable source calculation producer
L2-MNE cortical surface beta, future LORETA volume, etc.
        |
        | prepared payload JSON / manifest JSON
        v
prepared_payload_validator.py
        |
        | validated coordinates, scalar values, source metadata
        v
Tool-local bridge helpers
source_payloads.py + transforms.py + scalar_fields.py + cortical_paint.py + volume_overlay.py + volume_slices.py
        |
        | SourcePayload in renderer display space
        v
renderer.py
        |
        | PyVista actors and camera controls
        v
Embedded 3D viewport
```

The anatomical side follows a parallel path:

```text
FPVS Toolbox root-local fsaverage cache, allowed configured subjects-dir, or synthetic fallback
        |
        v
fsaverage_mesh.py / synthetic_brain.py
        |
        | BrainMesh + MeshDisplayTransform
        v
renderer.py
```

Demo conditions are local validation data only:

```text
conditions.py + dummy_activation.py
        |
        | synthetic SourcePayload values
        v
renderer.py
```

## Source Producer Boundary

Real source-localization methods should be implemented as calculation
producers, separate from display code. A producer owns method assumptions,
forward/inverse model construction, montage assumptions, FPVS harmonic handling,
condition aggregation, and scalar source metrics. Its output is a prepared
payload JSON file or a prepared manifest plus payload files.

Producer code may use scientific libraries such as MNE, but it must not import
or call `gui.py`, `renderer.py`, `fsaverage_mesh.py`,
`prepared_payload_importer.py`, `source_payloads.py`, `transforms.py`, or
`scalar_fields.py`. The importer and bridge helpers remain the display-side
translation layer.

Phase 6A added the first method as a beta L2-MNE cortical-surface producer:

- target BioSemi ActiveTwo 64-channel / 10-10 montage assumptions first;
- target group-level condition maps first, with individual maps later;
- use the Stats-locked group significant oddball harmonic list exactly;
- emit fsaverage-aligned cortical surface payloads with method metadata such as
  `l2_mne_cortical_surface_beta`;
- document that this method is cortical-surface source estimation and does not
  claim hippocampal or other deep localization.

LORETA/eLORETA volume methods are sibling producers that emit
`volume_points`, `volume_mesh`, or ROI mesh payloads. They should not require
renderer, importer, or bridge-helper rewrites.

The original amplitude-workbook beta eLORETA volume path follows that
sibling-producer rule. It adds
`source_space_statistics.py` for method-neutral source-space cluster
permutation helpers, `eloreta_volume.py` for participant-first eLORETA volume
payloads, and `project_eloreta_volume_export.py` for project-local export under
`6 - Source Localization/eLORETA Volume Beta/`. This path remains importable as
legacy/exploratory and is not a fallback for current source-PSD generation.
Volume masks are recomputed with volume adjacency and stored as
`cluster_mask_source_indices` rather than surface vertex indices.

The renderer displays prepared eLORETA `volume_points` through a smoothed,
display-space grid/contour overlay in transparent mesh mode. This smoothing is
for visualization only: it is applied after source-mask/exploratory filtering
and does not modify saved source values, source-space statistics, or payload
metadata. The transparent mesh view additionally clips volume overlays to the
currently displayed brain surface so outside-shell volume activity is not
painted against a cortical mesh that does not anatomically contain it.
The GUI also exposes an orthogonal MRI slice display for eLORETA volume
payloads. That view uses the same prepared payload values and display
filtering, maps display points back into the fsaverage MRI voxel frame, chooses
a shared slice triplet from the loaded condition set for the selected
method/summary/mask state, and interpolates values onto axial, coronal, and
sagittal slices for visualization and publication figure export only.

Phase 6C adds `project_l2_mne_export.py` as calculation-side orchestration. It
is allowed to read shared indexed project workbooks through `project_inputs.py`, use
MNE to build an fsaverage/BioSemi64 template forward model, and write generated
payload/manifest JSON under the active project root. It must not update
`project.json`, change Stats outputs, modify preprocessing data, or teach the
renderer how L2-MNE works.

Phase 6D adds `l2_mne_hauk_zscore.py`,
`project_fullfft_inputs.py`, and
`project_l2_mne_hauk_zscore_export.py` as a separate Hauk-style
source-space z-score path. It reads raw project `FullFFT Amplitude (uV)` target
and neighboring frequency-bin topographies, sums selected harmonics in sensor
space, estimates target/noise source amplitudes through the same inverse model,
and writes `source_value_unit: z-score` payloads. It must not derive z-scores
from already summed BCA values or compact selected-harmonic summaries.

The Hauk source-PSD feature adds `project_time_domain_inputs.py`,
`hauk_source_psd.py`, `project_l2_mne_hauk_source_psd_export.py`, and
`project_eloreta_volume_hauk_source_psd_export.py` as versioned sibling paths.
Main App processing publishes one signed,
repetition-averaged EEG Raw FIF per participant/condition plus provenance and a
participant commit manifest. Project orchestration derives one explicit
available-case cohort for each group-condition cell, and the read-only adapter
strictly validates every retained participant/condition input. Before either
inverse runs, the adapter selects the exact sample count `N` supported by a
unique modal number of participants. Nonmodal participant-condition derivatives are recorded as
condition-specific omissions with their actual and canonical `N`, duration,
and frequency resolution. This keeps all retained participant z-scores on one
FFT resolution and neighboring-noise-bin contract without shortening the
project to an anomalously brief record. A tied modal distribution fails
actionably rather than choosing a scientific contract arbitrarily. Each producer
applies its own EEG-only fsaverage BioSemi64 inverse. Default L2-MNE calls MNE source PSD with
the cortical-normal orientation before amplitude/harmonic aggregation; current
eLORETA applies its inverse to complex exact-bin Hann coefficients and performs
rotation-invariant vector pooling afterward. Each sends its own participant
source z-score arrays through the relevant aggregation, cluster, and
prepared-payload stages. The L2-MNE cortical path additionally retains surface
ROI/lateralization output; the eLORETA volume path does not fabricate cortical
lateralization rows.
When a project has multiple canonical participant groups, the exporter creates
separate group-by-condition aggregation and cluster inputs. Group identity is
preserved in prepared condition metadata; experimental groups are not pooled
silently. A group-condition cell with no retained participants is omitted. A
one-participant cell remains available as a descriptive map and records an
insufficient-participants cluster-mask status.

This method is deliberately Toolbox-specific where appropriate: project-selected
significant oddball harmonics remain authoritative, exact FPVS bins are
required, and neighboring noise uses offsets `-10..-2` and `+2..+10` before
one global minimum/maximum removal and population-SD (`ddof=0`) z scoring. The
method metadata must identify that nine-candidate-bins-per-side rule as an
intentional Toolbox adaptation, not an exact reproduction claim.

The methodological precedents are Hauk et al. (2021), *Face-selective responses
in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS)*
([DOI](https://doi.org/10.1016/j.neuroimage.2021.118460)), and the public
[`olafhauk/FPVS_sweep`](https://github.com/olafhauk/FPVS_sweep) repository,
including `FPVS_PSD_Source_sweep.py`. Cite them as influences on the
source-spectrum design. The default cortical-normal L2 estimator follows the
Hauk orientation choice more closely, while the vector-norm eLORETA volume path
is an FPVS Toolbox extension. Do not claim that either EEG-only template
implementation exactly reproduces their combined EEG/MEG or individual-anatomy
pipeline.

The supported source models are EEG-only `fsaverage` with Toolbox BioSemi64
geometry. MEG, individual MRI/coregistration, and mixed-modality fusion are
explicit non-goals. The L2-MNE inverse remains MNE-native with `method="MNE"`,
`loose=0.2`, `depth=None`, `fixed=False`, `lambda2=1/9`, and no dSPM,
sLORETA, or eLORETA normalization. The independent volume inverse uses
`method="eLORETA"`, a 10 mm fsaverage volume grid, `loose=1.0`, `depth=None`,
`fixed=False`, and `lambda2=1/9`. Both use MNE's ad-hoc diagonal EEG noise
covariance because the Toolbox workflow does not require a separate
resting/noise acquisition. These EEG/template choices are documented
departures from the reference pipeline's recorded resting covariance,
individual anatomy, and combined EEG/MEG analysis.

Source orientation is producer-owned and versioned. Source Map Options may pass
the default cortical-normal or historical pooled-orientation choice into the
next L2 rebuild, but the visualizer's Method and Display selectors only select
already-prepared results and rendering styles. They never recompute, reinterpret,
or change source orientation. Current eLORETA always uses vector-norm pooling;
it is not a display option.

Phase 6E adds documentation and GUI source-map options around those producer
paths. Project source-map generation excludes participants listed in
`Flagged Participants.xlsx` by default. The GUI may pass an
`include_flagged_subjects` opt-in choice into project rebuild workers and log
compact rebuild summaries, but source-estimation math still belongs only to
`source_producers/`.

## File Responsibilities

- `gui.py`: embedded page, controls, status text, fsaverage worker wiring, and
  user-triggered renderer updates. Source-map rebuild/import controls live in
  the Source Map Options modal. Figure export actions live behind the compact
  Export Figures modal so future display-specific exports can be added without
  crowding the side panel. The method selector groups loaded manifests by
  source method, keeps condition/summary selection method-local, and restricts
  non-cortical volume payloads to Transparent brain mesh and MRI slices
  displays. After Main App post-processing attempts source generation, an
  already-cached visualizer page reloads any successfully written current
  source-map manifest even when its sibling method failed. If neither current
  manifest survives the attempted rebuild, the page clears only a previously
  project-loaded map and warns that no current result is available; a manually
  imported payload is preserved. This reconciliation never starts source
  estimation and does not instantiate the page when it has not been opened.
- `renderer.py`: PyVista/VTK scene adapter. It displays base meshes,
  prepared source payloads, opacity where relevant, scalar ranges, cortical
  paint actors, split-hemisphere publication actors, and camera controls. It
  disables VTK depth peeling and relies on normal alpha blending so
  transparent brain meshes remain visible across supported Windows graphics
  stacks. It must not calculate source estimates.
- `fsaverage_cache.py`: shared fsaverage cache path policy. Automatic fetches
  install fsaverage and keep transient ZIP archives under
  `.fpvs_cache/mne/MNE-fsaverage-data/` in the FPVS Toolbox root. `src/`,
  `docs/`, quarantine, package-data paths, temp directories, and common
  admin-protected system folders are rejected. Stale generic MNE config
  candidates under forbidden paths are ignored; explicit
  `FPVS_FSAVERAGE_SUBJECTS_DIR` overrides under those paths fail fast.
- `fsaverage_mesh.py`: fsaverage discovery/fetch/read/decimation and
  construction of the anatomical display transform. It also preserves
  display-only left/right hemisphere meshes for publication layout. The
  combined mesh remains pial for the single-surface and transparent views;
  fsaverage inflated hemispheres are used only as the split-view display canvas
  when their topology matches the pial/source surface. FreeSurfer `curv` or
  `sulc` morph values may be read as split-view gray-white underlay shading.
  The prepared renderer-facing mesh is cached under the untracked root
  `.fpvs_cache/loreta_visualizer/meshes/` cache and invalidated when the
  fsaverage source files, surface choice, decimation setting, or cache schema
  changes.
  It must not calculate source estimates.
- `synthetic_brain.py`: deterministic fallback brain mesh and `BrainMesh`
  dataclass.
- `conditions.py`: synthetic demo condition metadata retained for validation.
- `dummy_activation.py`: deterministic demo-only scalar source maps retained for
  tests/developer validation, not normal live selector options.
- `prepared_source_fixture.py`: in-memory fixture that is shaped like a
  prepared source-map handoff from a future real calculation path. It validates
  and adapts coordinates/scalars but does not calculate source estimates.
- `prepared_payload_importer.py`: controlled JSON importer for prepared source
  payloads and source-payload manifests. Payload files include coordinates,
  scalar values, faces, coordinate-space labels, and metadata; manifest files map
  condition labels to relative payload JSON files. This is user-selected file
  input only, not project-output discovery. Prepared payload imports may be
  cached in memory by file mtime, file size, and display-transform signature so
  repeated condition switching does not re-read unchanged payload files.
- `prepared_payload_validator.py`: producer-facing validation for prepared
  payload and manifest JSON. It owns format constants, schema descriptors, and
  cross-field checks. It does not render, calculate source estimates, or inspect
  project outputs.
- `cortical_paint.py`: display-only projection from a prepared L2-MNE cortical
  surface payload onto the higher-resolution pial display mesh. It may
  interpolate already-computed values for visualization, but it must not compute
  source estimates or change payload values.
- `volume_overlay.py`: display-only smoothing from prepared volume source
  points onto a regular PyVista grid for transparent mesh contour overlays.
  The transparent mesh view may clip this overlay to the displayed cortical
  surface, but it must not mutate saved source values or source-space masks.
- `volume_slices.py`: display/export-only orthogonal MRI slice rendering for
  prepared volume point payloads. It requires `fsaverage/mri/brain.mgz`, builds
  a visualizer-only 0.5 mm display template in the untracked root
  `.fpvs_cache/loreta_visualizer/mri_templates/` cache, and loads that higher
  sampling underlay for embedded and exported MRI slices. The cache preserves
  the fsaverage RAS frame and must not replace or mutate the fsaverage cache
  used by source producers, mesh loading, or other toolbox modules. It surfaces
  a visible error when the source anatomy, display-template generation, or the
  all-condition slice reference is unavailable, converts display points back to
  native voxel space, reuses a standard slice triplet across conditions,
  interpolates already computed source values onto slice planes with the same
  Gaussian-neighbor policy family as the transparent mesh overlay, crops each
  panel to the anatomy bounds for high-detail embedded viewing, and writes
  matched 600-DPI PDF/PNG figures. It must not compute inverse estimates,
  z-scores, cluster masks, or condition effects.
- `source_producers/`: swappable source-localization calculation methods that
  read explicit source-ready inputs and write validated prepared
  payload/manifest JSON. Phase 6A includes method-neutral producer result
  contracts and `l2_mne_cortical.py`, a beta L2-MNE cortical surface producer
  with a deterministic BioSemi64/10-10 source-ready fixture. Phase 6H-A(1)
  lets real project exports attach an MNE-native loose-orientation estimator
  while preserving the same payload contract.
  Phase 6B includes `project_inputs.py`, a read-only adapter that assembles
  source-ready condition topographies from shared dataset-index records for
  existing flat or condition/group project workbooks. It does not infer
  participant or group identity locally. Phase 6C includes
  `project_l2_mne_export.py`, a
  project-local beta export that combines
  those topographies with an external MNE/fsaverage BioSemi64 template forward
  model and writes prepared source-map JSON. Phase 6D includes
  `l2_mne_hauk_zscore.py`, `project_fullfft_inputs.py`, and
  `project_l2_mne_hauk_zscore_export.py`, which produce project-local
  source-space z-score payloads from FullFFT target/noise-bin data. Phase
  6H-A(2) makes that Hauk-style path participant-first by default: project
  inputs preserve participant target/noise-bin topographies, the producer
  computes participant source-space z-score maps, and the export writes group
  raw mean, median, and 20% trimmed-mean prepared payloads plus a participant
  sidecar for future individual viewing. The deprecated group-first z-score
  model is retained only as an advanced comparison fallback and is not exposed
  in the normal Source Map Options GUI. Phase 6H-A(3)
  computes participant-first source-space cluster-permutation masks and stores
  the significant source vertices in payload metadata for publication-style
  display. Phase 6H-A(4) writes a descriptive source-space lateralization
  summary from already-computed participant/group maps and producer masks.
  Phase 6H-A(5) preserves fsaverage source vertex IDs and hemisphere labels,
  reads fsaverage Desikan-Killiany `aparc` temporal labels, and writes the
  primary Hauk-style inferior/middle/superior temporal ROI lateralization rows.
  `source_validation_report.py` writes project-local JSON/Markdown summaries
  from already-generated manifest, payload, participant-sidecar, and
  lateralization files. It is a reporting helper only: it must not estimate
  sources, run statistics, inspect renderer state, or mutate project inputs.
  The legacy beta eLORETA volume producer set uses the participant-first
  FullFFT/z-score input contract. The current
  `project_eloreta_volume_hauk_source_psd_export.py` path instead consumes the
  signed source-ready FIF contract and writes independently computed
  `eloreta_volume_hauk_source_psd_vector_norm_v1` `volume_points` payloads.
  Historical signed-FIF outputs with method identity
  `eloreta_volume_hauk_source_psd_v1` remain loadable but are explicitly
  orientation-basis-dependent legacy results. Both write a participant sidecar
  and method-neutral source-index cluster-mask metadata; neither emits surface
  lateralization rows.
  Later producers may use other LORETA/eLORETA volume or mixed source-space
  models.
- `source_rois.py`: producer-side anatomical ROI helpers that map named
  fsaverage label definitions onto already-computed source spaces using stable
  source vertex IDs and hemisphere labels. It must not estimate sources, render
  payloads, or perform statistics.
- `source_lateralization.py`: producer-side descriptive summaries of
  right/left source activation from already-computed source values. It may use
  producer-provided masks, precomputed anatomical ROIs from `source_rois.py`,
  and coordinate-defined whole-hemisphere/LOT-ROT QC rows, but it must not run
  inverse estimation, perform inferential lateralization tests, or inspect
  renderer state.
- `source_validation_report.py`: producer-side project report generation from
  emitted source-output files. It writes `source_validation_report.json` and
  `source_validation_report.md` beside the Hauk z-score manifest and must not
  calculate source values, derive masks, inspect renderer actors, or discover
  unrelated project files.
- `examples/`: checked-in synthetic JSON payload and manifest fixtures that show
  the expected output shape for future source-localization producers. They are
  format examples only and are not source estimates. This directory also holds
  the shape-level JSON Schema files for external tooling.
- `source_payloads.py`: renderer-facing `SourcePayload` validation,
  finite-value filtering, metadata preservation, non-surface positive-z display
  filtering, and payload conversion to display space.
- `transforms.py`: `MeshDisplayTransform` and coordinate-space constants.
- `scalar_fields.py`: visual scalar color stops and auto/manual color-limit
  resolution.

When validation code exercises a non-identity native/display transform, demo
payloads intentionally round-trip through native coordinates and
`source_payload_to_display(...)`. This exercises the same bridge that future
real source payloads should use, while keeping the values synthetic.

## Bridge Contract

The bridge helpers are the only place where future calculation outputs should be
normalized for rendering.

Allowed bridge behavior:

- validate `N x 3` coordinates and one scalar value per point;
- preserve faces, labels, source model metadata, and value labels;
- reject mismatched coordinate-space labels;
- convert native anatomical/source coordinates into renderer display space;
- treat `fsaverage_surface` and `fsaverage_volume` as compatible
  FreeSurfer/fsaverage millimeter spaces for display normalization while
  preserving their distinct payload labels;
- normalize or bound values for visual color mapping;
- adapt future real data into `SourcePayload`.

Disallowed bridge behavior:

- compute inverse solutions or LORETA values;
- choose source-localization methods;
- compute FFT, SNR, BCA, harmonic significance, or condition effects;
- discover or write project source-localization outputs unless a future plan
  explicitly scopes project integration;
- copy design or code from removed Source Localization/eLORETA modules.

## Source Payload Contract

Future real source-localization producers should hand this tool a prepared
payload with:

- `format`: `fpvs-loreta-source-payload-v1`;
- `label`: human-readable source-map label;
- `points`: finite `N x 3` coordinates;
- `values`: finite scalar values aligned one-to-one with `points`;
- `coordinate_space`: explicit native/display/source coordinate-space label;
- `kind`: surface points, surface mesh, volume points, volume mesh, or ROI mesh;
- `source_model`: method/model description such as `volume_grid`,
  `cortical_surface`, or a future method-specific label;
- optional VTK-style `faces` for mesh payloads;
- optional metadata that describes provenance without changing renderer logic.
  For participant-first L2-MNE z-score payloads, metadata may include
  `cluster_mask=source_space_cluster_permutation` and
  `cluster_mask_vertex_indices` so the renderer can display only
  producer-computed significant source vertices. For volume or other
  non-surface payloads, metadata may include `cluster_mask_source_indices` for
  the same display-only mask behavior without implying cortical vertices.

If a future method changes from LORETA to another inverse model, the renderer
should stay unchanged. The adapter/bridge should map the method output into this
payload contract.

For the beta L2-MNE cortical-surface method, expected payloads should identify
the method in `source_model`/metadata, use a cortical surface payload kind, and
describe the source metric clearly. A later volume LORETA method should use the
same outer payload shape but a volume or ROI payload kind and method-specific
metadata.

The current beta L2-MNE producer accepts source-ready arrays: channel names,
selected harmonic topographies, cortical source coordinates/faces, and a
channel-by-source leadfield. It writes payloads and manifests after validation.
`project_inputs.py` can assemble the selected harmonic topographies from
shared indexed flat condition workbooks or condition/group workbooks, but it still
does not compute Stats harmonic selections, export preprocessing data, write
project files, or build
subject-specific MRI forward models.

The project-input adapter reads the all-condition selected harmonics from the
Stats-ready workbook, consumes canonical workbook/participant/group records
from `Main_App.projects.dataset_index`, reads compact per-participant
electrode-level sheets (`BCA (uV)` or `FFT Amplitude (uV)`), applies existing
exclusion files, records flagged participant status, partitions true
multi-group projects before aggregation, and returns `L2MNEFPVSCondition`
objects for calculation producers.

The project L2-MNE exporter writes generated files under
`6 - Source Localization/L2-MNE Cortical Surface Beta/` by default. The manifest
can be loaded by the GUI's prepared-manifest importer. The GUI may trigger this
export in a worker thread and then load the resulting manifest, but all inverse
model construction and source-value calculation remain in `source_producers/`.

The project Hauk-style z-score exporter writes generated files under
`6 - Source Localization/L2-MNE Hauk Z-Score Beta/` by default. It uses the
same prepared-manifest importer as every other source payload. Its displayed
values are source-space z-scores, not arbitrary L2-MNE amplitude. It reads
`FullFFT Amplitude (uV)` only and refuses BCA-only or compact-summary-only
workbooks with a user-facing prerequisite message instead of fabricating
source-space z-scores. FullFFT ingestion uses the shared selected-column XLSX
XML reader so project source-map generation streams only `Electrode` plus the
target/noise-bin columns required by the current bin plan. The generated
payloads preserve the signed z-score field
for QC. The default L2-MNE cortical
surface view paints those values onto an opaque split-hemisphere display using
fsaverage inflated hemispheres when available and pial split hemispheres as a
fallback. The split display uses FreeSurfer `curv` gray-white underlay shading
when available, `sulc` as a fallback, and geometry-derived shading as a final
fallback. The alternate single-surface view paints the same values onto the
combined pial mesh. For participant-first maps with producer-computed
cluster-permutation metadata, source vertices outside the significant cluster
mask are shown as shaded cortex and retained positive z-scores use the same
heatmap ramp as the transparent overlay view. Older unmasked payloads fall
back to the manual display cutoff, whose default is `z >= 1.64`. A
condition/group with fewer than two participant maps cannot support the
one-sample permutation stage; its descriptive map is still written with an
explicit insufficient-participants mask status and shown as exploratory.
Empty computed masks also fall back to that exploratory cutoff: underpowered
exact small-sample masks warn that the mask cannot be resolved, and adequately
powered empty Hauk masks warn that no vertices survived the cluster mask. The
viewer can also disable a
saved cluster mask for exploratory z-threshold display and figure export. These
display fallbacks and toggles do not change the saved source values or compute
statistics in the renderer. The
neighboring-bin policy mirrors the Stats-style FPVS neighboring-bin window by
using offsets `-10..-2` and `+2..+10`, dropping the minimum and maximum
neighboring source amplitude per source point before computing the source-space
noise mean and population SD (`ddof=0`).

The time-domain source-PSD exporters write independently calculated prepared
outputs under `6 - Source Localization/L2-MNE Hauk Source PSD Beta/` with
default method identity `l2_mne_hauk_source_psd_cortical_normal_v1`. Source Map
Options can explicitly rebuild the historical pooled-orientation method
`l2_mne_hauk_source_psd_v1` instead. eLORETA outputs are written under
`6 - Source Localization/eLORETA Hauk Source PSD Beta/` with current method
identity `eloreta_volume_hauk_source_psd_vector_norm_v1`; the historical
`eloreta_volume_hauk_source_psd_v1` identity denotes the older
orientation-basis-dependent implementation. Their shared canonical inputs live under
`6 - Source Localization/Source-Ready Time Domain v1/` in
condition-first/group-second layout. An artifact pair is
`<condition label>/[<group>/]<participant>_<condition_id>_avg_raw.fif` and
`<condition label>/[<group>/]<participant>_<condition_id>_avg_raw.json`;
participant commit manifests are
`manifests/[<group>/]<participant>.json`. Each manifest is written only after
all expected condition FIF/sidecar pairs succeed. Readers reject missing,
stale, checksum-mismatched, incompatible-channel, or off-bin retained sets
rather than falling back to amplitude workbooks. Before that strict load, the
project exporter applies `available_case_by_group_condition_v1`: each completed
participant contributes to every canonical condition with a committed
derivative, while an explicitly missing condition omits only that
participant-condition input. Each prepared map records its own participant
count and identities. Empty group-condition cells are omitted; one-participant
cells remain descriptive without an inferential cluster mask. Participants
with unknown availability or no available canonical conditions are omitted
globally. Both omission scopes and reasons are written to the prepared
manifest, participant sidecar, validation report, structured log, and GUI
warning status. A derivative with a nonmodal sample count is a condition-level
source omission; a tied sample-count distribution, or a retained derivative
that is missing, corrupt, stale, or otherwise incompatible, still stops the
build. The FIF
contains signed EEG volts, exact processed `N` and sampling rate,
montage/reference state, and no FFT or source values.

For each included participant/condition, default L2-MNE computes cortical-normal
source PSD on the complete averaged time series, converts power to amplitude,
and then aligns exact target/noise positions. Current eLORETA instead computes
the required complex periodic-Hann sensor coefficients, preserves them through
`apply_inverse(..., pick_ori="vector")`, and obtains an orientation-invariant
amplitude with `sqrt(sum(abs(Cxyz)^2))`. Both then sum corresponding positions
across the canonical harmonic plan in their own source spaces and apply the
Toolbox neighboring-bin z-score. Only compact method-specific participant
results are cached; source amplitudes are reproducible from the durable
time-domain derivative and are not retained in full by default. Cache keys omit
harmonic-cache bookkeeping fields (source label, save time, and saved cache ID)
while the full prepared-output provenance retains them, so recalculating an
identical harmonic selection does not repeat the participant inverse solely
because the bookkeeping timestamp changed.

The legacy amplitude-derived eLORETA exporter continues to write under
`6 - Source Localization/eLORETA Volume Beta/`. Its manifest and the legacy
amplitude-derived L2-MNE manifest remain importable with explicit method labels,
but neither is used as a fallback when signed FIF inputs are missing or invalid.
Current eLORETA volume payloads use the same saved cluster-mask toggle semantics:
when enabled, saved source-index cluster masks filter displayed source
locations; when disabled or unavailable, transparent volume z-score overlays
use positive-only exploratory display filtering. Display behavior does not
change saved payload values.

On first open, if no current time-domain source manifest exists, the GUI may
start one background rebuild that generates default cortical-normal L2-MNE and
vector-norm eLORETA outputs. If one current method is already available, the GUI
loads that valid partial result instead of automatically rebuilding only because
the sibling is absent. Manual and post-processing rebuilds use the two-method
batch; Source Map Options exposes only the L2 orientation choice because the
corrected eLORETA vector norm is fixed. One method may report a method-specific
failure without relabeling or discarding a successfully generated sibling
result. The Method selector remains a display selector over loaded manifests,
not a numerical method editor.

Checked-in examples live in `examples/`. The fsaverage-native example is the
preferred reference shape for future calculations that produce coordinates in
the same source space as the anatomical mesh. The display-space examples and
manifest are intended for importer and GUI validation without requiring an
fsaverage cache.

Future calculation producers should use `prepared_payload_validator.py` for
preflight validation before handing JSON to the GUI importer. The JSON Schema
files provide an external-tooling shape contract, while the Python validator
adds cross-field checks that the schema intentionally does not own.

## Verification

Use the focused tool gate; it selects `.venv1` or `.venv`, applies the Qt guard,
and runs the tool tests, static checks, and legacy/source-localization audits:

```powershell
python .agents/scripts/verify.py --scope loreta --tier focused
```

Qt execution is CI-only by default. For viewport behavior, document a
visible/manual smoke path instead.
