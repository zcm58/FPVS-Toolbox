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
- Current local evidence includes 440 LORETA tests (eight graphics-guard tests),
  511 updater tests with four
  skips, and 655 non-Qt GUI tests, plus dependency and frozen synthetic-workflow
  checks. Native Windows source startup passed for eight real tool windows;
  the frozen artifact remains in qualification. These are scoped results,
  not a substitute for full release CI.
- Two private recordings passed baseline/current scientific-output comparison;
  prepared-cache results matched and warm resume repeated no work. A historical
  prepared FHC replay also matched its scientific arrays and result, with
  cancellation/non-overwrite checks passing. These bounded receipts do not
  qualify fresh project preparation or the current full cohort.
- Open qualification includes source/Qt CI, the exact Windows installer and
  installed-app acceptance, fresh-project/full-cohort checks, and safe
  public-history restoration. GitHub cached/PR data cleanup remains a separate
  requirement from rewriting branch and tag history.
- Follow [verification gates](verification-gates.md) for required checks and
  the [debt tracker](../exec-plans/tech-debt-tracker.md) for bounded maintenance.

No local offscreen Qt run or full native/project acceptance is claimed here.
