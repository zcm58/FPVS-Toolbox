# Legacy Boundaries

Protected active legacy path:

- `src/Main_App/Legacy_App/**`

Source Localization is no longer a protected black box. It is quarantined dead code:

- active path that must stay empty of source files: `src/Tools/SourceLocalization/**`
- ignored quarantine reference path: `src/quarantine/Tools/LORETA/SourceLocalization/**`

Rules:

- Do not edit `src/Main_App/Legacy_App/**` unless the user explicitly approves it.
- Prefer thin adapters or caller-side normalization outside protected legacy folders.
- Do not revive Source Localization imports, tests, or UI behavior unless the user explicitly asks to restore that feature.
- Keep compatibility exports in `src/Main_App/__init__.py` stable unless the task is specifically about imports.

Useful checks:

```powershell
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python scripts/agent_audit.py --check protected
python scripts/agent_audit.py --check source-localization
git diff --name-only
```

Run the skill-local script before manually scanning protected or quarantined paths.
