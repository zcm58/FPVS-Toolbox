# Shared QC Execution Contracts

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [review evidence](review-record.md)

Read this file with the parent index and the one QC action module being executed. These contracts prevent the modules from silently choosing conflicting identities, scopes, outcomes, or cache behavior.

## SC-01: Canonical Identity and Scope

Use `Main_App.projects.dataset_index` through the public `Main_App.projects` surface for participant, group, recording, session/visit, and condition identity. Default review and exclusion decisions to the affected recording in repeated-session projects. Preserve explicit whole-participant controls. Never infer group membership from output folders.

## SC-02: Exact Analyzed Intervals

Signal-based QC scoring uses the exact marker-derived intervals retained for analysis, with source and target sample coordinates, condition, occurrence, and crop provenance. Setup, breaks, discarded tails, and other unanalyzed samples do not directly contribute to QC decisions. Continuous temporal preprocessing can still use surrounding context; the separate analysis-window investigation owns that question.

## SC-03: Detector Control and Migration

Experimental removed-electrode detection is Off by default for new projects. Auto, Manual, and Off must be honored consistently in preflight, review, runner, cache, and reports. Manual lists remain available independently. Preserve valid saved modes and legacy choices; missing legacy preference requires one explicit choice before processing. Never expose inferred detector output while claiming the detector was Off.

## SC-04: Evidence, Suggestions, and Decisions

Store original machine findings, candidate sources, user-accepted/rejected/manual channel selections, and recording inclusion/exclusion decisions separately. A suggestion is not confirmed physical failure, successful interpolation, or a user decision. Review flags alone do not automatically change the analysis cohort unless the applicable action explicitly says so. Persist decision reason, reviewer state, time, evidence fingerprint, and scope.

## SC-05: Truthful Processing Outcomes

Use distinct attempted, successful, failed, skipped, unavailable, and legacy-unknown states for preprocessing and interpolation. Intended targets are not successful repairs. Never turn unknown or failed outcomes into zero burden or a successful status. QC-02 owns the preprocessing report taxonomy; QC-07 consumes confirmed successful interpolation outcomes.

## SC-06: Cache, Fingerprint, and Legacy State

Bind cached findings and review reuse to raw/workbook identity, project protocol inputs, exact analyzed spans, detector settings, method/policy versions, and relevant thresholds. Materially changed evidence requires renewed review. Handle excluded processing-ledger entries explicitly because they may be reused before ordinary fingerprint comparisons. Preserve explicit manual exclusions and independent technical failures during migrations.

## SC-07: Locked Processing Method

Preserve the locked preprocessing order: initial reference, drop reference channels, optional channel limit preserving stim, FIR filter, downsample, kurtosis/interpolation, final average reference. Leave fixed spatial interpolation applied to continuous Raw. Do not introduce condition-specific repair maps, reorder processing, or alter locked harmonic-selection mathematics unless a later explicitly approved statistical-method action updates the required contracts and tests.

## SC-08: GUI and Worker Behavior

Use PySide6 and existing `Main_App.gui.components`, theme tokens, dialog/status patterns, and recording-aware review surfaces. Keep revised embedded pages within the supported 1280x900 workspace without page-level scrolling. Long work stays off the UI thread; workers communicate only through signals. Qt execution is CI-only unless the user approves a safe visible local environment. Document a visible/manual smoke path.

## SC-09: Scientific Claims

Screening thresholds and published descriptive interpolation burdens are review criteria unless an action cites validation for stronger authority. Passing a threshold does not prove clean data; crossing one does not prove unusability. Manual review is additional evidence, not independent ground truth. Preserve measurements and limitations in user and methods reporting.

## Shared Verification and Documentation

Run the smallest focused checks for each module through `python .agents/scripts/verify.py --scope <scope> --tier focused`. Use the repository precommit gate only for final integrated handoff. Run skill-local static audits when their scope applies. Never run offscreen Qt workflows locally. At integration, update the preprocessing, post-processing/export, FFT-crop, GUI/project-I/O, calibration, and user methods/QC documents named by the executed modules. Normal scientific output formats and values remain unchanged unless the approved action explicitly changes them.
