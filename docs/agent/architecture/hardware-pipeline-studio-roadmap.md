# Hardware, Processing, and FPVS Studio Direction

Status: maintainer-directed product and architecture goals, updated 2026-10-19 for the Brain Products feature branch.
This page separates the current implementation from the intended future state.
It guides scoped implementation plans; it does not enable new hardware or change
scientific methods by itself. Read it when changing acquisition, montages,
processing composition, project import, or Studio interoperability.

## Current implementation

| Area | Implemented boundary | Still to do |
| --- | --- | --- |
| Production acquisition | BioSemi BDF retains its validated 64-channel contract. Confirmed Brain Products projects use BrainVision adapters and recording-owned channel geometry. | Validate representative laboratory recordings and visible acceptance before release; qualify additional montage-specific tools separately. |
| Acquisition definitions | `Main_App.io.acquisition_profiles` separates versioned format, device acquisition, montage, event decoding, and capabilities in an immutable registry. | Make the resolved contract drive production loading, processing, QC, GUI availability, and downstream tools consistently. |
| Unicorn | Read-only BDF/BDF+ inspection, explicit channel/unit/event policies, and a context-owned lazy/RAM/memmap MNE reader exist. Results retain `scientific_processing_allowed=False`. | Complete the [Unicorn plan](../exec-plans/active/unicorn-hybrid-black-support.md), including unresolved acquisition evidence and production integration. A readable recording is not scientific qualification. |
| Brain Products | Shared discovery/loading/preflight/pipeline/export routes accept BVCDF and single-participant BVRF 1.0.0. Project hardware, reference, channel roles, and selected montage persist. See [scope and sources](../../user/reference/brain-products.md). | Historical formats, multi-participant BVRF splitting, hardware gain/latency qualification, and BioSemi-specific statistical/spatial capability qualification remain separate work. |
| Processing | `Main_App.processing.preprocess` keeps the shared numerical stages and locked BioSemi baseline. `acquisition_policy` supplies the versioned Brain Products reference/retained-channel/QC policy. | Broader registry-driven stage composition remains a goal; the current policy boundary is not an arbitrary pipeline editor. |
| Studio project import | `Main_App.projects.fpvs_config_import` accepts `.fpvsconfig` schemas 1.0.0–1.8.0 for FPVS Oddball and Cognitive Load FPVS, importing the Toolbox-owned project/protocol/marker and optional removed-electrode subset. | Verify complete field and workflow coverage against explicitly identified Studio versions and real, sanitized exports. Current import is not complete Studio compatibility. |
| Studio acquisition evidence | `Main_App.io.studio_acquisition_evidence` validates a candidate handoff and compares ordered trigger codes only after reviewed recording association. | Qualify receiver integration, recording identity, acquisition facts, and timing semantics. Code agreement alone does not prove sample timing or recording completeness. |
| Updates | The independent updater uses ported Studio design/contracts with Toolbox-specific application and installer identities. | Maintain versioned protocol parity where intended. Updater similarity does not establish experiment/data interoperability. |

The Brain Products runtime policy uses `projects.hardware`,
`processing.acquisition_policy`, and `io.recorded_eeg_geometry`. The immutable
`io.acquisition_profiles` registry still owns the separate BioSemi/Unicorn
inspection contracts; do not assume it resolves dynamic recording montages.

Evidence owners: [EEG loading](eeg-loading-contract.md),
[preprocessing](preprocessing-contract.md), [project I/O](project-io.md),
[updater](updater.md), and the corresponding `tests/project_io/`,
`tests/processing/`, and `tests/updates/` coverage. These describe the working
source tree; a release tag and its acceptance receipt define shipped behavior.

## Target: modular hardware and montages

Support different acquisition systems and electrode layouts through shared,
explicit contracts. Hardware identity, file format, montage geometry, channel
label mapping, reference policy, and trigger decoding are separate concerns.
Do not infer one from a filename, channel count, or another device's defaults.

Extend the existing registry and canonical owners before creating parallel
device-specific pipelines. A supported combination must declare its units,
sampling constraints, channel roles/order, geometry source and coordinate frame,
event authority, reference policy, and available capabilities. Device-specific
unit corrections and reader workarounds stay in focused I/O adapters.

New montage support must reach the complete workflow: project persistence,
full/lazy/prefetch reads, QC, prepared-state/cache validation, processing,
exports, ROI selection, plotting, and applicable downstream tools. Spatial
interpolation, sensor adjacency, source estimation, and montage-specific QC
thresholds need their own evidence. A generic channel list must not silently
enable a BioSemi64-only spatial method on another montage. Mixed acquisitions
within one project require explicit compatibility rules and recording-level
identity; their scientific comparability must not be assumed.

### Required Brain Products support

The maintainer wants broad Brain Products support and has not specified an
amplifier, cap, channel count, reference, or Recorder version. Do not select one
by assumption or require the user to know the model before planning the shared
architecture. Detect documented format/acquisition metadata where available;
request explicit montage/reference information only where it cannot be established.

The format inventory must cover BrainVision Core/Data Exchange recordings
(`.vhdr`, `.vmrk`, `.eeg`) and BrainVision Recording Format (BVRF: `.bvrh`,
`.bvrm`, `.bvrd`, optional `.bvri`), then assess documented legacy variants.
The vendor's [Core Data Format specification](https://www.brainproducts.com/download/specification-of-brainvision-core-data-format-1-0/)
and [BVRF documentation](https://www.brainproducts.com/support-resources/brainvision-recording-format/)
are the initial format references, checked 2026-10-18. BVRF conversion can omit
impedance and other metadata; conversion is not automatically a lossless
substitute for native support.

Keep companion-file identity, units/calibration, channel roles, acquisition and
analysis references, geometry, sampling, event types/sample positions and
discontinuities explicit. Reuse the shared pipeline and capability gates rather
than the BioSemi EXG-pair policy. Validate full/lazy reads, reviewed marker maps,
cache/resume, exports and eligible downstream tools with representative fixtures
for every claimed combination. Record direct support, validated conversion,
unqualified and unsupported cases separately. Broad family coverage is the
goal; it is not a promise that every unknown or historical file already works.

## Target: a composable processing pipeline

Resolve a deterministic processing plan from the acquisition and montage
contract, versioned method policy, and reviewed project settings. The plan must
support swapping, including, or omitting steps when the selected montage and
device require it, without duplicating the orchestration for each headset.

Each step needs a clear input/output contract, prerequisites, applicability,
method/version identity, and cancellation/error behavior. Distinguish required,
optional, and unsupported steps. Validate the whole plan before work starts;
report disabled or unavailable checks accurately. Reject incompatible settings
instead of silently substituting a reference, geometry, or scientific method.
Keep GUI controls driven by the resolved capabilities, compact and relevant to
the selected setup; execution remains in workers.

Persist enough resolved plan and acquisition identity to reproduce results and
invalidate stale checkpoints, caches, ledgers, and downstream artifacts when
the method or layout changes. Full processing, review preparation, resume,
condition repairs, and single-file/batch routes must use the same plan semantics.
Keep existing exported formats compatible; any necessary new provenance or
schema must be versioned with an explicit migration.

The existing BioSemi profile remains the regression baseline: initial reference,
drop reference channels, optional channel limit preserving stim, FIR filtering,
optional smart FFT Hann multi-notch filtering, downsampling,
kurtosis/interpolation according to reviewed settings, then final
average reference. Extracting this behavior into steps must preserve its order,
numerical values, FIR scaling, and fingerprints. A genuinely different method
requires a scoped scientific change, evidence, contract updates, and focused
tests. Pipeline modularity is not permission to reorder arbitrary operations.
The locked harmonic-selection profiles and independent FHC inference contracts
remain unchanged by acquisition refactoring.

## Target: complete FPVS Studio compatibility

The product goal is full compatibility across FPVS Studio's supported
experiment-to-analysis workflows, not only successful config parsing or updater
parity. Establish the exact Studio source/release and schema versions being
targeted before implementing an adapter. The current Toolbox tests specify its
accepted subset; they are not evidence that every current Studio export or
workflow is covered.

Maintain a compatibility matrix covering:

- Experiment categories, conditions, frequencies, recurrence, planned sequence
  counts/durations, trigger maps, and analysis-window semantics.
- Project, participant, group, session, run, and recording identities, including
  repeated sessions, exclusions, and manually removed electrodes where defined.
- Hardware/montage/reference declarations, channel roles, units, sampling,
  event sources, recording association, clock domains, discontinuities, and
  incomplete or failed acquisition evidence.
- Config, recording, and acquisition-sidecar schemas, required/optional fields,
  unknown versions, migrations, and any result handoff Studio actually defines.
  Determine the required direction for each exchange from the verified Studio
  contract; do not invent a reverse-import or result format.
- User workflow from Studio export through Toolbox project creation, review,
  processing and analysis, including unsupported combinations and recovery.

For every matrix row, record the verified producer contract, Toolbox consumer,
support status, remaining gap, and a reproducible acceptance fixture. Preserve
relevant provenance without silently dropping required scientific metadata.
Unknown or conflicting scientific fields must be rejected or routed to explicit
review. Keep canonical project/group/recording identity in `Main_App.projects`;
an external handoff must not bypass project validation or overwrite decisions.
Do not copy stimulus assets, private recordings, or local participant records
into source control to demonstrate interoperability.

## Implementation sequence and acceptance

1. Inventory verified Studio contracts and hardware/montage capabilities; record
   gaps and unresolved evidence before claiming support.
2. Characterize the existing BioSemi behavior, then extract reusable step
   contracts and deterministic plan resolution while preserving that baseline.
3. Integrate alternate acquisitions through the shared contracts: finish the
   already-defined Unicorn path and add the required Brain Products format and
   hardware-family coverage. Complete each profile's evidence gates and shared
   execution routes before enabling production support.
4. Generalize downstream capability checks, geometry/ROI/adjacency ownership,
   persistence, provenance, and cache identity; qualify each additional montage.
   Prove the extension boundary with a third synthetic profile/montage that
   reaches common production processing through registration and tests without
   another device branch in orchestration or scientific metric code. Existing
   third-profile inspection tests alone do not satisfy this gate.
5. Close the Studio compatibility matrix with sanitized cross-application
   fixtures, malformed/unsupported cases, and end-to-end workflow acceptance.

Each implementation slice needs a bounded active plan and focused regression
checks. Use `verify.py --scope project-io --tier focused` and
`--scope processing --tier focused` for the foundation, then affected tool/GUI
scopes and the repo precommit gate for runtime integration. Execute Qt only in
CI or an explicitly approved visible environment. Portable source tests,
scientific qualification, native installer checks, and human workflow review
are separate evidence; document which have actually passed.

Do not label a device, montage, or Studio version fully supported until every
applicable acceptance row is satisfied. Research or design evidence alone does
not enable runtime support, and a passing parser test does not qualify hardware
amplitude, wireless integrity, or physical stimulus-onset timing.
