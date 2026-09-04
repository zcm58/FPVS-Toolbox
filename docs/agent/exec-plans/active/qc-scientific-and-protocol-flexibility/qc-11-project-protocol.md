# QC-11: Project-Owned Frequency Protocol

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this
action.

**Status:** implemented on the active QC branch. Each project owns one exact
presentation/oddball protocol and fingerprint, including recurrence-count or
direct-Hz entry with whole-number recurrence validation. Per-condition rate
overrides remain out of scope, and the live project-global BCA ceiling has been
removed.

## Problem

The rates currently live in application-wide settings. Processing copies them
at launch, but later frequency QC, harmonic selection, and provenance
independently reread the current global values. Changing settings for one
project can therefore alter how an older project's outputs are reviewed or
described. The oddball field is additionally forced to 1.2 Hz in several
active paths; removing that method lock belongs to the next rate action. A
separate application-wide `bca_upper_limit` normally defaults to 16.8 Hz but
has a conflicting 40-Hz code fallback. It is legacy implementation state, not
project protocol physics.

## Accepted Behavior

1. Add one versioned frequency-protocol record to `project.json` containing
   `presentation_rate_hz`, the oddball input mode, `oddball_every_n`, and
   canonical `oddball_rate_hz`. Validate the exact integer recurrence under
   QC-12. Do not add condition-level overrides or a universal BCA ceiling.
2. Initialize a new project's record once from the current defaults. Thereafter
   the settings GUI reads and writes the active project only; editing one
   project cannot change another project.
3. Resolve one immutable rate snapshot before a processing run. Pass it unchanged
   through crop planning, processing, export, frequency QC, provenance,
   harmonic selection, Stats, and cache/fingerprint inputs. Remove downstream
   application-setting rereads for the rates.
4. Persist the resolved rates and protocol version with derived artifacts.
   Editing the project protocol marks affected processing and frequency-domain
   outputs stale and requires regeneration before reuse.
5. For an existing project, migrate the rates from unambiguous persisted
   run/workbook provenance when available. Otherwise require the user to
   confirm a proposed legacy rate set before new processing; do not silently
   relabel old outputs.
6. Preserve per-target numerical behavior inside the formerly analyzed range
   for 6/1.2-Hz projects. This action establishes ownership and propagation;
   QC-12 later adds supported targets above the old generic limit under a new
   method version. QC-11 does not itself alter harmonic-selection mathematics
   or duration-sensitive neighboring-bin policy.
7. Do not promote legacy `bca_upper_limit` into the canonical project
   protocol. Preserve an old artifact's recorded value only as read-only audit
   and interpretation metadata; the current resolver never consumes it. A
   saved fixed/preregistered exact list or range remains a distinct, valid
   method input. QC-12 owns current technical eligibility.

## Owners and Acceptance

Implement schema normalization and persistence in `Main_App/projects/`, then
route the snapshot through `Main_App/gui/processing_inputs.py`, processing and
post-processing workers, FFT/BCA exports, frequency QC, canonical harmonic
selection, Stats consumers, and provenance/fingerprint builders. Replace GUI
global storage for the rate fields with project-bound controls, retire the
generic ceiling control when QC-12 supplies its replacement, and provide clear
project-required messaging when no project is open.

Verify with two projects holding different rate sets: changing or processing
project B must not change project A's values, outputs, QC inputs, provenance,
or fingerprints. Cover new-project defaults, save/reopen, an unambiguous legacy
migration, ambiguous legacy confirmation, stale-output invalidation, unchanged
per-target 6/1.2-Hz values inside the former range, and a versioned expanded
rerun under QC-12. Update the project-I/O, GUI, FFT-crop,
post-processing/export, and methods-reporting contracts when implementation
lands. Use focused non-GUI checks and a documented visible GUI smoke path; Qt
execution remains CI-only.
