# BIDS import and shared MNE pipeline

Branch: `codex/bids-shared-pipeline`. Numerical baseline: `da14edaa`.

Status: initial BIDS implementation and synthetic acceptance completed on
2026-10-19. The same-day follow-up moves remaining hardware interpretation
upstream; its scoped numerical acceptance is complete. Visible workflow/release acceptance
remains separate.

## Generic processing follow-up

The maintainer explicitly requested completion of the hardware boundary:
processing must consume generic recording metadata and project methods, with
manufacturer/format interpretation owned by acquisition adapters. Merely
renaming brand-specific helpers or moving numerical algorithms into I/O does
not satisfy this requirement. Preserve scientific profiles, qualification
gates, exact output/identity bytes, filtering order and all prior working-tree
changes.

- [x] Freeze a generic recording contract upstream with channel roles/order,
  geometry, reference, trigger semantics, qualified capabilities and opaque
  compatibility provenance.
- [x] Migrate preprocessing, runner, preflight/review and provenance consumers
  to that contract; retain historical imports only as compatibility adapters.
- [x] Prove the numerical entry can consume explicit generic metadata without
  resolving a hardware brand; enforce the boundary with focused tests.
- [x] Run relevant non-GUI regressions and repeat the five-participant old/new
  synthetic comparison with all optional QC off, timing import separately.
- [x] Update the conceptual map, ownership docs and exact acceptance receipt.

Existing montage-calibrated methods remain qualified only for their declared
geometry/profile. This work neither changes thresholds nor enables those
methods for a new montage. ROI preset libraries and secondary spatial tools
remain separately qualified consumers; their named scientific presets are not
native-reader or manufacturer dispatch in the shared processing engine.

The [follow-up receipt](../../../../scripts/manual_diagnostics/receipts/generic_pipeline_equivalence_20261019.json)
records the final refactor against the same pre-BIDS baseline, `da14edaa`:
all **30 scientific output files are byte-identical**, all **415 arrays /
5,375,645 numeric values** match exactly, and the maximum difference is **0.0**.
The five diagnostic logs match after timestamp/PID normalization. All five
native BDF copies, imported samples, events, channels and processing audits
match. Every optional QC method was off.

Fresh conversion took **0.847106 s** across five participants; complete import
preparation took **1.458482 s**. Processing took **24.511544 s** on the original
pipeline and **24.524832 s** after the generic-contract refactor, excluding
initial import. The latter plus full import preparation totals **25.983314 s**.
These are local measurements with OS disk caches intact, not a speed claim.
The earlier receipt below is retained as historical evidence for the initial
BIDS layer rather than overwritten by this follow-up.

`tests/processing/test_generic_recording_pipeline.py` additionally runs the
actual engine with arbitrary EEG/reference labels and a custom trigger channel,
an explicit immutable contract, and no hardware project key. Hardware and
acquisition resolvers are patched to fail. Both the reference-only and
FIR/downsample paths match independently computed MNE arrays and marker events
exactly. Static checks protect manufacturer-free imports in the shared engine,
reference operation, preflight, review scanner and runner. Focused regressions
also cover Brain Products exports, event alignment, fingerprints, calibrated
kurtosis evidence, cache cold/warm parity and unknown-dataclass rejection.
No repository-wide scientific suite or local Qt workflow was run.

## Authorized scope

Import supported acquisition files into a project-local BIDS representation,
resolve their recording metadata and processing policy, and feed the shared MNE
pipeline. Preserve existing BioSemi and Brain Products numerical behavior,
processing order, output formats, and scientific qualification gates. Update
the conceptual map and agent contracts to distinguish implemented behavior from
future hardware support. Original recordings remain unchanged.

The maintainer requested a quick, scoped check instead of repository-wide tests:
five synthetic BioSemi ActiveTwo participants, every optional QC feature off,
old and new full numerical/export paths compared, and BDF-to-BIDS conversion
time measured separately. Scientific arrays and exported contents must be
compared; timestamps, paths, and container metadata must be reported separately.
No local Qt execution or laboratory hardware qualification is part of this check.

## Work and acceptance

- [x] Preserve the old commit and create a new feature branch.
- [x] Run narrow path, protected-boundary, and GUI import audits.
- [x] Add BIDS preparation, identity validation, and MNE loading.
- [x] Route full/lazy/prefetch production reads through the shared import boundary.
- [x] Resolve acquisition differences before common numerical stages.
- [x] Preserve exact values and event semantics for each existing input route.
- [x] Run focused adapter checks and five-participant old/new comparison.
- [x] Record conversion timings, output comparisons, and limitations.
- [x] Update architecture and agent guidance; keep conceptual-map copies aligned.

The canonical project root comes from the active project or explicit worker
settings. BIDS imports and their receipts belong beneath that root. Cache
identity includes source companions and import metadata. A cache hit must not
silently reuse changed sources or a mismatched acquisition configuration.

## Implementation boundaries

`io.bids_import` publishes immutable per-recording datasets under the active
project's `.fpvs_cache/bids-import/`; `io.bids_loader` supplies project context
and MNE loading. BDF files and BrainVision signal payloads remain byte-exact.
BVRF calibration can produce float64 values that cannot survive a standard
BrainVision float32 export, so that route explicitly uses a lossless FIF64
derivative with preserved source companions. It is not standard raw EEG-BIDS.

`io.acquisition_metadata` resolves project reference, channel order, geometry,
event semantics and capability gates into `io.recording_contract.RecordingContract`;
`io.geometry_metadata` owns configured/source geometry identities for provenance.
The shared numerical operations live in `processing.preprocess` and
`processing.reference`, with calibrated QC formulas remaining in processing
and consuming upstream profile metadata. `processing.acquisition_policy` only
preserves historical imports. Existing methods and fingerprint bytes
remain unchanged. Resource planning retains a bounded native-header-only
reader before admission; it cannot perform processing or publish imports.

## Recorded comparison

The [portable receipt](../../../../scripts/manual_diagnostics/receipts/bids_pipeline_equivalence_20261019.json)
records five distinct synthetic BioSemi ActiveTwo-style BDFs, each 80 seconds
at 2048 Hz with 64 scalp channels, EXG1, EXG2, and Status. Each recording is
32,949,248 bytes. All optional QC, interpolation, and line-noise correction
were disabled. Both runs used EXG-pair reference/drop, 1–40 Hz FIR filtering,
128 Hz downsampling, final average reference, and identical spectral exports.
The old run used the isolated baseline commit; the new run used this branch.

- All 30 scientific output files were byte-for-byte identical: five `.fpvs`
  manifests, ten spectral/metric NPZs, five source-ready FIFs, and ten source
  JSON/manifests.
- All 415 arrays and 5,375,645 numeric values matched exactly; maximum absolute
  difference was `0.0`. Samples, events, channel identities, and processing
  audits matched. The five diagnostic logs matched after timestamp/PID
  normalization. Original/copied BDF bytes matched for every participant.
- Measured BIDS conversion totaled **0.961151 s**; complete preparation,
  including integrity checks and initialization, totaled **1.364107 s**.
  Per-participant conversion was 0.339759, 0.154074, 0.160363, 0.156938,
  and 0.150017 seconds.
- Processing totaled **24.948459 s** for the old pipeline and **25.561597 s**
  for the new one, excluding the explicitly timed initial conversion.

This is a fresh import-cache measurement on this machine; the OS disk cache
was not flushed. It is not a general performance claim or physical hardware
qualification. QC-enabled behavior, group Stats, installer packaging, and GUI
workflows were outside the requested comparison. Generated BDFs and full local
receipts remain ignored; only synthetic metadata and the portable receipt are
tracked.

Reproduce with a fresh work directory:

```console
python scripts/manual_diagnostics/compare_bids_pipeline.py --baseline-ref da14edaa --work-dir .codex-tmp/bids-pipeline-comparison-NEW
```

## Focused verification and visible smoke path

The maintainer explicitly excluded old/broad repository suites. Verification
used only the new import/policy/lifecycle tests, current Brain Products
integration/export and prefetch cases, bounded resource-header checks, locked
processing-order/fingerprint checks, scoped static audits, and the comparison
above. No Qt execution or broad repository suite was run.

Current Brain Products processing/export and prefetch selection:

```console
python -m pytest -q tests/processing/test_brain_products_integration.py -k "real_recording_to_spectral_export or prefetch"
```

Result: **10 passed, 2 deselected**. Adapter checks exercise exact BDF/BVCDF/BVRF
samples and markers, BVRF nonlinear calibration and geometry, cache corruption
and source invalidation, concurrent publication, and owned memory-map cleanup.
The directory-symlink containment case is skipped when Windows disallows
creating that fixture.

Final adapter result: **12 passed, 1 skipped**. Eleven bounded header checks
and twelve policy/lifecycle checks also passed. Changed-file Ruff and Python
compilation, `git diff --check`, strict MkDocs build, and conceptual-map copy
consistency passed. Final reader-version cache invalidation and Windows path
normalization fixes do not alter samples or numerical processing.

For later visible acceptance, open a BioSemi project, process a small recording
with QC off, reopen it, and confirm cache reuse and unchanged result discovery.
Repeat with a confirmed Brain Products project and its recorded/template
geometry. Check that inspection, prefetch, and processing remain responsive,
and that imports stay under each active project. This manual path has not been
executed during the scoped numerical check.
