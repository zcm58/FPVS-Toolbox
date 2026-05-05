# Legacy Boundary Prompt Template

Use `$legacy-boundary-review`.

Goal: keep runtime-used legacy behavior stable while migrating callers and small responsibilities toward clearer current-app modules.

Checks:

```powershell
python scripts/agent_audit.py --check protected
python scripts/agent_audit.py --check source-localization
git diff --name-only
```

Requirements:

- Targeted edits to `src/Main_App/Legacy_App/**` are allowed for active refactors, but they must preserve the processing pipeline, processing order, data formats, and exports.
- Do not revive Source Localization/eLORETA unless explicitly requested as a new restoration feature.
- Prefer adapters or current-app modules when they avoid unnecessary edits to migration-boundary code.
