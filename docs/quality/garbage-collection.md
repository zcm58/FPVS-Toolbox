# Garbage Collection

Garbage collection is the repo's recurring cleanup discipline for keeping agent
work from compounding into technical debt.

## Golden Principles

- Prefer existing shared owners and canonical import surfaces over new
  hand-rolled helpers.
- Keep generated caches, temporary output, and local probe artifacts out of git.
- Do not leave unresolved inline debt markers in changed files. Record real debt
  in `docs/exec-plans/tech-debt-tracker.md` or an active execution plan.
- Avoid broad exception handlers in production additions unless the boundary is
  explicit and logged.
- Do not probe data shapes casually. Validate boundaries with existing project,
  loader, Stats, or export contracts.

## Mechanical Gate

Run:

```powershell
python scripts/agent_audit.py --check garbage-collection
```

The check is intentionally low-noise. It currently catches:

- visible cache/build/temp artifacts;
- new unresolved inline debt markers in changed Python or Markdown files;
- new broad `except Exception:` handlers in production code additions.

When a recurring cleanup rule becomes stable and low-noise, add it to
`scripts/agent_audit.py` instead of relying on manual review.
