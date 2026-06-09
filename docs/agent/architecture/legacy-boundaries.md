# Legacy Boundaries

Retired Main App legacy paths:

- `src/Main_App/Legacy_App/**`
- `src/Main_App/PySide6_App/**`

The historical `Legacy_App` and `PySide6_App` packages have been retired. Do not recreate these
directories; active Main App behavior belongs in purpose-based packages such as
`Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.exports`,
`Main_App.workers`, `Main_App.diagnostics`, and `Main_App.gui`.

Source Localization/eLORETA is removed from active runtime, not a protected black box:

- `src/Tools/SourceLocalization/**` must stay empty of source files.
- The app must not add GUI actions, settings, tests, imports, or quarantine-tree dependencies for this removed feature.
- The new `src/Tools/LORETA_Visualizer/**` tool is a separately scoped
  source-visualization branch. It must not consult, copy, import, or inherit
  design decisions from the removed Source Localization/eLORETA code.
- In that new tool, renderer code displays prepared payloads only. Tool-local
  helpers may validate, transform, normalize, and adapt future calculation
  outputs into renderer payloads, but they must not compute inverse solutions,
  source statistics, or LORETA values.
- The new visualizer may fetch external fsaverage data through MNE, but durable
  automatic installs belong in the ignored repository-root `.fpvs_cache`
  directory, never in active source, docs, package data, or quarantine paths.

Rules:

- Do not add files under `src/Main_App/Legacy_App/**` or `src/Main_App/PySide6_App/**`.
- Prefer thin adapters or caller-side normalization in purpose-based Main App packages.
- When old behavior already has a current-app replacement, use that replacement rather than adding compatibility paths.
- Do not revive Source Localization/eLORETA imports, tests, settings, or UI behavior unless the user explicitly asks to restore that feature.
- Do not treat the new LORETA Visualizer as permission to change preprocessing,
  Stats methods, project manifests, BDF loading, diagnostics, or active
  project I/O.
- Keep compatibility exports in `src/Main_App/__init__.py` stable unless the task is specifically about imports.

Useful checks:

```powershell
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/scripts/audit/agent_audit.py --check protected
python .agents/scripts/audit/agent_audit.py --check source-localization
python .agents/scripts/audit/agent_audit.py --check source-localization-refs
git diff --name-only
```

Run the skill-local script before manually scanning protected or quarantined paths.
