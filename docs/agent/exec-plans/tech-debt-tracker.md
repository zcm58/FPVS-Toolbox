# Technical Debt Tracker

This page tracks unresolved, implementation-ready debt. Keep permanent rules
in `AGENTS.md` and architecture contracts; keep implementation evidence in the
active plan while work is underway. Counts are review signals, not deletion or
refactoring thresholds.

## Open Debt

No open implementation-ready items remain from the bounded 2026-10-18 cleanup
scope. Future findings need a named responsibility, evidence and an observable
completion condition before becoming another cleanup item. The review census
below remains relevant; it is not a claim that the whole application has no
architectural debt.

## Remaining Review Context

The 2026-10-18 implementation census contains 519 production Python modules,
107 above 600 physical lines, and 428 exact `except Exception` handlers across
116 modules. The original snapshot contained 504 modules and 435 handlers
across 118 modules. This census uses tracked/new source Python files, excludes
`src/Standalone_Scripts/**` and quarantine before reading, decodes UTF-8-SIG,
and counts handlers with the Python AST.

Large QC, Stats, source-visualization and worker orchestration modules remain.
Their size alone does not identify unused code or justify changing scientific
kernels. Further extraction should choose a coherent, behavior-covered owner.
Likewise, remaining broad catches need workflow-specific review: terminal
worker failures, best-effort previews, logging and transactional cleanup can
require broad boundaries. A handler count is not a list of confirmed bugs.

Canonical ownership and retained compatibility are documented in
[Main App target layout](../architecture/main-app-target-layout.md),
[GUI architecture](../architecture/gui.md), and
[the module map](../architecture/module-map.md). `Shared` and `Performance`
contain compatibility aliases, with zero active implementation owners or
active runtime imports relying on those transitional paths. Neutral ROI,
harmonic and workbook readers own their shared implementations.

## Tracking Rules

- Give new items stable `TD-###` identifiers, evidence, a bounded next slice,
  and an observable completion condition.
- Promote an item to `exec-plans/active/` when implementation starts.
- Reverify evidence before planning; snapshots describe scale, not acceptance
  thresholds.
- Remove fixed or explicitly accepted items; do not retain completed migration
  logs as open debt.
