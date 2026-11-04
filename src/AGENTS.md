# Source Instructions

Inherit root [AGENTS.md](../AGENTS.md), including scientific, platform, path,
retirement, and verification rules. Start with the
[agent index](../docs/agent/agent-index.md); read a tool's scoped `AGENTS.md`
before editing it. Do not scan unrelated source to reconfirm a passing audit.

- Use the canonical owners in [ARCHITECTURE.md](../ARCHITECTURE.md).
  `Shared` and `Performance` hold compatibility aliases, not implementations.
- Keep new features modular; prefer files under 500 lines. Do not add functions
  to `Main_App/gui/main_window.py` or refactor its shell without explicit scope.
- Preserve existing GUI workflows unless the task calls for a change. Use
  PySide6 and shared `gui/components`; no Tkinter/CustomTkinter/CTkMessagebox.
- Before hardware, montage, pipeline-composition, or Studio work, read the
  [current-state/future roadmap](../docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
  and matching active plan. Acquisition metadata belongs upstream of numerical
  processing; software support does not establish physical qualification.
