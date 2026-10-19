# Quality Score

Reviewed 2026-10-18. [V3.0.0 is published](https://github.com/zcm58/FPVS-Toolbox/releases/tag/v3.0.0)
as the latest stable, immutable release at the user's explicit direction.
The release uses the exact qualified `9f7480b4` installer; anonymous downloads
of all four release assets matched their verified checksums. Outstanding manual
checks remain unclaimed, and optional full-cohort investigations are stopped.

- The [v3 release ledger](../exec-plans/active/v3-release-readiness.md) owns
  published-artifact evidence, remaining manual acceptance, and explicit deferrals.
  Historical passing runs do not qualify a newer release commit or installer.
- Post-release source maintenance at `7b026c65` passed 7,614 local non-Qt
  tests (25 skipped) and [source CI](https://github.com/zcm58/FPVS-Toolbox/actions/runs/39133936133)
  passed 8,242 tests (24 skipped), including registered Qt coverage, plus Linux
  lint and Windows backend checks. The
  [agent harness](https://github.com/zcm58/FPVS-Toolbox/actions/runs/39133936110)
  passed. This qualifies that source revision, not a rebuilt installer.
- The bounded Settings/runtime ownership/workbook-adapter cleanup is complete.
  Larger module and exception-handler counts remain review signals in the debt
  tracker, not proof of defects or justification for arbitrary deletion.
- Modular hardware/montage support, capability-selected processing stages and
  full FPVS Studio interoperability are the agreed target in the
  [roadmap](../architecture/hardware-pipeline-studio-roadmap.md). Current Unicorn
  support is inspection/Raw-adapter/project-metadata groundwork; production
  processing and hardware qualification remain gated. End-to-end compatibility
  must be demonstrated per Studio schema/version, not inferred from import success.
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
- Outstanding qualification includes representative-project/manual installed-app
  acceptance. Additional private fresh-project/full-cohort and FHC preparation
  checks remain incomplete optional evidence, not newly imposed release blockers.
  Release identity and publication are complete. Later changes remain subject to CI.
- Public restoration is complete at `zcm58/FPVS-Toolbox`, with cleaned source
  history, verified historical installers, and deployed documentation. The
  original repository remains private with its retained PR/cached objects;
  those objects were not copied to the new repository.
- Follow [verification gates](verification-gates.md) for required checks and
  the [debt tracker](../exec-plans/tech-debt-tracker.md) for bounded maintenance.

No local Qt execution or manual installed-app/project acceptance is claimed here.
The completed hosted Windows lifecycle qualifies the exact published artifact
through automated checks; it does not establish human installed-app acceptance.
