# Hardware, Processing, and FPVS Studio Direction

Status: maintainer-directed product and architecture goals, recorded 2026-10-18.
This page separates the current implementation from the intended future state.
It guides scoped implementation plans; it does not enable new hardware or change
scientific methods by itself. Read it when changing acquisition, montages,
processing composition, project import, or Studio interoperability.

## Current implementation

| Area | Implemented boundary | Still to do |
| --- | --- | --- |
| Production acquisition | BDF loading and preprocessing use the validated BioSemi64 geometry contract. Canonical and explicitly mapped A/B channel labels are supported. | Integrate and qualify other hardware/montage combinations throughout the application. |
| Acquisition definitions | `Main_App.io.acquisition_profiles` separates versioned format, device acquisition, montage, event decoding, and capabilities in an immutable registry. | Make the resolved contract drive production loading, processing, QC, GUI availability, and downstream tools consistently. |
| Unicorn | Read-only BDF/BDF+ inspection, explicit channel/unit/event policies, and a context-owned lazy/RAM/memmap MNE reader exist. Results retain `scientific_processing_allowed=False`. | Complete the [Unicorn plan](../exec-plans/active/unicorn-hybrid-black-support.md), including unresolved acquisition evidence and production integration. A readable recording is not scientific qualification. |
| Processing | `Main_App.processing.preprocess` owns the locked BioSemi pipeline. Optional screens and approved repair policies already have versioned settings/provenance. Workers and prepared checkpoints preserve that contract. | A shared composition mechanism that selects, replaces, or omits steps from an explicit acquisition/montage policy; existing switches are not a general pipeline system. |
| Studio project import | `Main_App.projects.fpvs_config_import` accepts `.fpvsconfig` schemas 1.0.0–1.8.0 for FPVS Oddball and Cognitive Load FPVS, importing the Toolbox-owned project/protocol/marker and optional removed-electrode subset. | Verify complete field and workflow coverage against explicitly identified Studio versions and real, sanitized exports. Current import is not complete Studio compatibility. |
| Studio acquisition evidence | `Main_App.io.studio_acquisition_evidence` validates a candidate handoff and compares ordered trigger codes only after reviewed recording association. | Qualify receiver integration, recording identity, acquisition facts, and timing semantics. Code agreement alone does not prove sample timing or recording completeness. |
| Updates | The independent updater uses ported Studio design/contracts with Toolbox-specific application and installer identities. | Maintain versioned protocol parity where intended. Updater similarity does not establish experiment/data interoperability. |

Evidence owners: [BDF loading](eeg-loading-contract.md),
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
3. Integrate the already-defined Unicorn path as the next concrete alternate
   acquisition, completing its evidence gates and all shared execution routes.
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
