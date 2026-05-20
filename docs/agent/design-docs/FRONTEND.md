# Frontend

FPVS Toolbox frontend work is PySide6-only.

Primary references:

- `docs/agent/architecture/gui.md`
- `docs/agent/quality/test-selection.md`
- `.agents/skills/pyside6-gui-cleanup/SKILL.md`
- `.agents/skills/pytest-qt-smoke/SKILL.md`

Do not add Tkinter, CustomTkinter, or CTkMessagebox imports.

For explicit visual polish or UX critique requests, global design skills such
as `impeccable`/`delight`, `ui-ux-pro-max`, or `frontend-design` may be used as
input, but their output must be translated into this desktop app's PySide6
contracts:

- Start with `Main_App.gui.components`, `theme.py`, `typography.py`, and the
  existing tool workflow before adding local widgets or style rules.
- Preserve labels, defaults, processing order, file formats, project-root
  behavior, and existing user workflows unless the task explicitly changes
  them.
- Ignore React, Tailwind, browser, mobile, landing-page, and deployment advice
  from those skills unless the repo gains that scoped surface.
- Verify GUI edits with `py_compile`, focused `ruff`, GUI import audits, agent
  audits, and a documented visible/manual smoke path. Do not run offscreen Qt.
