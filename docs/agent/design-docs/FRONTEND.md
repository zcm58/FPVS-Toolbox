# Frontend

FPVS Toolbox frontend work is PySide6-only.

Primary references:

- `docs/agent/architecture/gui.md`
- `docs/agent/quality/test-selection.md`
- `.agents/skills/pyside6-gui-cleanup/SKILL.md`
- `.agents/skills/pytest-qt-smoke/SKILL.md`

Do not add Tkinter, CustomTkinter, or CTkMessagebox imports.

Use the repo-local PySide6 skill for desktop visual polish and UX work.
`frontend-design`, `emil-design-eng`, and `web-design-guidelines` are web-only
and do not apply unless the task explicitly introduces a browser surface.
Desktop changes follow these contracts:

- Start with `Main_App.gui.components`, `theme.py`, `typography.py`, and the
  existing tool workflow before adding local widgets or style rules.
- Preserve labels, defaults, processing order, file formats, project-root
  behavior, and existing user workflows unless the task explicitly changes
  them.
- Ignore React, Tailwind, browser, mobile, landing-page, and deployment advice
  from those skills unless the repo gains that scoped surface.
- Verify GUI edits with `py_compile`, focused `ruff`, GUI import audits, agent
  audits, and a documented visible/manual smoke path. Do not run offscreen Qt.
- For future hardware/montage controls, show the capabilities of the resolved
  profile and keep unsupported scientific operations unavailable. Follow the
  [shared roadmap](../architecture/hardware-pipeline-studio-roadmap.md); do not
  expose an arbitrary processing-order editor or assume registration enables
  production support.
