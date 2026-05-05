# Legacy Boundaries

Protected active legacy path:

- `src/Main_App/Legacy_App/**`

This designation is temporary. The long-term simplification goal is to remove or rename the confusing `Legacy_App` boundary after runtime-used behavior has been migrated to clearer current-app modules, thin adapters, or shared services with equivalent coverage.

Source Localization/eLORETA is removed from active runtime, not a protected black box:

- `src/Tools/SourceLocalization/**` must stay empty of source files.
- The app must not add GUI actions, settings, tests, imports, or quarantine-tree dependencies for this removed feature.

Rules:

- Targeted edits to `src/Main_App/Legacy_App/**` are allowed for active refactors, but they must preserve the processing pipeline, processing order, data formats, and exports.
- Prefer thin adapters or caller-side normalization outside protected legacy folders.
- When a feature already has a current-app replacement, prefer migrating callers away from `Legacy_App` over adding new compatibility paths.
- Do not revive Source Localization/eLORETA imports, tests, settings, or UI behavior unless the user explicitly asks to restore that feature.
- Keep compatibility exports in `src/Main_App/__init__.py` stable unless the task is specifically about imports.

Useful checks:

```powershell
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python scripts/agent_audit.py --check protected
python scripts/agent_audit.py --check source-localization
git diff --name-only
```

Run the skill-local script before manually scanning protected or quarantined paths.
