# eLORETA Volume Source Estimation

## Status

Active plan for `codex/loreta-volume-method-spike`.

Implementation started 2026-06-20:

- added a method-neutral source-space cluster statistics helper;
- added beta eLORETA volume producer/exporter modules under
  `src/Tools/LORETA_Visualizer/source_producers/`;
- added GUI source-method grouping/selection between L2-MNE surface and
  eLORETA volume manifests;
- preserved L2-MNE normalization and aggregation behavior as the default path.

This plan scopes a beta eLORETA volume source-space method for the LORETA
Visualizer. It extends the current participant-first Hauk-style source-map
workflow by adding a second source-space method that is as close as practical to
the existing L2-MNE cortical-surface z-score path, while using a three
dimensional volume source space and method-appropriate volume adjacency for
cluster masking.

This is not a restoration of the retired Source Localization/eLORETA runtime.
Do not use `src/Tools/SourceLocalization/**`, `src/quarantine/**`, retired
legacy launchers, historical settings, or old GUI workflows as design inputs.
The implementation belongs under `src/Tools/LORETA_Visualizer/`, with numerical
source estimation confined to `source_producers/`.

## Date

Created: 2026-06-20

## Goal

Add a beta eLORETA volume source-space method that can be selected in the
LORETA Visualizer alongside the current L2-MNE cortical-surface method.

The eLORETA volume method should preserve the existing source-map math contract
where possible:

- read the same project FullFFT target and neighboring-bin inputs;
- exclude Stats QC flagged participants by default, with the existing explicit
  include-flagged option preserved;
- estimate each participant independently before group aggregation;
- compute participant source-space z-score maps from target and neighboring
  source estimates;
- aggregate participant z-score maps into raw mean, median, and 20% trimmed
  mean group summaries;
- apply the same one-sample, positive-tail, sign-flip cluster-permutation
  strategy to participant z-score maps;
- store the producer-computed mask in prepared payload metadata;
- let the existing cluster-mask display toggle enable masked publication-style
  display or disabled-mask exploratory viewing without altering saved values.

The intentional difference is the source space and inverse method:

- current method: L2-MNE on an fsaverage cortical surface, rendered primarily
  as cortical paint;
- planned method: eLORETA on an fsaverage/template volume source space,
  rendered primarily through the transparent brain mesh.

## Problem

The current Hauk-style L2-MNE source-map path is useful for publication-style
cortical-surface figures, but the transparent mesh view is not scientifically
very meaningful for that method because the data live on a cortical surface.
The transparent mesh becomes more appropriate when the payload contains
prepared values distributed through a 3D source grid.

The next method should therefore add a real volume source-space payload while
preserving the strongest parts of the current L2-MNE implementation:

- participant-first z-score maps rather than group-first maps;
- raw FullFFT target/noise-bin inputs rather than compact BCA summaries;
- robust group summaries;
- source-space cluster permutation for group-level masking;
- renderer/importer separation from numerical source estimation.

## Non-Goals

- Do not revive or import from the retired `src/Tools/SourceLocalization/**`
  tree.
- Do not move source-estimation math into `gui.py`, `renderer.py`,
  `fsaverage_mesh.py`, `prepared_payload_importer.py`,
  `source_payloads.py`, `transforms.py`, `scalar_fields.py`, or
  `cortical_paint.py`.
- Do not change preprocessing order, Stats harmonic selection, FullFFT export
  formats, project manifests, BDF loading, or Publication Report behavior.
- Do not implement subject-specific MRIs, individual BEMs, or BIDS-derived
  forward models in this slice.
- Do not claim precise deep-source localization from template EEG eLORETA
  outputs. Treat this as a beta, template-based visualization and method
  validation path.
- Do not add mixed surface-volume source spaces in the first implementation
  slice. Mixed spaces can follow after the volume-only path is validated.
- Do not add new figure export layouts until the volume payload, method
  selection, and mask semantics are stable.

## Scientific Design

### Source Method

Use MNE-Python's minimum-norm inverse machinery with `method="eLORETA"` on an
fsaverage/template volume source space. The repo currently pins MNE 1.9.0, and
the local API exposes:

- `mne.setup_volume_source_space(...)`;
- `mne.spatial_src_adjacency(...)`;
- `mne.minimum_norm.apply_inverse(..., method="eLORETA", method_params=...)`.

Initial defaults should mirror the current L2-MNE path unless there is a clear
method-specific reason to diverge:

- BioSemi64/10-10 channel assumptions;
- average-reference projection policy;
- fsaverage/template model;
- `lambda2 = 1 / 9`;
- selected oddball harmonics from existing project/Stats outputs;
- target/noise-bin source estimates computed from raw `FullFFT Amplitude (uV)`
  topographies;
- participant-first source z-scores.

eLORETA-specific parameters should be explicit in metadata. Start with MNE
defaults for `eps`, `max_iter`, and `force_equal`, then record the resolved
values in the payload/report metadata. If loose orientation is used, preserve
MNE's recommendation that `force_equal=True` behavior is appropriate for loose
orientation inverses.

### Z-Score Model

The eLORETA volume path should follow the current Hauk-style L2-MNE source
z-score model:

1. For each participant and condition, read selected harmonic target
   topographies plus matching neighboring-bin topographies.
2. Sum selected harmonic target topographies in sensor space.
3. Sum matching-offset neighboring-bin topographies in sensor space.
4. Apply the eLORETA volume inverse model to the participant target map and
   each neighboring-bin map.
5. For every source location, compute the participant source z-score from the
   target estimate relative to neighboring-bin estimates.
6. Drop the minimum and maximum neighboring source amplitudes per source
   location before computing noise mean and population standard deviation,
   matching the current L2-MNE behavior.
7. Preserve signed z-score values in the prepared JSON payload and participant
   sidecar.
8. Build group raw mean, median, and 20% trimmed mean maps from participant
   z-score maps.

This keeps the group map interpretable as a group summary of participant
source-space z-scores, not an inverse of an already-aggregated group
topography.

### Cluster Mask

Apply the same cluster-permutation strategy, but recompute it in eLORETA volume
space. Do not reuse the cortical-surface L2-MNE mask.

The shared statistical engine should be source-space neutral:

1. Build a participants x source-locations matrix from participant eLORETA
   volume z-score maps.
2. Compute one-sample t values against zero at each source location.
3. Use the current positive-tail cluster-forming threshold defaults unless a
   later scientific review changes them:
   - cluster-forming `p = 0.00001`;
   - corrected cluster `alpha = 0.05`;
   - deterministic seed `20260609`;
   - up to `10000` permutations, with exact sign flips when participant count
     permits.
4. Use volume source-space adjacency, not cortical face adjacency.
   `mne.spatial_src_adjacency(src)` is the preferred first implementation path
   because it supports volume source spaces.
5. Form connected components among suprathreshold source locations.
6. Use sign-flipped participant maps to build the null distribution of maximum
   cluster mass.
7. Mark significant clusters and store retained source-location indices in
   metadata.

The metadata should become method-neutral while preserving backward
compatibility:

- keep reading/writing `cluster_mask_vertex_indices` for existing L2-MNE
  surface payloads;
- add `cluster_mask_source_indices` for volume and future non-surface payloads;
- include `cluster_mask_source_space_kind`, for example `surface` or `volume`;
- include `cluster_adjacency_source`, for example `surface_faces` or
  `mne.spatial_src_adjacency`;
- preserve `cluster_mask=source_space_cluster_permutation` and existing
  p-value/permutation fields.

The renderer and GUI should not compute t values, permutations, clusters, or
p-values. They only obey producer metadata.

## Architecture

### New Producer Modules

Add eLORETA as a sibling source producer, not as a modification to the renderer:

- `src/Tools/LORETA_Visualizer/source_producers/eloreta_volume.py`
- `src/Tools/LORETA_Visualizer/source_producers/project_eloreta_volume_export.py`

Expected project output folder:

```text
6 - Source Localization/eLORETA Volume Beta/
```

Expected manifest name:

```text
project_eloreta_volume_hauk_zscore_beta_manifest.json
```

Expected method IDs:

- `eloreta_volume_hauk_zscore_beta`;
- `eloreta_volume_participant_zscore`;
- `eloreta_volume_participant_zscore_mean`;
- `eloreta_volume_participant_zscore_median`;
- `eloreta_volume_participant_zscore_trimmed_mean`.

The exact names may be adjusted during implementation, but they must remain
clear, method-specific, and beta-labeled.

### Shared Source-Statistics Helpers

The current cluster code in `l2_mne_hauk_zscore.py` is already close to
source-space neutral. Factor the generic parts into a helper module before
adding eLORETA, for example:

- `src/Tools/LORETA_Visualizer/source_producers/source_space_statistics.py`

This helper can own:

- participant z-score matrix validation;
- one-sample t values;
- cluster-forming t threshold;
- sign-flip vector generation;
- connected-component cluster construction from an adjacency list;
- cluster mass;
- permutation max-cluster distribution;
- generic `SourceSpaceClusterPermutationResult` dataclasses.

The L2-MNE module should continue to expose its current public functions and
behavior, but call the shared helper internally. This first refactor must be
behavior-preserving and covered by the existing L2-MNE cluster tests before the
eLORETA producer is added.

### Volume Forward/Inverse Model

Add a volume model builder that parallels
`build_mne_fsaverage_l2_mne_forward_model(...)` but constructs a volume source
space:

- resolve fsaverage through the existing root-local cache policy;
- use existing BioSemi64 info/montage helpers where possible;
- use the existing BEM/transform policy where appropriate;
- call `mne.setup_volume_source_space(...)`;
- call `mne.make_forward_solution(...)`;
- build an inverse operator with MNE;
- estimate maps with `apply_inverse(..., method="eLORETA")`.

The model result should expose:

- channel names;
- source points;
- volume source-space object or enough adjacency metadata to build masks;
- coordinate space;
- source estimator callable;
- method metadata;
- optional volume grid shape, spacing, source indices, and MRI/template
  provenance.

The renderer-facing payload should be `kind="volume_points"` initially. A
volume mesh or interpolated MRI volume can be a later slice.

### Payload And Manifest Contract

The existing prepared payload contract already supports `volume_points` and
`volume_mesh`. eLORETA volume payloads should use the same outer shape:

- `format: fpvs-loreta-source-payload-v1`;
- `coordinate_space` matching the fsaverage/native space used by the producer;
- `kind: volume_points`;
- `source_model: eloreta_volume`;
- `value_label: source-space z-score`;
- `points`: one coordinate per volume source location;
- `values`: signed z-score summary values;
- metadata describing method, inverse settings, source-space kind, source grid,
  input metric, cluster mask, participant exclusion policy, and beta
  limitations.

For manifest grouping, keep the improved GUI selector behavior:

- condition selector shows each condition once;
- summary selector chooses raw mean, median, or 20% trimmed mean;
- new method selector chooses L2-MNE surface or eLORETA volume.

### GUI Method Selector

Add a source-space method selector without overloading the display selector.

Recommended toolbar structure:

- Method: `L2-MNE surface` or `eLORETA volume`;
- Condition;
- Summary;
- Display.

Method selection should filter the available condition/summary entries by
manifest method group. If only one method is loaded, the selector can remain
visible but disabled, or be hidden if doing so does not make state confusing.

Display behavior:

- L2-MNE surface defaults to `Split Hemispheres`;
- eLORETA volume defaults to `Transparent brain mesh`;
- split-hemisphere and cortical-surface display modes should be disabled or
  hidden for volume payloads until a deliberate projection path exists;
- transparent mesh display should keep the current positive-only z-score
  display behavior for exploratory unmasked volume maps.

Cluster mask behavior:

- the existing Source Map Options cluster-mask toggle applies to both methods;
- when enabled and a non-empty producer mask exists, display only retained
  source locations;
- when disabled, show exploratory positive z-score values using the manual
  threshold/display-color rules;
- status text must clearly distinguish publication-style producer masks from
  exploratory unmasked views.

### Rebuild Controls

The first implementation should keep the Source Map Options rebuild action
simple:

- default rebuild may continue to build the current L2-MNE surface maps until
  the eLORETA path is fully validated;
- add an explicit source-method rebuild choice only after the volume producer
  can write valid payloads and reload them;
- never compute source maps directly in a GUI slot. Use the existing worker
  pattern with `QThread` and signals.

## Implementation Slices

### Slice 1: Method-Neutral Cluster Statistics

- Add shared source-space statistics helpers.
- Move generic cluster permutation machinery out of
  `l2_mne_hauk_zscore.py` without changing L2-MNE outputs.
- Preserve current public L2-MNE functions and metadata.
- Add focused tests proving L2-MNE cluster results are unchanged.

Done means:

- existing `tests/loreta/test_l2_mne_hauk_zscore.py` cluster tests pass;
- L2-MNE payload metadata remains backward compatible;
- no renderer or GUI behavior changes.

### Slice 2: eLORETA Volume Model Spike

- Add a producer-local eLORETA volume model builder.
- Create a minimal source-ready fixture or mocked model path that emits a
  valid `volume_points` prepared payload.
- Confirm the importer and transparent mesh renderer can display the payload.
- Record eLORETA inverse settings and volume source-space metadata.

Done means:

- a synthetic or fixture-backed eLORETA volume payload validates;
- no retired Source Localization code is imported or consulted;
- renderer changes are limited to method-neutral payload/mask handling if
  needed.

### Slice 3: Participant-First eLORETA Volume Z-Score Export

- Reuse the existing project FullFFT input assembler.
- Estimate participant target and neighboring-bin topographies through the
  eLORETA volume model.
- Compute participant source z-scores.
- Emit raw mean, median, and 20% trimmed mean group payloads.
- Emit a participant sidecar analogous to the L2-MNE sidecar.

Done means:

- project-local eLORETA volume outputs are written under
  `6 - Source Localization/eLORETA Volume Beta/`;
- the prepared manifest loads through the existing importer;
- payload values remain signed z-scores.

### Slice 4: Volume Cluster Mask

- Build volume adjacency from the MNE volume source space.
- Run the shared sign-flip max-cluster-mass test on participant eLORETA
  z-score maps.
- Store method-neutral mask metadata and retained source indices.
- Add tests for volume adjacency conversion and mask application.

Done means:

- eLORETA volume payloads include producer-computed cluster-mask metadata;
- disabling the mask produces exploratory display only;
- empty and underpowered mask status text remains clear.

### Slice 5: GUI Source Method Selector

- Add a compact method selector to the LORETA Visualizer toolbar.
- Group loaded manifest entries by source method, condition, and summary.
- Keep each condition shown once per selected method.
- Default eLORETA volume to transparent mesh display.
- Disable incompatible display modes for volume payloads.

Done means:

- users can switch between L2-MNE surface and eLORETA volume when both are
  loaded/generated;
- condition and summary selectors remain clean;
- the GUI does not compute source values.

### Slice 6: Reports, Docs, And Validation

- Extend source validation reports to summarize eLORETA method settings, source
  grid, cluster-mask coverage, participant inclusion, and beta limitations.
- Add user-facing docs under Tools > Source Estimation once the method exists.
- Update tool-local architecture docs if file responsibilities or method
  boundaries change during implementation.
- Add a visible/manual smoke path for method switching and transparent volume
  rendering.

Done means:

- users can understand what eLORETA volume maps represent;
- validation artifacts clearly warn against overinterpreting precise deep
  localization;
- agent docs match the implemented structure.

## Risks And Open Decisions

- Volume source-space resolution affects runtime, memory, and statistical
  sensitivity. Start conservatively and record grid spacing in metadata.
- eLORETA maps are expected to be spatially smooth and diffuse. The cluster
  mask controls group-level familywise error over the chosen source grid, but
  it does not make source localization anatomically precise.
- Template fsaverage EEG source localization is not subject-specific source
  modeling. Subject-specific MRI/BEM support requires a separate branch.
- The current L2-MNE lateralization summaries rely on cortical hemisphere
  labels and Desikan-Killiany surface labels. eLORETA volume lateralization
  should not reuse those assumptions blindly. A volume ROI/laterality extension
  should be separately scoped.
- Figure export for eLORETA volume is intentionally deferred until the
  visualization and mask semantics are validated.
- Project-local inverse-model caching from the performance plan should be
  considered before full eLORETA runs become expensive, but cache signatures
  must include method, source-space kind, spacing, inverse settings, MNE
  version, channel order, and template identity.

## Verification

Use the local repo environment. This checkout currently has `.venv`; if a
future checkout has `.venv1`, use that instead.

Focused checks for implementation slices:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src\Tools\LORETA_Visualizer
.\.venv\Scripts\python.exe -m pytest tests\loreta -q
.\.venv\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
.\.venv\Scripts\ruff.exe check src\Tools\LORETA_Visualizer tests\loreta
```

For GUI slices, also run:

```powershell
.\.venv\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
```

Do not run offscreen Qt workflows locally. Document a visible/manual smoke path
instead:

1. Launch the app visibly.
2. Open the LORETA Visualizer from a processed project.
3. Generate or load L2-MNE surface maps.
4. Generate or load eLORETA volume maps.
5. Switch source method and confirm condition/summary selectors stay clean.
6. Confirm L2-MNE defaults to Split Hemispheres.
7. Confirm eLORETA defaults to Transparent brain mesh.
8. Toggle the cluster mask on and off and confirm status text distinguishes
   producer-masked display from exploratory unmasked display.

## Boundary Checklist

- `src/Tools/SourceLocalization/**` remains unused and unmodified.
- `src/quarantine/**` remains unused.
- `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` are not
  recreated.
- Source estimation code stays in
  `src/Tools/LORETA_Visualizer/source_producers/`.
- Renderer/importer/bridge helpers consume prepared payloads only.
- Project input readers remain read-only except for explicit project-local
  source-map output writes.
- Existing L2-MNE surface payloads, masks, and figure exports remain backward
  compatible.
