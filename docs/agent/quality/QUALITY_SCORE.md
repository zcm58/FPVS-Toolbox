# Quality Score

Reviewed 2026-10-15. V3 is in release qualification; it is not yet cleared for
stable publication.

- The [v3 release ledger](../exec-plans/active/v3-release-readiness.md) owns
  current blockers, accepted scope, evidence, and explicit post-v3 deferrals.
  Historical passing runs do not qualify a newer release commit or installer.
- Active plans remain for QC/performance, source visualization, project/tool
  integration, acquisition support, and visible acceptance. Implemented features
  with pending manual review remain marked as pending. Completed implementation
  plans are removed only after their contracts and remaining release checks
  have a durable owner.
- At `0442e882`, source CI passed 8,114 tests with 24 skips, including Qt
  coverage; lint, Windows backend, documentation deployment, and agent audits
  also passed. The local repository gate passed 7,487 non-Qt tests with 25 skips.
  Native frozen checks, fresh installation, and the v2.1.2 upgrade passed;
  interactive installer relaunch timed out, so complete lifecycle acceptance
  remains open. The release ledger links the exact runs and their limits.
- Two private recordings passed baseline/current scientific-output comparison;
  prepared-cache results matched and warm resume repeated no work. A historical
  prepared FHC replay also matched its scientific arrays and result, with
  cancellation/non-overwrite checks passing. These bounded receipts do not
  qualify fresh project preparation or the current full cohort.
- Open qualification includes the complete Windows installer lifecycle,
  installed-app acceptance, fresh-project/full-cohort checks, and final release
  identity/publication. Later changes remain subject to final-commit CI.
- Public restoration is complete at `zcm58/FPVS-Toolbox`, with cleaned source
  history, verified historical installers, and deployed documentation. The
  original repository remains private with its retained PR/cached objects;
  those objects were not copied to the new repository.
- Follow [verification gates](verification-gates.md) for required checks and
  the [debt tracker](../exec-plans/tech-debt-tracker.md) for bounded maintenance.

No local offscreen Qt run or full native/project acceptance is claimed here.
