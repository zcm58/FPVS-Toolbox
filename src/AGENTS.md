# Source Instructions

Follow [root rules](../AGENTS.md) and the matching tool's scoped `AGENTS.md`.
Use the [architecture map](../ARCHITECTURE.md) for canonical imports.

- Keep new features modular and prefer files under 500 lines. Adding functions
  to `Main_App/gui/main_window.py` or refactoring its shell requires explicit scope.
- For Studio import, follow the [project handoff contract](../docs/agent/architecture/project-io.md#studio-config-handoff).
  For hardware or method extensions, read the [roadmap](../docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
  and [matching plan](../docs/agent/exec-plans/README.md).
