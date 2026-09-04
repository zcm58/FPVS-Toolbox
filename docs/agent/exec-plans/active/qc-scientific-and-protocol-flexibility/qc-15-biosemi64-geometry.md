# QC-15: Canonical BioSemi64 Geometry and Legacy Impact

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts. Execute it before
every other action in this plan.

**Status:** accepted on 2026-09-03 as execution priority 1. The user reports
that most historical recordings required interpolation, so prior outputs are
potentially affected and require an explicit compatibility assessment.

## Accepted Behavior

1. Replace the active processing loader's `standard_1005` assignment with one
   canonical MNE `biosemi64` montage used by preflight, full loading, spatial
   QC, interpolation, and processing-owned map/provenance consumers. Preserve
   the recorded signal associated with each channel name; do not reorder data.
   Store a project-owned montage identifier with the sole accepted value
   `biosemi64`; do not derive it from a user-global preference.
2. At load, before the locked optional channel-limit stage, require the exact
   supported set of 64 anatomical scalp identities and finite BioSemi64
   coordinates. Report an incomplete or ambiguous acquisition as a technical
   failure rather than logging that the montage succeeded. After an explicitly
   configured intentional channel limit, freeze the retained eligible canonical
   scalp set for QC-07/QC-21 and provenance; every retained scalp channel must
   still have a unique BioSemi64 identity and finite coordinates. The ordinary
   full analysis retains all 64. A reduced set must be explicit and cannot
   masquerade as a complete 64-channel analysis. Keep CMS/DRL outside the
   data-channel montage and keep the selected EXG mastoid references
   coordinate-free through initial reference and their existing removal.
3. Anatomical BDF headers map directly by name. If A1-A32/B1-B32 headers are
   encountered, accept them only through an explicit, tested BioSemi64 wiring
   profile stored in project/protocol provenance. Never infer anatomy from
   ordinal order or silently accept an unknown/custom cap arrangement.
4. Give the geometry a versioned processing identity. Invalidate relevant QC,
   interpolation, processed-data, FullFFT/BCA, and downstream-analysis cache
   reuse when geometry differs. Retain old files for audit, label their legacy
   geometry truthfully, and block silent pooling of old- and new-geometry
   outputs.
5. Treat historical work produced with `standard_1005` as requiring
   reprocessing before new analysis or publication when any channel was
   interpolated or a geometry-dependent automatic rule informed channel
   selection. A legacy output may remain viewable with a prominent status; do
   not delete or silently rewrite it.
6. Revalidate the experimental spatial-predictability and cluster calibration
   under BioSemi64 before those rules can operate as validated automatic
   evidence. Preserve the separate, versioned Free Harmonic Clustering graph;
   this action does not alter that locked statistical method.
7. Add an **Electrode montage** entry to project settings as the extension
   point for future hardware support. For now it displays only **BioSemi
   ActiveTwo 64** and cannot accept a custom or alternative template. Persist
   the canonical identifier in `project.json`, processing inputs, outputs, and
   provenance. A future montage becomes selectable only after its channel
   mapping, geometry-dependent QC, interpolation, migration, and validation
   contracts are explicitly added.

## Sensitivity and Legacy Assessment

First isolate geometry by processing representative recordings with identical
bad-channel decisions under both templates. Then repeat the complete pipeline
to capture any changed spatial nominations. Include isolated and clustered
frontal, temporal, central, and posterior interpolation patterns and the
observed range of interpolation burdens.

Compare interpolated time series, final average-referenced data, FullFFT,
BCA/SNR/local-z values, included harmonics, scalp maps, participant summaries,
and group results. Report absolute and relative changes by channel and
condition; identify decision changes separately from small numerical changes.
Produce a project inventory of geometry version, successful interpolation
channels, affected conditions, stale outputs, and reprocessing status. Use the
results to prioritize reprocessing, not to mix geometries within one analysis.

## Owners and Acceptance

The active BDF-loading surface is `Main_App.io.load_utils`; follow its current
shared implementation only as needed. Other primary owners are raw-channel QC,
preprocessing interpolation, processing ledger/cache identity, preprocessing
reporting, FullFFT provenance, and project dataset indexing. Audit downstream
map tools for consistent canonical coordinates while leaving tool-local locked
graphs intact.

Acceptance requires tests for all 64 anatomical labels, finite coordinate
coverage, identical preflight/full-load geometry, reference-channel handling,
explicit A/B-profile success and unknown-profile failure, interpolation
geometry, explicit channel-limit freezing, legacy migration, cache
invalidation, and rejection of mixed
geometry group inputs. Verify the project setting has exactly one available
choice, round-trips through `project.json`, and reaches every processing and
provenance consumer without a global reread. Add a reproducible non-GUI
sensitivity runner and report. Update the preprocessing contract, calibration
documentation, user QC guidance, and methods-reporting checklist. Document a
visible manual smoke path; keep Qt execution in CI.

Scientific basis: MNE distinguishes the international `standard_1005` montage
from the BioSemi 64-channel template and uses sensor locations for EEG
spherical-spline interpolation
([MNE montage definitions](https://mne.tools/0.24/generated/mne.channels.make_standard_montage.html),
[MNE interpolation API](https://mne.tools/stable/generated/mne.io.Raw.html)).
BioSemi describes its standard 64-channel cap as a 10/20 layout and CMS/DRL as
non-data electrodes
([BioSemi headcap specifications](https://www.biosemi.com/headcap.htm),
[BioSemi CMS/DRL explanation](https://www.biosemi.com/faq/cms&drl.htm)).
