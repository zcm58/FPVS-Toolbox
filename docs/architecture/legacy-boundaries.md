# Legacy Boundaries

Retired Main App legacy path:

- `src/Main_App/Legacy_App/**`

The historical `Legacy_App` package has been retired. Do not recreate this
directory; active Main App behavior belongs in purpose-based packages such as
`Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.exports`,
`Main_App.workers`, `Main_App.diagnostics`, and `Main_App.gui`.

Source Localization/eLORETA is removed from active runtime, not a protected black box:

- `src/Tools/SourceLocalization/**` must stay empty of source files.
- The app must not add GUI actions, settings, tests, imports, or quarantine-tree dependencies for this removed feature.

Rules:

- Do not add files under `src/Main_App/Legacy_App/**`.
- Prefer thin adapters or caller-side normalization in purpose-based Main App packages.
- When old behavior already has a current-app replacement, use that replacement rather than adding compatibility paths.
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
