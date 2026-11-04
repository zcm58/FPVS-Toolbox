# LORETA scientific integrity and reproducibility

Status: implementation and automated source verification complete, 2026-11-04.
Retained at the user's request for checkpointed handoff; visible/CI Qt acceptance
remains below. The user authorized this plan and its implementation after the
code/literature review.

## Resume here

1. Read root and tool `AGENTS.md`, this plan's checkpoint table, and `git status`.
   Preserve concurrent edits. Do not restart completed checkpoints.
2. Start/renew the root task's bounded keep-awake helper; credentials stay in
   task context, never this repository. Subagents reuse the parent's request.
3. Use `.venv1`, otherwise `.venv`. Never run local Qt/offscreen workflows,
   download templates, inspect real projects, or access `Standalone_Scripts`.
4. Read only the checkpoint's owners and failing tests. Update its evidence and
   next action before a context transition. Unfinished verification is not a pass.
5. A scientific limitation is resolved by correct behavior, explicit scope and
   measured evidence, not by claiming an unperformed experiment succeeded.

There is no unfinished source implementation. Resume only the unperformed
acceptance below in an authorized environment, or investigate a new finding.

## Scope and acceptance

Address every finding in the November LORETA review: nontransactional builds,
stale/mixed results, lost adaptive-selection provenance, inaccurate Hauk
attribution, undefined source Z encoded as data, unqualified cluster inference,
missing numerical-reference coverage, insufficient model/rank/resolution
diagnostics, and ambiguous lateralization interpretation.

Keep the current EEG-only BioSemi64/fsaverage L2 cortical-normal and eLORETA
complex-vector inverses. Preserve signed repetition averaging, exact FFT bins,
accepted harmonic lists, locked neighboring-bin rule, source-ready FIFs,
independent methods, and all sensor-processing/Stats contracts. Do not silently
switch to Hauk's historical orientation pooling, alter source regularization,
invent empirical noise recordings, or add individual-MRI/MEG support.

The user's request authorizes a versioned source-validity policy and honest
qualification of source inference. It does not require a new unvalidated test
to replace another. Historical saved outputs remain distinguishable/readable;
new exports must not imply calibrated population inference where evidence is
absent. A bounded synthetic experiment never establishes clinical or real-data
localization accuracy.

## Evidence and starting state

- Review baseline: clean source tree; focused LORETA gate previously passed
  455 tests. Repeat once at execution start; record the actual result below.
- Partial manual rebuild loads every existing default manifest, including a
  failed method's older result (`gui.py` callback).
- Generic writers overwrite stable payload names before their final manifest;
  an injected second-write failure produced a manifest referencing mixed runs.
- `project_source_psd_inputs._resolve_selected_harmonics` overwrites
  `exploratory=False`, losing canonical same-sample adaptive provenance.
- `compute_hauk_source_zscores` encodes undefined/near-zero-noise scores as zero.
- A 200,000-spectrum Rayleigh probe through that helper returned mean Z
  0.08040 (SE 0.00316), skew 0.774. This challenges a zero-centered symmetric
  null but is not a measured full-pipeline false-positive rate.
- Hauk 2025's declared code is `olafhauk/FPVS_WORDS`, commit
  `f9628b088f181e2b5afeabba9fc167d42140b5a3`. It averages signed repetitions,
  uses MNE source PSD/Hann, takes square roots, sums harmonic windows and then
  computes neighboring-bin Z. It omits `pick_ori`; cortical-normal output is
  a Toolbox adaptation. Imported `config_fpvswords.py` is absent publicly.
- Hauk 2021's `FPVS_sweep` submission snapshot has configuration discrepancies
  and a discarded `np.delete` result; do not copy that bug for fidelity.

Primary references: [Hauk 2025](https://doi.org/10.1162/imag_a_00414),
[2025 code](https://github.com/olafhauk/FPVS_WORDS/tree/f9628b088f181e2b5afeabba9fc167d42140b5a3),
[Hauk 2021](https://doi.org/10.1016/j.neuroimage.2021.118460),
[Hauk 2022 resolution](https://doi.org/10.1016/j.neuroimage.2022.119177),
[sign-flip assumptions](https://pmc.ncbi.nlm.nih.gov/articles/PMC4010955/),
[selection independence](https://pmc.ncbi.nlm.nih.gov/articles/PMC2841687/).

## Checkpoints

| ID | State | Deliverable / restart boundary |
| --- | --- | --- |
| C0 | Complete | Plan saved; protected/path/GUI audits pass; focused baseline 455 passed in 43.59 s. |
| C1 | Complete | Transactional bundles/receipts, input/cohort freshness, worker discovery and partial-load isolation; 101 owned tests and independent late-QC rollback reproduction pass. |
| C2 | Complete | Canonical adaptive provenance retained; Hauk attribution, method disclosures and references corrected without changing inverse defaults. |
| C3 | Complete | Validity v1, cache v2, complete cohort support, JSON nulls and missing display/ROI regions; numerical, cache, payload and volume regressions pass. |
| C4 | Complete | Frozen native-MNE reference; 512-cohort spectral receipt with exact uncertainty and source hashes; source inference explicitly remains exploratory. |
| C5 | Complete | Measured participant rank, archived native PSF/CTF/noise/gain diagnostics and unmasked mean-absolute-Z ROI summaries with missing-support labels. |
| C6 | Automated complete | LORETA 554 passed; project I/O 1,208 passed / 14 skipped; GUI 721 passed; figures 4 passed; repo 471 passed / 1 skipped; docs/audits pass. Visible/CI Qt acceptance remains. |

### C0 — Establish the executable baseline

Run the LORETA focused gate and protected/path/GUI audits before broad inspection.
Read the tool architecture, source-PSD plan, validated-improvements plan and
Stats consumer contract. Record baseline failures before changes. Add this plan
to routing. Implementation begins only after this plan is saved.

### C1 — Publish and discover coherent results

Owners: new tool-local publication/discovery helper; the two project source-PSD
exporters; GUI source workers/callbacks; narrow Main App post-processing adapter.
Generic numerical writers remain reusable and write inside a staging directory.

1. Create a sibling staging directory under the active project output parent.
   Write all payloads, manifest, participant sidecar, lateralization files and
   reports there. Validate before publication. Do not touch the previous result
   while computation or serialization can fail.
2. Publish a complete method bundle with rollback around directory replacement.
   Keep an existing valid bundle intact on exceptions/cancellation; preserve
   completed sibling methods. Check cancellation before publication, never
   interrupt a directory transaction midway. Handle existing target, first
   build, rename failures and Windows path containment explicitly.
3. Add a versioned receipt with build identity, method/options, selection and
   condition-cohort/input identity, and hashes of published files. Rebase returned
   paths to final output. Exclude transient staging paths from durable metadata.
4. Reconcile the shared artifact registry; avoid competing pipeline pre-delete
   and exporter transaction owners. Current discovery must check selection
   freshness and bundle integrity. Historical explicit import stays possible
   with historical/unverified provenance rather than silently becoming current.
5. After partial success, the GUI loads only successful result manifests from
   that attempt. Never attach an unsuccessful sibling merely because its old
   path exists. Keep a meaningful partial-failure message.

Acceptance: fault injection before/after payload writes, before manifest/report,
and at publication leaves the preceding bundle byte-consistent. Successful
publication has final paths and valid hashes. Changed selection, changed/missing
payload, and stale sibling cannot auto-load. Temporary roots only; non-Qt callback
tests and CI-only Qt coverage as warranted.

### C2 — Preserve scientific provenance and correct attribution

Owners: source input adapter, method information/options, tool/user/agent docs.

- Preserve canonical `exploratory`/`same_sample_adaptive`, exact selected list
  and fingerprint. Do not calculate selection in LORETA or alter shared Stats.
- Describe cortical-normal output as an explicit Toolbox choice. Cite the
  correct pinned 2025 repository; distinguish paper, executable code and missing
  configuration. Keep existing inverse IDs and default numerical parameters.
- Report cluster family as one group-condition-method map, shared mean-t mask
  across display summaries, and no condition/group contrast. State the actual
  forming threshold/tail and separate source Z from Gaussian p-values.
- Keep the main page compact. Put methods/qualification details in existing
  options, tool information and source validation reports.

Acceptance: adaptive/fixed provenance regressions; no incorrect “closer to Hauk”
claims in affected current docs; strict docs build and link/owner checks.

### C3 — Make undefined source measurements explicit

Owners: source-PSD calculation/result, cache, generic L2/eLORETA writers,
participant sidecar, payload validation/import/display and lateralization.

1. Add a versioned validity policy and persist a per-participant source-validity
   mask. A score with undefined neighboring-noise SD is missing, never an observed
   neutral zero. Finite valid scores remain numerically unchanged.
2. Prefer common valid source support within each group-condition cohort for
   group summaries and inference, retaining fixed participant N and source
   adjacency/index identity. Record participant validity and common-support
   exclusions/counts. Fail clearly when no valid support remains; do not silently
   reduce N independently per vertex or bridge excluded adjacency locations.
3. Preserve the full source geometry. If finite placeholder values are required
   by the existing payload format, explicitly mark them invalid and exclude them
   from summaries, cluster tests, ROIs, color limits and all render/export paths,
   including when the statistical mask is disabled.
4. Include policy identity in numerical cache keys and retain old saved-output
   semantics. Never reuse old zero-filled caches under the new policy. Historical
   inputs without validity metadata remain explicitly historical.

Acceptance: isolated invalid source, different invalid participants, all-invalid
support, sparse adjacency, single participant, legacy payload and cache isolation
tests. Valid reference calculations retain their expected values. Display tests
must prove “mask off” cannot reveal an invalid placeholder.

### C4 — Reproducibility and inference qualification

Owners: source-producer validation/calibration modules, source statistics
metadata, tests/fixtures, validation report and method disclosures.

1. Check in a small deterministic native-MNE numerical reference requiring no
   downloads or real data. Cover signed/complex inputs, normal/vector output,
   odd/even sample counts, source amplitudes, summed windows and Z. Record fixture
   generation settings/dependency versions and tolerances; avoid a test that
   merely computes expected values with the same function under test.
2. Provide a reproducible, seeded, bounded offline null/sensitivity runner using
   signed synthetic EEG, periodic Hann, actual inverse kernels, the production
   Z helper and production cluster engine. Include realistic cohort sizes,
   spatial/temporal correlation, fixed harmonic domains and explicitly scoped
   adaptive-selection stress scenarios; label any simplification accurately.
3. Record rejection counts, binomial uncertainty, invalid support, signal
   recovery, seed, configuration and dependency versions. Separate conditional
   sign-symmetric engine tests from the spectral-pipeline experiment. Run a
   practical bounded experiment; keep expensive experiments out of routine CI.
4. Existing sign-flip masks remain explicitly exploratory/unqualified for the
   spectral null unless a documented matching validation establishes the needed
   assumptions/error control. Neither a small successful simulation nor a
   reference paper grants automatic qualification. Preserve numerical p-values
   as algorithm outputs with their scope, not universal significance claims.
5. Adaptive selection must retain its additional post-selection qualification.
   Do not implement a guessed replacement statistical method or modify the
   locked processing selection to make a diagnostic pass.

Acceptance: executable reference/regression tests; archived compact synthetic
evidence and exact rerun command; qualifications visible in prepared outputs,
existing report/info surfaces and methods documentation. No empirical/whole-brain
FWER claim beyond the actual diagnostic design.

### C5 — Model diagnostics and lateralization interpretation

Owners: model diagnostics/recovery benchmark, source lateralization/reporting.

- Record a computable participant-data rank diagnostic separately from inverse
  covariance rank, including tolerance/reference/interpolation limitations.
  Validate channel/reference/geometry consistency against admitted inputs;
  reject an established mismatch, never infer qualification from names alone.
- Extend recovery evidence beyond isolated peak error: spread, cross-talk and
  representative noise/model-perturbation sensitivity where supported by the
  available model. Clearly distinguish a synthetic perturbation from empirical
  anatomy/electrode accuracy. Preserve template and ad-hoc covariance defaults.
- Retain the existing descriptive positive/masked-sum laterality output with
  explicit policy/family labels. Add separately named anatomical, unmasked
  participant mean-absolute-Z summaries with source counts/validity and clear
  left/right convention, matching the stated Hauk-style quantity more closely.
  Do not add an unvalidated subsequent inferential test on selected clusters or
  claim a normalized index reproduces Hauk's reported comparison.

Acceptance: diagnostic rank tests on known-rank arrays; leakage/sensitivity
fixtures; ROI vertex/hemisphere identity, differing ROI sizes, invalid support,
mask independence and zero-denominator tests. Record measured model evidence
without qualifying new hardware, individual MRI or observed participant accuracy.

### C6 — Integrate, verify and hand off

- Review all cross-owner interfaces and failures. Check historical payload/cache
  compatibility, cancellation, current selection/cohort provenance, partial
  rebuilds, final path containment and no GUI-thread numerical work.
- Run `python .agents/scripts/verify.py --scope loreta --tier focused`, affected
  GUI/project/export scopes, then `--scope repo --tier precommit`. Run strict
  MkDocs, agent-doc links/owners and `git diff --check`. Inspect the final diff.
- Manual/CI smoke: visibly open an existing project, rebuild both methods,
  cancel/fail the second, verify only successful fresh results load; invalidate
  selection and verify old results do not auto-load; inspect historical import,
  qualification details, invalid-source visibility, all summary/mask states and
  figure exports. Qt/renderer execution stays in CI or a user-approved visible
  environment; document unexecuted human acceptance honestly.
- Keep this requested resumable plan with dated checkpoint evidence and any
  remaining human/empirical acceptance. Update canonical tool architecture,
  user methods and agent routing, keeping entry-point docs concise.
- Commit/push only if authorized for this execution; do not infer a new publish
  request from the earlier completed maintenance tasks. Report modified files,
  measured checks and remaining scientific limits without declaring universal
  scientific correctness.

## Execution ledger

- 2026-11-04 C0: plan saved before implementation. Protected, source-boundary,
  path and GUI audits passed. Fresh focused baseline: 455 passed. Parent owns docs,
  payload/display integration and final gates; delegated owners cover publication,
  numerical validity, and scientific diagnostics/reference validation.
- 2026-11-04 C1–C3: staged receipts include final paths, file/input hashes and
  canonical cohort/QC identity. Independent fault injection found and verified a
  late-QC race fix under the commit lock. GUI discovery is asynchronous and only
  loads successful current batches. Undefined Z remains missing through full
  source geometry, complete-cohort statistics, JSON, caches and both render paths.
- 2026-11-04 C4–C5: frozen independent native-MNE reference and diagnostic tests
  pass; all new masks explicitly retain exploratory qualification. Resolution
  receipt is `docs/agent/quality/data/loreta-native-resolution-2026-11-04.json`.
  Unmasked anatomical ROI means are descriptive; absent hemisphere support cannot
  produce a laterality index. The 64-null/16-signal-per-scenario, 24-participant
  spectral run completed in 1,190.53 s. Receipt:
  `docs/agent/quality/data/loreta-source-spectral-2026-11-04.json`. All four
  recorded numerical source hashes matched the final source. White/correlated
  null cells had 0/64 rejections for both methods; simplified adaptive stress had
  0/64 L2 and 1/64 eLORETA. Each signal cell had 16/16 detections, with material
  peak-location displacement. Interpret only within the documented design and
  uncertainty; no inference qualification was promoted. The atomic checkpoint
  remains under ignored `.codex-tmp/`; the durable receipt is self-contained.
- 2026-11-04 C6 source gates: final LORETA run passed 554 tests; GUI, figures,
  project I/O and repository gates passed with the counts above. Independent
  review also reproduced/fixed a historical-null-validity report edge and missing
  hemisphere ROI comparison. Final receipts and rerun commands are linked from
  `docs/agent/quality/loreta-validation.md`. Local Qt/renderer and real-project
  manual acceptance have not run and must not be reported as complete.

## Remaining acceptance

The later [rendering review](loreta-rendering-quality.md) exercised visible
synthetic anatomy, interaction and exports with explicit user approval. It does
not replace the project publication/failure or empirical checks below.

- CI owner: run the registered LORETA Qt cases on the final source revision;
  historical CI runs do not qualify these changes. No local offscreen substitute.
- Visible reviewer: follow `docs/agent/quality/loreta-validation.md`, especially
  partial/cancelled builds, stale cohort/selection rejection, historical import,
  missing-source rendering/exports and report disclosures. Record environment,
  fixture and outcome here; fix a failure before marking that check complete.
- Scientific qualification is a separate study: empirical covariance/anatomy,
  the complete locked adaptive selector, and population/family error control
  remain unqualified. Do not rerun private projects or promote exploratory masks
  solely because this synthetic experiment and source tests passed.
