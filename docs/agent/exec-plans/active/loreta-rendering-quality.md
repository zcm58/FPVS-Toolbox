# LORETA rendering quality and cost

Status: rendering implementation and continuous MRI dragging complete with
scoped visible Windows review and automated source verification, 2026-11-04.
User authorized visible Toolbox inspection.
Preserve unrelated worktree changes. Cross-platform graphics and final-source Qt
CI remain separate acceptance. The volume-backdrop follow-up is complete below.

## Boundaries and resume

- Renderer/display only: no inverse, statistical, harmonic, payload-value or
  anatomical-coordinate changes. Preserve missing support and shared scales.
- Use cached fsaverage and synthetic prepared data for visible review. Never
  fetch templates or process private projects for this task. No offscreen Qt.
- Parent owns GUI integration, visible review and docs; renderer owner handles
  actors/materials; MRI owner handles volume sampling/layout. Coordinate edits.
- On resume read this ledger and current diff. Reuse completed checks; renew the
  task-owned keep-awake request from context, never store credentials here.

## Checkpoints

| ID | State | Work and acceptance |
| --- | --- | --- |
| R0 | Complete | Baseline 554 tests passed; actual Toolbox page inspected visibly with synthetic surface/volume payloads and cached anatomy. Primary sources below reviewed. |
| R1 | Complete | Cached actors/normals, no idle redraw, guarded FXAA, neutral matte lighting, isometric volume entry/reset. Full geometry retained; visible rotation/volume review and independent transform parity passed. |
| R2 | Complete | Native T1/brain fallback, shared window/FOV, responsive layout, original-support Gaussian width and missing-source alpha. Native coordinate probes and paired export review passed. |
| R3 | Complete | Viewport/DPR budget, anatomy reuse and debounced resize; visible compact/wide navigation and isometric volume review; LORETA 588, GUI 721, figures 4, repo 543 / 1 skipped; strict docs and focused links pass. |

R1 acceptance: rotations do not rebuild actor geometry/normals; no-op setters do
not render; idle preview does not continuously redraw. Viewports retain proper
curvature, mask state, colors and rotation/reset behavior. Avoid expensive SSAO,
shadows, ray tracing and extra mesh smoothing. Decimation is optional only if
measured cost still warrants it; preserve native projection identity and exports.

R2 acceptance: one anatomical grayscale range across planes/conditions; affine
orientation and aspect ratios remain correct; stable field of view; sparse-mask
overlays retain original-grid scale. Native template is an averaged atlas and
cannot provide invented individual-MRI detail. Preview and export share display
rules while retaining publication typography and paired 600-dpi PNG/PDF output.
Use existing native `T1.mgz` full-head anatomy, with `brain.mgz` fallback; both
must use their recorded tkregister affine. Preserve old generated 0.5 mm caches
but do not use them for normal loading. Compact previews use a 2×2 arrangement;
wide previews and publication exports retain three planes in a row.

R3 acceptance: visibly inspect split/combined/volume/MRI modes, rotation/reset,
mask and scale changes, original-grid inspection and missing regions. Exercise
rapid MRI navigation and resizing. Record observed render costs with the local
environment; do not claim general GPU benchmarks. Use synthetic visible probes
under `.codex-tmp/`; durable manual probes belong in `scripts/manual_diagnostics/`.

## Continuous MRI drag follow-up

Requested behavior: dragging within one MRI panel moves its crosshair immediately
and updates the other two planes during the gesture. Preserve native affine
geometry, source values/support, masks, shared scale and publication exports.

- D0 complete: GUI/protected audits passed; existing click/navigation and single
  coalescing worker inspected. Prior edits and concurrent Home work preserved.
- D1 complete: widget captures the originating plane, clamps drag positions,
  suppresses duplicate voxels, ends on release/focus loss/hide/clear and preserves
  the current pointer when an older compatible render completes.
- D2 complete: accept progressive frames only within the same display context;
  keep one worker and latest pending coordinate, reject stale contexts, and settle
  on the final release coordinate. Reuse the current scale during navigation.
- D3 complete: native preview cache, safe/CI smoke definitions and visible
  synthetic dragging complete. LORETA 717, GUI 768 and repository 946 / 1 skipped
  passed; invariant audits, strict MkDocs, scoped links/owners and diff checks pass.

Drag evidence (Windows, native cached fsaverage T1, synthetic prepared values):

- Visible gestures exercised all three panels, fixed-plane clamping, release,
  Home and wheel navigation; closure produced no errors. A 5.369-second gesture
  requested 444 coordinates and displayed 36 intermediate frames; 35 kept a
  newer pointer than the completed image. The final frame matched the endpoint.
- Alternating paired renders with 1,837 sources at 900×750 pixels reduced median
  frame time by about 40% over 16 pairs. Initial cached frames took 104–108 ms
  versus 164–179 ms fresh; concurrent load increased both. This is a local
  measurement, not a hardware-independent frame-rate guarantee.
- Preview reuse retains one Agg canvas and at most 16 panels/16 MiB. Numerical
  tests verify exact cached/fresh RGB, hit geometry, missing-source transparency
  and context invalidation. Exports and native resolution are unchanged.
- Widget/controller tests cover progressive frames, stale success/error,
  pre-gesture request rejection, cancellation and final settling. Additional
  interactions remain registered in the existing Qt CI files; no local Qt tests
  or cross-platform graphics acceptance are claimed.

Resume from these checkpoints and the current diff. Widget owner is
`slice_viewer.py`; orchestration is `gui.py`; numerical display preparation stays
in `volume_slices.py`. No inverse, processing or new statistical work is scoped.
Use cached fsaverage plus synthetic prepared data for local review. Keep task
keep-awake credentials in context only; no offscreen Qt or private-project reads.

## 3D volume anatomy follow-up

Requested behavior: detailed fsaverage pial anatomy is the default translucent
3D volume backdrop; a Display option selects the smooth whole-brain shell.

- B0 complete: GUI/protected audits and LORETA baseline (717 tests) passed.
- B1 complete: renderer swaps only the anatomy actor, preserving source
  payload/support, overlay geometry/scalars, masks, limits and user camera.
- B2 complete: session-only Display option applies to both comparison panes
  and later-created renderers; unrelated options must not trigger a refresh.
- B3 complete: LORETA 728, GUI 768 and repository 391 / 1 skipped passed;
  invariant audits, strict MkDocs and diff checks passed. Scoped Windows visible
  review verified detailed default, shell option, retained rotation and comparison
  inheritance. Before/after captures were identical for payload points/values/
  metadata, overlay points/faces/scalars/actor identity, color limits and camera;
  only backdrop selection changed. Native Qt interaction definitions remain in
  the registered source-options file for CI; no cross-platform acceptance claimed.

Changed owners: `renderer.py`, `gui.py`; safe regressions in
`test_renderer_updates.py`, `test_volume_overlay.py`, `test_volume_anatomy_gui.py`,
and CI smoke in `tests/gui/test_loreta_source_options_qt.py`. Tool rules,
architecture, user guide and validation notes own the durable behavior.

No producer, inverse, statistical, file-format or source-cache changes are scoped.
Existing MRI and cortical source views keep their behavior. Missing optional
shell anatomy falls back to pial context without removing source points.

## Published guidance

- [NVIDIA FXAA](https://developer.download.nvidia.com/assets/gamedev/files/sdk/11/FXAA_WhitePaper.pdf)
  and [PyVista anti-aliasing](https://docs.pyvista.org/api/plotting/_autosummary/pyvista.plotter.enable_anti_aliasing):
  inexpensive edge treatment, with possible fine-detail softening.
- [PyVista lighting](https://docs.pyvista.org/examples/04-lights/plotter_lighting.html):
  controlled key/fill lighting and material response.
- [Freeview window/level](https://surfer.nmr.mgh.harvard.edu/fswiki/FreeviewGuide/FreeviewGeneralUsage/FreeviewInterface)
  and [FreeSurfer coordinates](https://surfer.nmr.mgh.harvard.edu/fswiki/CoordinateSystems):
  faithful MRI contrast and orientation.
- [NiBabel resampling](https://nipy.org/nibabel/reference/nibabel.processing.html#resample-from-to):
  physical affine-aware sampling, not increased anatomical resolution.

## Ledger

- R0: identified repeated split-mesh actor/normal construction, excessive MRI
  preview resampling and selected-point-dependent Gaussian width. Baseline
  anatomy-only image retained under `.codex-tmp/` for visual comparison.
- Visible baseline measurement: 25 unsolicited renders in 5.00 seconds idle;
  five split-rotation calls averaged 239.3 ms and four range updates 235.7 ms.
  These are local synthetic call costs, not general GPU benchmarks. The native
  T1 underlay has 16 MiB of voxel data versus 128 MiB in the old 0.5 mm display cache.
- R1: updated visible runs produced 0 idle redraws; rotation means 42.7 and
  39.6 ms, range-update means 76.8 and 66.6 ms. Do not claim lower total CPU
  consumption from these observations. Volume entry/reset now uses isometric
  framing; same-mode changes preserve user camera/zoom, and spin keeps ownership.
- R2: 46 focused MRI checks passed. Independent review covered 144 panels across
  48 signed axis permutations with anisotropic voxels, physical aspect and missing
  holes. Native T1/brain tkregister transforms match. Paired synthetic MRI export
  visually checked as PNG and rendered PDF: 3307×1920 pixels at 600 dpi, one-page
  PDF, 140×81.28 mm, three equal row panels, missing sources transparent.
- R3: visible resize exposed old-layout retention; a 180 ms debounce now reuses
  current cursor/range/anatomy through the existing coalescing worker. Hidden,
  closing and unchanged-size cases skip work. Final source gates: LORETA 588,
  GUI static 721, figures 4, repository 543 passed / 1 skipped. Native Qt smoke
  definitions remain registered for CI; local review used visible synthetic data.
- Final visible reload confirmed isometric volume framing and automatic grid-to-row
  MRI reflow on maximize, retaining x/y/z coordinates and scalar range. No renderer
  errors appeared. Independent geometry/coordinate reviews found no regression.
  Test/measurement fixtures and paired export receipts remain in ignored
  `.codex-tmp/`; this plan and the validation guide preserve the durable findings.
