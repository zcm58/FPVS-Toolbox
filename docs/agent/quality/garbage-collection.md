# Garbage Collection

Garbage collection is the repo's recurring cleanup discipline for keeping agent
work from compounding into technical debt.

## Golden Principles

- Prefer existing shared owners and canonical import surfaces over new
  hand-rolled helpers.
- Keep generated caches, temporary output, and local probe artifacts out of git.
- Preserve repository-root `.fpvs_cache/` during routine cleanup. It can hold
  the ignored MNE/fsaverage dependency used by LORETA Visualizer.
- Do not leave unresolved inline debt markers in changed files. Record real debt
  in `docs/agent/exec-plans/tech-debt-tracker.md` or an active execution plan.
- Avoid broad exception handlers in production additions unless the boundary is
  explicit and logged.
- Do not probe data shapes casually. Validate boundaries with existing project,
  loader, Stats, or export contracts.

## Mechanical Gate

Run:

```console
python .agents/scripts/audit/agent_audit.py --check garbage-collection
```

The check looks for a small set of patterns.

- Git-visible paths that match generated cache and temporary artifact patterns.
- New unresolved inline debt markers in changed Python or Markdown files.
- New broad `except Exception:` handlers in production code additions.

For user-requested deletion, use the
[cleanup skill](../../../.agents/skills/cleanup-generated-files/SKILL.md) to
preview its named generated targets, including retired bundled template caches.
Keep fsaverage template data outside tracked source and distribution contents.

When a recurring cleanup rule becomes stable and low-noise, add it to
`.agents/scripts/audit/agent_audit.py` instead of relying on manual review.
