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

The shared Slate & Signal Teal palette lives in `Main_App.gui.style_tokens` and
`theme.py`. The main menu bar and workspace navigation share one slate
background with light text. Signal teal marks the active workspace and keyboard
focus in the navigation row. Light mode pairs paper and white surfaces with
deep teal actions and ochre focus. Dark mode uses slate surfaces, brighter teal
actions, and amber focus. Menus, Settings, dialogs, and embedded tools inherit
the same appearance. Use shared tokens for UI chrome. Scientific canvases and
figure exports keep their scientific palettes.
