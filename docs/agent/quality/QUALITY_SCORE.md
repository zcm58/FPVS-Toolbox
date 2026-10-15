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
- At `9f7480b4`, source CI passed 8,120 tests with 24 skips, including Qt
  coverage; lint, Windows backend, documentation deployment, and agent harness
  checks also passed. The local repository gate passed 7,487 non-Qt tests
  with 25 skips at `0442e882`, before the bounded
  native-driver changes; the subsequent focused updates gate passed 533 tests
  with four skips.
- The exact `9f7480b4` installer passed automated hosted Windows fresh install,
  launch/close/second launch, v2.1.2 upgrade, obsolete-file cleanup, interactive
  installer relaunch with process exit 0, and both uninstall/data-preservation
  paths. Source/frozen startup of eight default/beta pages, dependency probes,
  synthetic scientific workflows, and native ownership/rollback fixtures passed.
  Independent artifact downloads verified the installer bytes and checksum
  sidecars against the acceptance receipt. The release ledger links the exact
  run, artifact IDs, SHA-256, and qualification limits; no manual human review
  or representative-project scientific acceptance is inferred from these probes.
- Two private recordings passed baseline/current scientific-output comparison;
  prepared-cache results matched and warm resume repeated no work. A historical
  prepared FHC replay also matched its scientific arrays and result, with
  cancellation/non-overwrite checks passing. These bounded receipts do not
  qualify fresh project preparation or the current full cohort.
- Open qualification includes representative-project/manual installed-app
  acceptance, private fresh-project/full-cohort and FHC preparation checks,
  and final release identity/publication. Later changes remain subject to
  final-commit CI.
- Public restoration is complete at `zcm58/FPVS-Toolbox`, with cleaned source
  history, verified historical installers, and deployed documentation. The
  original repository remains private with its retained PR/cached objects;
  those objects were not copied to the new repository.
- Follow [verification gates](verification-gates.md) for required checks and
  the [debt tracker](../exec-plans/tech-debt-tracker.md) for bounded maintenance.

No local Qt execution or manual installed-app/project acceptance is claimed here.
The completed hosted Windows lifecycle is automated qualification of the exact
retained artifact, not stable release publication.
