# FHC Harmonic Cluster Maps

## Status

Implementation and local non-GUI validation complete. CI Qt execution and the
visible manual acceptance path below remain pending under the repository's
local Qt policy.

## Scope

Implement the user-requested descriptive FHC maps on
`codex/fhc-harmonic-cluster-maps`. Presentation follows Hermann, Ching and
Stothart (2026), Figures 7 and 10, DOI `10.1111/psyp.70361`: harmonic-specific
mean response differences with discrete signed significant-cluster markers.
The Toolbox's attributed ROI-selector BioSemi64 geometry is reused. No author
MATLAB code or layout files are consumed.

## Decisions

- Numerical preparation, harmonic selection, graph, permutation tests, and
  cluster p-values remain unchanged.
- Read-only display snapshots retain sensor x harmonic mean differences and
  original membership, never participant or permutation tensors.
- Piecewise-linear response interpolation is explicitly descriptive, bounded
  by the electrode hull/scalp, and never applied to significance.
- One symmetric color scale spans all retained harmonics per contrast.
- Analysis stays on its own tab; Cluster maps provides run, cluster, and
  harmonic navigation without page scrolling at 1280x900.
- Completed atomic run bundles include all retained harmonics as numbered
  600-DPI PNG/single-page PDF pairs with map values and external captions.
- Repeated-session condition/family identity and run-level Holm values remain
  explicit, distinct from raw within-run cluster p-values.

## Verification and manual acceptance

Local gates: focused `figures` and `free-harmonic-clustering`, then `repo`
precommit through `.agents/scripts/verify.py`. New headless tests exercise
exact membership, channel order/orientation, paired numerical precision,
shared scales, empty results, atomic export failure/cancellation, and batch
context. GUI smoke definitions are registered for CI. Never execute Qt or
offscreen GUI workflows locally without the required visible-session approval.

Visible manual path: open FHC at 1280x900; run a flat contrast, select a
cluster row and View cluster maps; switch harmonics and confirm changing
membership with fixed color limits and unchanged raw p. Enable electrode
names, inspect all analyzed harmonics, and inspect a no-significant-cluster
run. Repeat with a batch, changing condition/family and checking Holm context.
Change setup/project and confirm all old maps clear. Cancel during export
and verify no completed partial bundle exists. Inspect paired PNG/PDF files
and their metadata from Open Results Folder. Confirm no page-level scrollbar,
clipping, or unresponsive controls.

Initial GUI import audit passed. The initial path audit found eight existing
developer paths in unrelated untracked `outputs/rcads-*` files. Those files
are outside this feature and remain untouched.

Final local results:

- `.venv/Scripts/python.exe -m pytest tests/free_harmonic_clustering
  tests/project_io/test_main_app_xlsx_selected_reader.py
  tests/audit/test_figure_style_contract.py -q`: **265 passed**.
- Ruff over the FHC package, FHC tests, changed GUI tests and shared figure
  contract: passed. Compilation of the FHC package and changed GUI tests:
  passed. `verify.py --check-config`: passed (15 scopes).
- `verify.py --scope figures --tier focused`,
  `verify.py --scope free-harmonic-clustering --tier focused`, and
  `verify.py --scope repo --tier precommit`: each stopped at the same eight
  pre-existing path-audit findings above. Their focused non-GUI test targets
  were run directly as recorded above; the full precommit gate is not a pass.
- `git diff --check`: passed. Headless synthetic PNGs were visually inspected
  for single-harmonic long labels and a 13-harmonic two-figure export. Real
  600-DPI PNG and single-page PDF output is covered by the renderer tests.
- Registered CI-only `test_free_harmonic_clustering_map_view.py` covers exact
  slice navigation, negative IDs, empty slices/results, batch context and
  reset. Existing page tests cover table-to-map selection, project reset,
  and preserving committed success when an interactive-preview build fails.
  Neither Qt tests nor manual GUI acceptance were executed locally.

## Changed files

Runtime under `src/Tools/Free_Harmonic_Clustering/`:
`visualization.py`, `render_cluster_maps.py`, `exports.py`, `api.py`,
`tool_info.py`, `gui/cluster_map_view.py`, `gui/page.py`, `gui/workers.py`,
`gui/models.py`, and `gui/backend_adapter.py`.

Tests: `tests/free_harmonic_clustering/test_visualization.py`,
`tests/free_harmonic_clustering/test_cluster_map_rendering.py`,
`tests/free_harmonic_clustering/test_exports.py`,
`tests/free_harmonic_clustering/test_repeated_session_batch_inference.py`,
`tests/free_harmonic_clustering/test_api.py`,
`tests/gui/test_free_harmonic_clustering_map_view.py`,
`tests/gui/test_free_harmonic_clustering_page.py`,
`tests/audit/test_figure_style_contract.py`, and `tests/qt_test_files.txt`.

Documentation: this plan, `src/Tools/Free_Harmonic_Clustering/AGENTS.md`,
`src/Tools/Free_Harmonic_Clustering/ARCHITECTURE.md`,
`src/Tools/Free_Harmonic_Clustering/README.md`, and
`docs/user/tools/free-harmonic-clustering.md`.
