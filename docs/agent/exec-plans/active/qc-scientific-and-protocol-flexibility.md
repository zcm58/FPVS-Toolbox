# QC Scientific Review and Protocol Flexibility

## Status and Use

The scientific review is complete and twenty-one QC actions are approved.
Implementation started on 2026-09-04 on branch
`codex/qc-scientific-protocol-v3`, based directly on v3 release commit
`f586652e0bf9920eb42ce9e8a75b5b08f2717f31`. QC-15 is execution priority 1
and blocks the other planned changes.

For future execution, read only:

1. this index;
2. [shared execution contracts](qc-scientific-and-protocol-flexibility/00-shared-contracts.md); and
3. the action module being executed; and
4. only the dependency modules that action explicitly names.

Use the [review record](qc-scientific-and-protocol-flexibility/review-record.md) only when original evidence or a settled decision must be revisited. The separate [analysis-window preprocessing investigation](../future/analysis-window-preprocessing-scope.md) remains the authority for unresolved FIR/notch/resampling boundary questions.

## Objective and Global Boundaries

Make QC scientifically interpretable and support projects beyond 6 Hz presentation, 1.2 Hz oddball, and 120-second conditions. Preserve the locked preprocessing order, current continuous-Raw interpolation application, project data formats, and versioned harmonic-selection contracts unless a later approved action explicitly changes them. Do not access `src/Standalone_Scripts/**`, recreate retired packages, or run local offscreen Qt tests.

Automation should produce reproducible measurements and suggestions. The approved review policies reserve uncertain scientific inclusion/exclusion decisions for an explicit user choice with evidence and provenance. This does not convert every automated operation to manual review.

## Approved Action Index

| Action | Accepted result | Primary dependencies | Wave/stage | Module |
| --- | --- | --- | --- | --- |
| QC-15 | Make project-owned BioSemi ActiveTwo 64 the sole montage; identify affected legacy outputs | SC-05, SC-06, SC-07, SC-09 | **0: priority 1** | [BioSemi64 geometry](qc-scientific-and-protocol-flexibility/qc-15-biosemi64-geometry.md) |
| QC-16 | Auto-interpolate corroborated kurtosis findings; review kurtosis-only findings in the GUI | QC-04, QC-06, QC-15; SC-04, SC-05, SC-06 | 2 | [Kurtosis decision gate](qc-scientific-and-protocol-flexibility/qc-16-kurtosis-decision-gate.md) |
| QC-17 | Make fixed summed-BCA bands project-owned experimental GUI review flags | QC-03, QC-10 through QC-15, QC-20 pre-review gate, QC-21 prevalidation; SC-01, SC-04, SC-06, SC-09 | 4 review | [Experimental summed-BCA review](qc-scientific-and-protocol-flexibility/qc-17-experimental-summed-bca-review.md) |
| QC-18 | Keep raw-spectral screening experimental; retain notch filtering and make affected target/noise frequencies unavailable | Screen: QC-02, QC-06, QC-11, QC-12 rate/target foundation, QC-13, QC-15, QC-19; eligibility: finalized QC-12 and QC-14; SC-02, SC-04, SC-06, SC-09 | 2 screen; 4 eligibility | [Experimental raw-spectral review](qc-scientific-and-protocol-flexibility/qc-18-experimental-raw-spectral-review.md) |
| QC-19 | Make oddball marker identity project-owned; pause occurrences with unexplained marker loss for GUI review | QC-02, QC-11, QC-12 rate foundation, QC-13; SC-01, SC-02, SC-04, SC-06, SC-09 | 1 | [Project marker integrity](qc-scientific-and-protocol-flexibility/qc-19-project-marker-integrity.md) |
| QC-20 | Require every expected recording-condition to have a current validated output or an explicit no-output state | Ledger: QC-02, QC-19; receipts: QC-10 through QC-15; pre-review: QC-21 prevalidation; final release: QC-03, QC-17, QC-21 final | 1 ledger; 3 receipts; 4 gates | [Recording-condition completeness](qc-scientific-and-protocol-flexibility/qc-20-recording-condition-completeness.md) |
| QC-21 | Require complete fixed canonical electrode membership and complete whole-scalp normalization denominators | Prevalidation: QC-02, QC-07, QC-10, QC-15, QC-20 ledger; final coverage: QC-03, QC-09, QC-16, QC-17, QC-20 pre-review | 1 validators; 4 final | [Fixed ROI coverage](qc-scientific-and-protocol-flexibility/qc-21-fixed-roi-coverage.md) |
| QC-01 | Five-second transient windows with 50% overlap, jointly recalibrated | QC-06 | 2 | [Transient screening](qc-scientific-and-protocol-flexibility/qc-01-transient-screening.md) |
| QC-02 | Truthful Preprocessing QC Report with actual stage/interpolation outcomes | SC-01, SC-05, SC-06 | 1 foundation; 3 finish | [Preprocessing report](qc-scientific-and-protocol-flexibility/qc-02-preprocessing-report.md) |
| QC-03 | Review and decide frequency-QC findings by recording/session | SC-01, SC-04; QC-10 and QC-20 pre-review gate before final review | 1 identity; 4 finish | [Recording-aware frequency review](qc-scientific-and-protocol-flexibility/qc-03-recording-aware-frequency-review.md) |
| QC-04 | Experimental removed-electrode detector, Off by default, reliable opt-out | QC-01, QC-06, QC-15 before calibration; SC-03, SC-06 | 1 settings; 2 finish | [Experimental detector](qc-scientific-and-protocol-flexibility/qc-04-experimental-electrode-detector.md) |
| QC-05 | Severe raw amplitude becomes a review flag with brief BioSemi help | QC-06; SC-04 | 2 | [Amplitude review](qc-scientific-and-protocol-flexibility/qc-05-amplitude-review.md) |
| QC-06 | All signal-based QC scores only exact analyzed intervals | QC-19; SC-02, SC-06, SC-07 | 2 | [Analyzed intervals](qc-scientific-and-protocol-flexibility/qc-06-analyzed-intervals.md) |
| QC-07 | Report successful scalp interpolation burden; review above 5% | QC-02, QC-15; SC-05 | 3 | [Interpolation burden](qc-scientific-and-protocol-flexibility/qc-07-interpolation-burden.md) |
| QC-08 | Candidate burden/hemisphere/cluster thresholds become evidence-based review flags | QC-04, QC-05, QC-06, QC-09; SC-04 | 2 | [Candidate burden review](qc-scientific-and-protocol-flexibility/qc-08-candidate-burden-review.md) |
| QC-09 | Prominent electrode warnings scoped to condition and occurrence | QC-04, QC-06; SC-01 | 2 | [Condition-specific warnings](qc-scientific-and-protocol-flexibility/qc-09-condition-specific-warnings.md) |
| QC-10 | Nonfinite computable BCA output is a technical integrity failure; no partial sums | QC-12/QC-14 spectral eligibility; SC-05, SC-06 | 3 source; 4 spectral | [BCA integrity](qc-scientific-and-protocol-flexibility/qc-10-bca-integrity.md) |
| QC-11 | One project-owned presentation/oddball-rate protocol with no universal BCA ceiling | SC-06, SC-07 | 1 | [Project frequency protocol](qc-scientific-and-protocol-flexibility/qc-11-project-protocol.md) |
| QC-12 | Generalize rates and replace legacy ceilings with one project-filter-derived harmonic-eligibility source | Rate foundation: QC-11; domain finalization: QC-14; SC-06, SC-07 | 1 protocol; 4 domain | [Rate generalization](qc-scientific-and-protocol-flexibility/qc-12-rate-generalization.md) |
| QC-13 | One expected analyzed oddball-cycle count per project | QC-11, QC-12 rate foundation; SC-02, SC-06 | 1 | [Expected analyzed cycles](qc-scientific-and-protocol-flexibility/qc-13-expected-cycles.md) |
| QC-14 | Keep +/-10-bin noise method; require complete uncontaminated support | QC-12 rate foundation, QC-13; SC-06, SC-07 | 4 | [Noise-window applicability](qc-scientific-and-protocol-flexibility/qc-14-noise-window-applicability.md) |

These waves are the execution baseline. Shared foundations may be implemented
together, but each action retains its own acceptance criteria and provenance.

## Compact Decision Ledger

| Item | Disposition |
| --- | --- |
| 1 | No action: keep header-only/recording-not-started detection and likely lab explanation. |
| 2 | No action: keep condition-aware cache identity; future protocol inputs must reach it. |
| 3 | QC-01 approved. |
| 4 | No action: keep post-preprocessing metadata checks warning-only. |
| 5 | No action to the shared-list safeguard: preserve canonical harmonics, exact selected-column failures, and stale-output guards. QC-10 through QC-14 and QC-17 resolve the later integrity, rate, and selection questions. |
| 6 | No action: preserve canonical dataset identity and recording-specific manual override precedence. |
| 7 | No action: preserve original automatic suggestions separately from user decisions. |
| 8 | No action: preserve original spectra and separate exclusion metadata/full-audit visibility. |
| 9 | No additional action: preserve bounded condition buffering, concurrency, cancellation, and cleanup. |
| 10 | QC-02 approved. |
| 11 | QC-03 approved. |
| 12 | QC-04 approved, including existing-project migration and amplitude separation. |
| 13 | QC-05 approved. |
| 14 | QC-06 approved. |
| 15 | Bad-channel decisions use analyzed intervals; interpolation application stays unchanged. Temporal processing remains in the separate investigation. |
| 16 | No separate montage editor or repair-retry workflow. QC-15 later supersedes the earlier permissive geometry handling and blocks unsupported or mismatched geometry. |
| 17 | QC-07 approved. |
| 18 | QC-08 approved. |
| 19 | No additional action: retain same-category/all-observed-occurrences persistence for recording-wide experimental nomination; occurrence visibility handled by QC-09. |
| 20 | No action to dynamic base-overlap exclusion. QC-11/QC-12 own canonical input propagation and QC-14 owns exact-bin applicability. |
| 21 | QC-09 approved. |
| 22 | QC-10 approved. |
| 23 | No action to marker-derived duration or exact-bin truncation. QC-13/QC-14 define expected cycles, heterogeneous-span handling, and duration-dependent noise applicability. |
| 24 | QC-11 corrected: one project-wide presentation/oddball-rate protocol with no per-condition overrides and no universal 16.8-Hz analysis ceiling. |
| 25 | QC-12 accepted in direction: support non-6/1.2 projects and both recurrence-count and direct oddball-Hz entry. |
| 26 | QC-12 finalized: direct oddball-Hz entry must resolve to a whole-number recurrence and cannot be silently rounded. |
| 27 | QC-13 accepted in direction: one project-wide expected oddball-cycle count, imported from FPVS Studio or required during manual setup. |
| 28 | QC-13 finalized: expected analyzed cycles are complete FFT cycles; presentation/marker counts remain separate. |
| 29 | QC-14 approved: retain +/-10 bins and add edge, finite-support, cycle-count, and tagged-harmonic applicability guards. |
| 30 | QC-15 approved as execution priority 1: project-owned BioSemi ActiveTwo 64 is the sole supported montage; replace `standard_1005`, prevent geometry mixing, and assess legacy interpolated outputs. |
| 31 | QC-16 approved: kurtosis plus an eligible independent method permits automatic interpolation; kurtosis alone requires GUI review. |
| 32 | No action: preserve exact BCA-column validation, fingerprints/stale-output guards, original outputs, provenance separation, and recording-aware backend identity. |
| 33 | QC-17 approved: preserve the rough 10/50/250 uV and count defaults as project-owned experimental GUI review flags; summed BCA alone cannot exclude data. |
| 34 | No additional action: preserve exact FullFFT grid validation and explicit/manual condition exclusions; QC-12/QC-13 own rate and expected-cycle generalization. |
| 35 | No action: preserve the four versioned harmonic profiles and canonical selection/freshness safeguards as analysis-method identity. |
| 36 | No action: preserve the Stats DV screen that flags finite extremes and excludes only nonfinite, unusable derived values. |
| 37 | QC-17 expanded: consolidate the Stats cohort-relative BCA screen into the same experimental GUI review and canonical final-harmonic state. |
| 38 | QC-04 expanded: retain detector percentages as internally validated in-lab results with a reproducible calibration receipt; rerun them after method changes. |
| 39 | No additional action: retain explicit Continue/Cancel when preflight scanning is unavailable, but QC-02 must report `not evaluated` and the reason. |
| 40 | QC-18 approved: raw-spectral screening is a project-owned experimental, review-only feature; its thresholds are provisional and notch/FPVS conflicts are visible. |
| 41 | QC-19 approved: use one project-owned oddball marker code, default 55; remove code guessing and broad silent deduplication; pause occurrences with unexplained missing markers for GUI review. |
| 42 | QC-20 approved: require every expected recording-condition to be accounted for, while allowing documented exclusions/unavailability and partial occurrence retention without requiring a workbook for excluded cells. |
| 43 | QC-21 approved: primary ROI values require their complete fixed unique electrode set; successfully interpolated members count as present, while a valid excluded member makes only the affected ROI cell unavailable. |
| 44 | QC-21 expanded: if any member of the fixed whole-scalp normalization set is unavailable, all normalized ROI derivatives for that recording-condition are not calculated; unaffected complete raw ROI values remain available. |
| 45 | QC-11/QC-12 corrected: 16.8 Hz is a legacy application default, not an approved or scientifically universal ceiling. Retain an old artifact's actual boundary only as historical provenance, never as current behavior. |
| 46 | QC-12 finalized: remove the live 16.8-Hz default, generic ceiling control, competing 40-Hz fallback, and independently rebuilt target lists. One shared resolver supplies exact eligible harmonics whose complete +/-10-bin neighborhoods lie within the project's applied filter range and Nyquist. |
| 47 | QC-18/QC-12/QC-14 finalized: keep every configured effective line-noise notch even when it overlaps a base/oddball target. Mark a notched target or a standard score whose required noise bin is notched as unavailable; do not exclude the recording-condition or count the unavailable harmonic as an adaptive failure. |

## Review Complete

No QC decisions remain open. Configured effective line-noise notches stay in
place regardless of overlap with base/oddball harmonics. The affected harmonic
or noise-based metric is unavailable rather than interpreted from attenuated
data; the remaining recording-condition data stay eligible.
The separate FIR/notch/resampling
[analysis-window investigation](../future/analysis-window-preprocessing-scope.md) remains
open as future evidence work and authorizes no temporal-method change. Per-file
scan acknowledgement and neutral FullFFT provenance require no separate action
beyond QC-02 and the existing freshness contracts.

## Execution Waves

0. **Priority 1 geometry correction:** implement QC-15 before every other action; version legacy outputs and complete the sensitivity/reprocessing assessment.
1. **Protocol and identity foundation:** implement QC-11, the rate-foundation portion of QC-12, QC-13, and QC-19 in that order; add QC-04 and QC-17 settings/schema/migration foundations, QC-02/QC-03 foundations, the QC-20 expected ledger, and QC-21 ROI/source validators.
2. **Analyzed-interval signal QC:** implement QC-06 from QC-19-approved spans, then QC-01 and QC-05; finish QC-04's On/Off authority wiring before QC-09, QC-08, QC-16, and QC-18; run QC-04 empirical recalibration after those behaviors are final.
3. **Outcomes and integrity:** finish QC-02; implement QC-07 and QC-10; add QC-20 atomic output receipts and core cell states.
4. **Frequency and ROI finalization:** apply QC-14, then finish QC-12's harmonic-domain replacement and QC-18's deterministic notch-collision availability; run QC-21 definition/source prevalidation and QC-20's pre-review readiness gate; finish QC-03; allow QC-17's bounded provisional selection/review/recomputation loop; apply decisions; run QC-21 final coverage; then pass QC-20's final release gate before harmonic selection finalizes and feeds Stats or primary exports.
5. **Integration:** migrations, cache/fingerprint invalidation, cross-module regression, documentation, and visible manual smoke paths.

## Implementation Progress

| Stage | Status | Current evidence / next gate |
| --- | --- | --- |
| Plan activation and v3 branch baseline | Complete | Active plan moved onto `codex/qc-scientific-protocol-v3` at the exact v3 release base; documentation validation precedes the first source change. |
| Wave 0: QC-15 BioSemi64 geometry | In progress | Baseline protected-boundary audit passes; implementing the canonical loader/settings/provenance identity before focused processing and legacy-impact checks. |
| Wave 1: protocol and identity foundation | Not started | Blocked by Wave 0. |
| Wave 2: analyzed-interval signal QC | Not started | Blocked by Waves 0-1. |
| Wave 3: outcomes and integrity | Not started | Blocked by required earlier foundations. |
| Wave 4: frequency and ROI finalization | Not started | Blocked by Waves 0-3. |
| Wave 5: integration and handoff | Not started | Requires every action-level gate and final repository verification. |

## Completion Gate

- [x] Record approved actions QC-01 through QC-21 in separate executable modules.
- [x] Separate shared contracts and extended review evidence from the execution index.
- [x] Complete the final remaining decision and append it.
- [x] Reconcile approved actions with the waves and module dependencies after the final decisions.
- [x] Give every approved behavior an owner, migration rule, acceptance checks, and required documentation.
- [x] Move the finalized index and modules to `active/` together when implementation begins.
- [ ] Implement by wave, reading the current module, this index, shared contracts, and only its named dependency modules.
- [ ] Run focused gates per action and the repository precommit gate once at integrated handoff.
