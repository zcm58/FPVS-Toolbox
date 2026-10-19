# Legacy Boundary Prompt Template

Use `$legacy-boundary-review`.

Goal: keep retired or historical legacy behavior from re-entering active runtime while preserving the processing pipeline during any boundary cleanup.

Checks:

```console
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/scripts/audit/agent_audit.py --check protected
python .agents/scripts/audit/agent_audit.py --check source-localization
python .agents/scripts/audit/agent_audit.py --check source-localization-refs
git diff --name-only
```

Requirements:

- Do not recreate `src/Main_App/Legacy_App/**` or `src/Main_App/PySide6_App/**`; active behavior belongs in purpose-based `Main_App` packages.
- Use active Main App import surfaces: `Main_App.gui`, `Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.workers`, `Main_App.diagnostics`, `Main_App.settings`, and `Main_App.exports`.
- `Main_App.Shared` and `Main_App.Performance` preserve compatibility aliases;
  do not add implementations or new runtime imports there.
- If historical behavior must be referenced, use existing current-app APIs or a focused adapter outside retired paths.
- Do not revive the retired `Tools.SourceLocalization` package or quarantine
  dependencies. The separate current `Tools.LORETA_Visualizer` and its isolated
  source producers follow their scoped agent/architecture contracts.
- Preserve existing processing order, data formats, project paths, and exports.
- For modular hardware/pipeline or Studio work, read the
  [shared roadmap](../architecture/hardware-pipeline-studio-roadmap.md); new
  capabilities must retain historical project behavior and locked science.
