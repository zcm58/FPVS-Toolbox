# Legacy Boundary Prompt Template

Use `$legacy-boundary-review`.

Goal: keep retired or historical legacy behavior from re-entering active runtime while preserving the processing pipeline during any boundary cleanup.

Checks:

```powershell
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python scripts/agent_audit.py --check protected
python scripts/agent_audit.py --check source-localization
python scripts/agent_audit.py --check source-localization-refs
git diff --name-only
```

Requirements:

- Do not recreate `src/Main_App/Legacy_App/**` or `src/Main_App/PySide6_App/**`; active behavior belongs in purpose-based `Main_App` packages.
- Use active Main App import surfaces: `Main_App.gui`, `Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.workers`, `Main_App.diagnostics`, and `Main_App.exports`.
- If historical behavior must be referenced, use existing current-app APIs or a focused adapter outside retired paths.
- Do not revive Source Localization/eLORETA imports, tests, settings, quarantine dependencies, or UI behavior unless explicitly requested as a restoration feature.
- Preserve existing processing order, data formats, project paths, and exports.
