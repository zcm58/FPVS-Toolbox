# Test Selection

Use `.agents/verification.toml` as the executable scope registry and
`tests/qt_test_files.txt` as the Qt registry. The driver selects `.venv1` or
`.venv` and combines audits, lint, compilation, and tests:

```console
python .agents/scripts/verify.py --scope <scope> --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

Start with the affected feature. Precommit runs all invariants, changed Python
checks, bounded repo tests, and changed non-Qt test files; it does not infer
feature scopes or launch the full suite. Use `--list` to inspect commands and
`--check-config` after changing the registries. Do not duplicate pytest lists
in prose. [Verification gates](verification-gates.md) owns docs-only checks,
CI details, and failure reporting.

## Qt Execution Boundary

PySide6/pytest-qt execution is CI-only unless the user explicitly approves a
safe visible environment. Never set `QT_QPA_PLATFORM=offscreen` or launch
ad-hoc offscreen Qt locally; these can hang indefinitely. Filenames and markers
alone do not establish safety: the registry controls local selection.

GUI changes require local non-GUI checks, current CI coverage definitions, and
a documented visible/manual smoke path. Precommit excludes registered Qt tests
even when the Qt opt-in environment is set.

## Scope Map

| Scope | Local focused coverage | CI Qt / visible coverage |
| --- | --- | --- |
| `repo` | Verification/audit contracts; precommit adds all audits and changed-file checks | Full application suite remains in CI |
| `backend-hardening` | Imports, settings/persistence, transaction recovery, runner lifecycle, exact spectral reads, source-model caches | None in this bundle |
| `gui` | Import/static checks and non-window state contracts | Windows, dialogs, settings, menus, embedded pages |
| `updates` | Release selection, download/install backend, packaging syntax | Update dialog/manager and Windows installer smoke |
| `project-io` | Settings, acquisition/BIDS, discovery, paths, manifests, exact XLSX reads | File dialogs/project workflows |
| `processing` | MNE admission, order/fingerprints, QC, persistence, crop, runner/exports | Processing-window wiring and workers |
| `pipeline-methods` | Slot replacements, selections/default identity, review/checkpoint/repair, exports, synthetic hardware matrix | Settings save/cancel and worker snapshots |
| `pipeline-setup` | Detached setup draft, project settings, freshness, protocol and static launch workflow | Guided dialog navigation, save/cancel, guards and fit |
| `plot-generator` | Config/data helpers, aggregation, FFT/SNR, rendering/exports | Plot Generator page/workflow |
| `publication-maps` | Harmonics, BCA/SNR rendering, paired/group figures, colorbars | Scalp Maps page |
| `sequence-figure` | Renderer and high-DPI outputs | Sequence Figure wiring |
| `sensitivity-analysis` | Power/design-sensitivity math, simulation/search, cancellation, uncertainty | Inputs, worker, results/reset, information tabs, fit |
| `stats` | Project/data context, pipeline, DV/harmonics, FullSNR, exports/reporting | Stats layout/focus/workflow |
| `free-harmonic-clustering` | FullFFT reads, preparation/adjacency, permutations, exports, static GUI contracts | Prepare/run/cancel/results/folder actions |
| `loreta` | Payloads, source producers, exports, rendering helpers, legacy boundaries | Visualizer/Qt workers |
| `figures` | Shared figure-style and render/export contracts | Relevant export dialogs |
| `legacy-boundary` | Retired-package audits and compatibility | None by default |

## Selection Rules

- Add a second scope when a shared boundary changes. Shared harmonic selection
  needs `publication-maps` and `stats`; shared figure styles need `figures`
  plus the affected tool. Guided setup needs `pipeline-setup` and `gui`.
- Put regression tests beside their owning workflow; register Qt dependencies
  before relying on local scope results. Precommit includes changed non-Qt test
  files even outside a focused bundle, skips helpers/deletions, and avoids
  rerunning files already covered in that invocation.
- File/project tests use isolated temporary paths, never developer data.
- Routine tests and Ruff exclude opt-in `src/Standalone_Scripts` and
  `tests/standalone_scripts`; do not collect that suite without explicit scope
  or approval and its scoped instructions. Stats remains in active lint.
- Scientific calibration and real-data diagnostics require their separate
  protocol/scope; focused synthetic tests do not replace qualification.

## Maintaining Older Tests

Keep scientific baselines, historical schemas, compatibility-alias identity,
and retirement guards. A legacy name alone is not grounds for removal.
Ordinary tests use current owners; compatibility tests alone exercise aliases.

Remove obsolete symbol-only checks only when behavioral tests cover the same
contract. Update mocks at the public boundary rather than weakening assertions.
A supported import failure is a regression, not a reason to catch every import
error and skip. Split backend/Qt tests where practical and update both registries.

## Hardware and Studio Extension Coverage

The [roadmap](../architecture/hardware-pipeline-studio-roadmap.md) separates the
four implemented acquisition routes from remaining hardware/Studio work.
Extensions need relevant admission, pipeline, cache/provenance, and downstream
coverage. Inspection fixtures do not establish production or physical
qualification; keep timing/laboratory evidence distinct from synthetic tests.

## Retired Source Localization Package

Do not restore `Tools.SourceLocalization`, its tests/shims, or bundled fsaverage.
The current `Tools.LORETA_Visualizer` and isolated `source_producers` have
supported `loreta` coverage; their existing L2-MNE/eLORETA tests are not retired.
Preserve renderer/calculation separation and the ignored root `.fpvs_cache`.
