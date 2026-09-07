# QC-17: Experimental Summed-BCA Review Gate

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-03, QC-10 through
QC-15, QC-20's pre-review readiness gate, QC-21 definition/source
prevalidation, and the project-settings portions of QC-04.

**Status:** software behavior implemented on the active QC branch on
2026-09-04. Keep the existing magnitude and count values as experience-based
experimental defaults, but remove their independent authority to exclude data.
Review takes place in the GUI. Representative-data calibration is required only
before considering stronger scientific authority; the current review-only
behavior does not depend on it. CI-only Qt execution and the visible smoke path
remain verification work.

## Accepted Behavior

**2026-09-07 amendment:** individual electrode and ROI exclusions are retired.
The default-off experimental setting instead permits artifact-confirmed,
condition-specific EEG interpolation followed by regenerated QC and analysis.
Historical narrow exclusions require a new decision and are retained only for
audit. Reasons remain optional. This supersedes the electrode-exclusion and
mandatory-reason wording below; see the
[condition-specific interpolation implementation](../condition-specific-interpolation.md).

1. Add a dedicated **Experimental settings** section to the project Settings
   menu. Put the QC-04 removed-electrode detector and a project-owned
   **Experimental summed-BCA screening** control there. The summed-BCA screen
   can be enabled or disabled and is On by default because its result is only a
   review flag. Existing projects migrate to On to preserve their prior screen;
   prior automatic decisions are handled separately below. A disabled run is
   `not performed`, never `passed`.
2. Expose and preserve these rough defaults: warning above 10 uV, strong warning
   above 50 uV, extreme review above 250 uV, concentrated review at five flagged
   cells, and broad extreme review at 11 unique electrodes. Validate finite,
   positive, strictly ordered amplitude values and integer counts from 1 through
   64. Store the enabled state, values, and policy version per project.
3. Rename `hard` findings to `extreme` or `high-priority review`. No summed-BCA
   value or count automatically excludes an electrode, condition, recording, or
   participant. The GUI has no preselected decision: the reviewer must explicitly
   choose Retain for the scientific no-exclusion outcome or choose a reasoned
   exclusion. A broader exclusion requires a separate explicit user choice.
   Independent technical evidence keeps only
   the authority granted by its own validated policy; BCA cannot promote another
   review-only method to automatic authority and is not a QC-16 corroborator.
4. Scope each finding and decision to its actual recording, condition, and
   electrode. Show grouped patterns for context without widening their scope.
   One extreme value in Condition A cannot remove that electrode from Condition
   B. Preserve the original measurement, machine flag, supporting evidence, and
   user decision separately.
5. The GUI shows signed and absolute summed BCA, band crossed, exact harmonic
   count/list, recording and condition, analyzed duration/cycles, and relevant
   independent QC. Use brief text: **“Experimental summed-BCA screening flags
   unusually large frequency responses for review. These suggested limits come
   from FPVS Toolbox development experience and are not validated for every
   protocol. This check does not remove data by itself.”**
6. Consolidate the separate Stats cohort-relative BCA screen into this review
   as optional experimental context. For each explicit condition and ROI, show
   the sum of absolute ROI-mean harmonics and the largest absolute harmonic
   relative to the eligible cohort. Retain median/MAD with documented IQR and
   zero-spread fallbacks, robust-score defaults of 6/10, sum floors of 5/10 uV,
   and peak floors of 1/2 uV as editable experimental defaults. Use the
   current in-memory candidate harmonic list and project protocol. Missing, unreadable, or
   incomplete inputs produce visible technical statuses rather than being
   skipped. Fingerprint the ROI definition and cohort.
7. Remove the Stats screen as an independently calculated, exclusion-named
   system. Stats consumes the saved QC-17 evidence and decisions and does not
   silently rebuild a fixed-1.2-Hz domain. Keep nonfinite-DV integrity and its
   report separate. A Stats export may reproduce QC-17 evidence for audit but
   must identify it as shared experimental review context.
8. Use identical project protocol and harmonic-profile inputs for provisional
   and canonical selection. First require QC-21's ROI-definition and workbook-
   source prevalidation, then calculate review evidence from the current
   eligible cohort/list. After reviewed exclusions, derive an in-memory
   candidate final list and recompute the summed-BCA screen against that exact
   list. Reopen review if the list, cohort, values, severity, or decision scope
   changes. When the loop stabilizes, run QC-21 final coverage and QC-20's final
   release gate; only then commit and publish the canonical final harmonic list.
   Detect a repeated/oscillating state and stop with an actionable error instead
   of silently accepting one pass.
9. Migrate prior automatic summed-BCA exclusions to preserved legacy machine
   suggestions that require review; do not keep them active merely because the
   old policy created them. Preserve explicit manual exclusions. Mark dependent
   outputs stale when the active inclusion state changes, but do not rewrite
   historical files merely on project open.
10. Fingerprint the feature state, thresholds, rates, QC-12 shared eligibility
    result, any fixed/preregistered subset, analyzed cycles/duration, harmonic list/count,
    recording/condition scope, evidence, and decision. Reports must call the
    defaults experimental and must not describe a retained observation as clean
    or an extreme value as artifact.
11. Label an exclusion based only on the displayed BCA outcome as
    outcome-informed and preserve the complete pre-exclusion audit value.
    Require the user's reason and supporting evidence. Confirmatory reporting
    must expose the corresponding included-versus-excluded sensitivity result,
    or state clearly that the outcome-informed exclusion makes that analysis
    exploratory; a mixed model does not remove this selection risk.

## Owners and Verification

Primary owners are project preprocessing/analysis settings and migration,
`gui/settings_panel.py`, `gui/frequency_domain_qc_dialog.py`, processing
workflows/workers, `processing/frequency_domain_qc.py`, harmonic-selection and
artifact-freshness owners, downstream exclusion consumers, and full-audit
exports. QC-03 owns recording-aware review; QC-10 owns nonfinite cells; QC-11
through QC-14 own protocol, harmonic, and neighboring-noise inputs. QC-15 stays
execution priority 1.

Cover exact threshold boundaries, five-cell and 11-electrode patterns, disabled
state, invalid settings, default retain, explicit condition/recording decisions,
repeated sessions, one-condition isolation, preserved manual exclusions, legacy
automatic migration, cohort-relative 6/10 scores and uV floors, ROI/cohort
fingerprints, missing/incomplete relative inputs, arbitrary rates and cycle
counts, final-list re-review, no duplicate Stats calculation, oscillation
failure, stale/current transitions, and full-audit visibility.
Verify that summed BCA alone never changes active inclusion. GUI behavior uses
static checks, CI-only Qt tests, and a documented visible smoke path.

Calibrate the defaults on representative BioSemi64 FPVS projects across rates,
cycle counts, profiles, harmonic counts, populations, and downstream outcomes
before considering stronger authority. Update the post-processing/statistics
architecture, calibration guidance, user QC guide, and methods-reporting
checklist. Summed BCA remains a defensible multiharmonic response measure; this
action limits the unvalidated interpretation of its magnitude as artifact
([Retter et al., 2021](https://doi.org/10.1162/jocn_a_01763),
[Keil et al., 2022](https://doi.org/10.1111/psyp.14052)).

## Implementation Evidence

Project experimental settings own the enabled state, method version, absolute
10/50/250 uV bands, five-cell and 11-electrode pattern counts, cohort robust
scores, and cohort floors. Validation enforces ordered positive amplitudes and
bounded electrode counts. The Settings GUI presents the review-only wording;
disabled runs are recorded as `not_performed`.

`processing/frequency_domain_qc.py` consumes canonical project protocol and
harmonic-selection inputs, emits exact recording/condition/electrode absolute
and cohort-relative evidence, preserves signed and absolute values and the
harmonic list, and never creates an automatic exclusion. The dialog begins
without a selected decision, requires a reason for every exclusion, and keeps
participant-wide exclusion as an explicit broader choice. The bounded
review/recompute loop rejects repeated states, reopens when current harmonic or
cohort evidence changes, and coordinates final coverage/release through the
public QC-20/QC-21 helpers before canonical harmonic publication.

Managed Stats runs now load the completed shared QC-17 decision fingerprint and
review evidence instead of calculating a separate fixed-rate BCA screen.
Exports retain the shared source, review-only authority, status, thresholds,
and fingerprint; nonfinite dependent-variable handling remains a separate
integrity rule. Projectless legacy Stats calls retain their compatibility path.

Focused non-Qt processing and static GUI checks cover arbitrary protocol
rates/cycles, thresholds and grouped patterns, disabled status, no automatic
authority, exact decision scope, legacy migration, evidence change,
oscillation protection, and final-gate order. Focused Stats checks cover reuse
of recording-aware QC-17 evidence, rejection of an incomplete review, no
independent managed-project calculation, and exported audit provenance. The
visible release smoke path is to toggle the project feature, review and retain
one finding, apply one reasoned condition/electrode exclusion, verify a changed
candidate harmonic list reopens review, and confirm Stats reports the same
review fingerprint without widening the exclusion.
