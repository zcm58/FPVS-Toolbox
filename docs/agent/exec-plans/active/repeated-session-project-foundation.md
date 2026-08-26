# Repeated-Session Project Foundation

## Status

Active on `codex/repeated-session-projects`.

## Goal

Add first-class repeated-session EEG projects without changing the numerical
preprocessing contract or the existing single-session project behavior.

The motivating dataset has one stable between-participant group factor
(birth-control vs no birth-control) and two recordings of the same participant:
luteal at visit 1 and follicular at visit 2, approximately two weeks later.
The implementation must remain generic: sessions are project-defined metadata,
not hard-coded menstrual-cycle concepts.

## Scientific Contract

- `participant_id` is the stable person/pairing identity.
- `group_id` is a participant-level between-subject identity and cannot change
  between recordings.
- `recording_id` is the stable raw-file, processing-ledger, derivative, and QC
  identity.
- `session_id` is the within-participant repeated-measure level.
- `visit_index` and optional interval metadata are distinct from the session
  label.
- A participant may have at most one recording per declared session.
- Missing sessions are allowed, surfaced in design/QC audits, and never filled
  with zero or silently converted into a participant exclusion.
- The motivating study always acquired luteal at visit 1 and follicular at
  visit 2. Session/phase is therefore perfectly confounded with visit order,
  elapsed time, repetition, and habituation. User-facing reports must describe
  a `session/phase-at-visit` contrast and must not claim an isolated
  physiological phase effect.
- Raw preprocessing runs independently per recording and preserves the locked
  preprocessing order and calculations.
- Standard Summed-BCA consumers use one canonical harmonic list across all
  groups and sessions. Repeated-session pooling/fingerprinting is a separately
  versioned scientific policy; sessions must never receive independently
  selected lists inside one repeated-session project.
- The locked single-session Standard FPVS Screening method remains unchanged.
  Repeated-session inference is a separate analysis mode and export contract.

## Versioned Manifest Contract

Single-session v2.1 manifests remain valid and retain their exact persisted
shape. A repeated-session project adds these v2.2 fields:

```json
{
  "schema_version": "2.2.0",
  "sessions": {
    "luteal": {"label": "Luteal", "visit_index": 1},
    "follicular": {"label": "Follicular", "visit_index": 2}
  },
  "recording_sources": {
    "bc_luteal": {
      "group_id": "birth_control",
      "session_id": "luteal",
      "raw_input_folder": ".../BC Group/Luteal"
    }
  },
  "participants": {
    "P01": {"group_id": "birth_control"}
  },
  "recordings": {
    "P01__luteal": {
      "participant_id": "P01",
      "session_id": "luteal",
      "source_id": "bc_luteal",
      "raw_file": ".../P01_BC_L.bdf",
      "visit_index": 1,
      "days_from_baseline": 0
    }
  }
}
```

Rules:

- Session, source, participant, and recording IDs are stable readable slugs;
  labels are presentation only.
- Each recording source resolves to exactly one canonical group and session.
- Each raw source folder and raw file is unique.
- A recording raw file is a direct `.bdf` child of its declared source.
- Recording participant/group membership must agree with the participant and
  source definitions.
- A repeated-session project may keep the existing group raw root as a common
  parent for compatibility, but processing discovery uses the explicit
  recording sources.
- Locked grouped projects also lock session/source definitions and recording
  assignments after the first successful repeated-session output.
- Legacy projects synthesize a default in-memory recording identity only where
  a shared consumer needs it; loading must not rewrite an old manifest.

## Output And Index Contract

- Existing single-session filenames and directories remain byte-for-byte
  compatible.
- Repeated-session Excel output retains the condition-first/group-second
  directory layout and uses a collision-safe recording filename:
  `<recording_id>_<condition>_Results.xlsx`. The project setup/import default
  recording ID is `<participant>__<session>`, while the canonical manifest ID
  remains authoritative for any explicitly named recording.
- Source-ready time-domain derivatives, manifests, caches, and ledger records
  likewise include `recording_id` so one visit cannot overwrite another.
- `WorkbookRecord` carries participant, recording, session, visit, and group
  identity. Duplicate identity is `(recording_id, condition)`.
- Downstream selection filters by stable IDs, never by generated directory or
  filename inference.
- Participant-wide, recording-wide, participant-condition, and
  recording-condition exclusions remain distinguishable.

## Processing And QC Contract

- Batch discovery enumerates every declared recording-source folder.
- Repeated participant IDs are expected across different sessions; duplicate
  participant/session or duplicate raw-file ownership hard-fails.
- Group changes across sessions hard-fail before BDF loading.
- Participant review becomes recording-aware and persists participant and
  recording changes only after confirmation.
- The processing ledger, incremental planner, preflight cache, QC rows, output
  cleanup, and provenance key work by recording ID while retaining participant
  ID for paired analysis.
- Removed-electrode decisions may differ by recording. Existing participant-
  scoped settings remain backward-compatible and act as defaults unless an
  explicit recording override exists.

## Tool Contract

### SNR Plots

- Task condition and recording session are separate controls.
- Supported descriptive views include group overlays within one session,
  session overlays within one group, and a vertically stacked stable-group
  session-overlay view at the normal single-SNR figure width.
- Session comparisons report contributing participant N for every group and
  session curve.
- Labels for the motivating project include both phase and visit.

### Scalp Maps

- One task condition may render a group-by-session panel grid with common
  per-metric color limits.
- Any within-session difference map is computed within participant first and
  then averaged; subtracting independent grand averages is not allowed.
- Maps remain descriptive and are not labelled as statistical tests.

### LORETA Project Sources

- The current LORETA Stats-ready workbook and project-source producers are
  participant-keyed and cannot represent two recording IDs for one participant
  safely.
- Repeated-session post-processing reports those three legacy outputs as
  successful, non-applicable skips while preserving source-ready derivatives
  and continuing the recording-aware full-audit export. Single-session LORETA
  behavior is unchanged.

### Statistics

- Session-aware long exports include participant, recording, group, session,
  visit, condition, ROI, DV, and QC/exclusion fields.
- A native repeated-session analysis mode is separate from Standard FPVS
  Screening.
- Its design audit reports duplicate/missing visits, stable group membership,
  observed and paired Ns, coverage, and missing-data assumptions.
- Version 1 requires exactly two stable groups and exactly two ordered
  sessions. For each explicitly declared Condition x ROI outcome it computes
  the participant change (visit 2 minus visit 1), then uses a two-sided Welch
  test to compare those changes between groups. The primary Holm family spans
  every declared outcome, including declared but non-estimable outcomes.
- Secondary paired within-group changes use two-sided one-sample tests of the
  participant changes and one separate Holm family across both groups and all
  declared outcomes. There is no imputation, model fallback, or automatic
  full Group x Session x Condition x ROI screen.
- The GUI reads the recording-aware full-audit ROI-long workbook in a worker,
  displays complete-pair coverage, requires explicit outcome selection, and
  writes primary, secondary, delta, coverage, missingness, metadata, and
  canonical long-data sheets atomically.
- Because session and visit order are perfectly aligned in the motivating
  dataset, every result uses `session/phase-at-visit` language.

### Free Harmonic Clustering

- Repeated projects are recognized automatically and use the separately
  versioned `fhc_repeated_session_batch_v1` workflow; legacy one-contrast
  projects remain unchanged.
- Exactly two stable groups, two ordered sessions, and every project condition
  produce four participant-level families: session-averaged groups, paired
  Visit 2 minus Visit 1 within each group, and the between-group difference in
  participant session change.
- All primary families use complete recording pairs. Missing visits and
  batch-local recording exclusions with required reasons remain in the audit;
  recordings are never treated as independent participants.
- One harmonic domain is selected and frozen across the entire batch. Global
  run p-values receive Holm correction across conditions within each family and
  a conservative second correction across the full batch.
- The fixed-order confounding remains in the workbook, manifest, and reporting
  guidance without adding a repeated warning to the compact GUI. The legacy
  powered-null receipt does not cover this extension.

## Delivery Slices

1. Project/session/recording schema, public context, persistence, dataset index,
   and backward-compatible tests.
2. Recording-aware discovery, review, ledger, post-export naming, QC,
   provenance, and analysis-ready export.
3. Repeated-session project creation/import UI plus CI-only pytest-qt smoke
   definitions.
4. Session-aware SNR and Scalp Maps descriptive workflows.
5. Session-aware Stats export, design audit, validated inference mode, and
   reporting.
6. Birth Control folder import/validation and visible end-to-end smoke.
7. Protective gates/skips for participant-keyed tools and post-processing
   outputs that cannot yet preserve recording identity.
8. Versioned repeated-session Free Harmonic Clustering preparation, four-family
   batch inference/export, embedded GUI, documentation, and Birth Control
   acceptance analysis.

## Private study input audit

Participant-level source conflicts and group/session assignments are retained
privately. Import must block unresolved source/group identity conflicts and
filename/source mismatches; legacy analysis artifacts are not import authority.

## Verification

Run locally safe checks only; Qt execution remains CI-only unless a visible
safe environment is explicitly approved.

```console
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/scripts/verify.py --scope project-io --tier focused
python .agents/scripts/verify.py --scope processing --tier focused
python .agents/scripts/verify.py --scope plot-generator --tier focused
python .agents/scripts/verify.py --scope publication-maps --tier focused
python .agents/scripts/verify.py --scope stats --tier focused
python .agents/scripts/verify.py --scope gui --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

Visible/manual smoke:

1. Create a repeated-session project with two groups and two sessions.
2. Select one raw source folder for every group/session cell.
3. Review paired, missing-session, filename/source mismatch, and group-conflict
   rows without loading BDF data.
4. Confirm processing lists recordings separately and never overwrites the
   first visit.
5. Generate one group-by-session SNR view and one Scalp Maps grid.
6. Export the session-aware analysis workbook and inspect paired/missing Ns.

Locally safe verification completed with 135 project-I/O tests, 431 processing
tests (three memmap cases rerun successfully outside the restricted sandbox),
490 Stats tests, 198 Plot Generator/Publication Maps tests, 110 Free Harmonic
Clustering tests, 296 LORETA tests, and 28 post-processing worker tests. Ruff,
compileall, GUI/protected/source-localization/Stats/print/garbage-collection
audits, and `git diff --check` passed. PySide6/pytest-qt smoke remains CI-only.
The repo path audit is blocked by eight pre-existing findings under the
user-owned untracked `outputs/rcads-*` tree; no changed feature file is
implicated.

## Progress

- [x] Read-only repo and motivating-data audit.
- [x] Feature branch created.
- [x] Schema/context/index.
- [x] Processing/QC/provenance.
- [x] Project setup GUI and CI smoke definitions.
- [x] SNR/Scalp Maps.
- [x] Stats export/inference/reporting.
- [x] Birth Control source preflight/import validation. Import remains blocked
  until the documented identity conflicts are resolved; source data are unchanged.
- [x] Focused non-Qt verification and documented CI-only visible/pytest-qt
  smoke. The repo-wide path stage retains the unrelated `outputs/rcads-*`
  findings described above.
- [ ] Repeated-session Free Harmonic Clustering extension and Birth Control
  acceptance run (tracked in
  `repeated-session-free-harmonic-clustering.md`).
