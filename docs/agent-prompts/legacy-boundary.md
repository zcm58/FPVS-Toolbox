# Legacy Boundary Prompt Template

Use `$legacy-boundary-review`.

Goal: keep retired or historical legacy behavior from re-entering active runtime while preserving the processing pipeline during any boundary cleanup.

Checks:

```powershell
python scripts/agent_audit.py --check protected
python scripts/agent_audit.py --check source-localization
git diff --name-only
```

Requirements:

- Do not recreate `src/Main_App/Legacy_App/**`; active behavior belongs in purpose-based `Main_App` packages.
- If historical legacy behavior must be referenced, use existing current-app APIs or a focused adapter outside the retired path.
- Do not revive Source Localization/eLORETA unless explicitly requested as a new restoration feature.
