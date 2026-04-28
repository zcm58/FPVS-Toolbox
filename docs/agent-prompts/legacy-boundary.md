# Legacy Boundary Prompt Template

Use `$legacy-boundary-review`.

Goal: keep protected legacy behavior stable while changing caller-side code.

Checks:

```powershell
python scripts/agent_audit.py --check protected
python scripts/agent_audit.py --check source-localization
git diff --name-only
```

Requirements:

- Do not edit `src/Main_App/Legacy_App/**` unless explicitly approved.
- Do not revive Source Localization dead code unless explicitly requested.
- Prefer adapters outside protected folders.
