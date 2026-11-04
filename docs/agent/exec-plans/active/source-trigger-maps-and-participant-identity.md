# Source trigger maps and independent participant identity

## Current status

Implementation is complete (2026-10-21); source and combined-project processing
validation completed on 2026-10-22. The remaining acceptance is visible GUI
review, deferred by the user, plus registered Qt execution in CI. Do not restart
completed cohort processing or statistical comparisons from this plan.

The versioned mapping model, durable source identity, registration, processing
integration and unified Home/Settings editor are implemented. Current contracts:

- [Project I/O: identity and trigger maps](../../architecture/project-io.md#independent-source-study-identities)
- [EEG loading](../../architecture/eeg-loading-contract.md)
- [GUI](../../architecture/gui.md)
- [User workflow](../../../user/reference/source-trigger-maps.md)
- [Guided setup acceptance](guided-pipeline-setup.md)

Completed implementation and study-analysis chronology remain in Git history;
project-local receipts remain the authority for those particular datasets.
Historical test counts describe their revisions, not today's verification gate.

## Boundaries to preserve

- Source study, biological group, participant, recording and trigger protocol
  are separate identities. Source-local `P1` in two studies can denote different
  people; exact registered paths resolve canonical IDs before filename inference.
  Preserve existing IDs, original labels/leading zeros and repeated-visit pairing.
  Cross-study same-person linking and automatic rekeying remain out of scope.
- Preserve raw bytes, native event codes and sample positions. Use explicit
  named profiles with onset/oddball pairs, one explicit assignment and an immutable
  resolved snapshot per canonical processing ID. Group defaults propose future
  registrations only; reassignment requires a reviewed scientific edit.
- Explicitly opted-in mapped projects use protocol 1.5.0 and extension schema
  1.0. Legacy projects keep their payloads, event maps and fingerprints. Retire
  competing global/condition/recording oddball stores only through reviewed
  conversion; ordinary editing does not convert mapped projects back.
- Every selected condition needs a valid mapping in each assigned profile,
  including excluded recordings. Unknown/missing assignments block before work.
  Keep recognized unselected onsets as boundary-only events; they end blocks
  without creating expected outputs. Structurally uncollected group-condition
  designs remain a separate feature.
- All profiles share one rate/length protocol. Scientific map/catalog/assignment
  edits invalidate interpreted processing and downstream results project-wide.
  Cosmetic source/profile labels and registration defaults do not. Condition
  output labels remain scientific identity. Targeted invalidation needs separate
  proof; this feature does not change numerical preprocessing or Stats/FHC methods.
- Publish source registration, assignments, exclusion transitions and freshness
  atomically. Cancel, stale drafts and failed saves preserve the prior manifest.
  Migrations require explicit participant/recording/condition crosswalks; copied
  QC receipts, caches and harmonic selections are not automatically valid.

Owners are `projects.condition_trigger_maps`, `raw_identity`,
`source_registration`, `frequency_protocol` and the public `Main_App.projects`
surface. `gui.trigger_maps_dialog`/`trigger_maps_workflow` share the editor;
Home publishes atomically, Settings waits for its outer Save, and guided setup
preserves maps while requiring the user to leave the wizard to edit them.
Detailed APIs and consumers belong in the linked architecture contracts.

## Remaining visible acceptance

Use a disposable two-source project in an explicitly approved visible environment:

1. Open a legacy project, then configure two source-local `P1` recordings with
   distinct canonical IDs and differing onset/oddball maps.
2. Check collisions, missing assignments, one-way opt-in, legacy marker-control
   routing, Cancel, Save/reopen, and preservation of existing oddball differences.
3. Add a recording with an explicit profile; change a group default and confirm
   existing identities/assignments remain unchanged. Existing group locks apply.
4. Check Home saves against stale Settings drafts and the guided-setup guard.
   Confirm identities persist through participant review, exclusions and QC.
5. Verify the editor and reviews fit 1280x900, with scrolling confined to tables.

No offscreen Qt. Registered coverage executes in CI; source tests do not establish
visible behavior. Use the verification driver's `project-io`, `processing`, `gui`
and `pipeline-setup` focused scopes when those owners change; add `stats` or
`free-harmonic-clustering` only for changes to their consumers. Finish with
`--scope repo --tier precommit`. The executable registry owns exact test lists.

Trigger/identity validation does not establish experimental comparability,
causal group effects or statistical significance. Study-specific comparisons
require their own analysis plan and provenance.
