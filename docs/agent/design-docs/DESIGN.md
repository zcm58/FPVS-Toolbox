# Design

Design guidance lives in:

- `docs/agent/design-docs/`
- `docs/agent/architecture/gui.md`
- `docs/agent/product-specs/`

For GUI work, preserve existing workflows unless the task explicitly changes
behavior. Prefer quiet, task-focused PySide6 interfaces over decorative layouts.

Installed design skills can help critique hierarchy, spacing, labels, and
interaction clarity, but they do not set this repo's design system. Repo rules
override them:

- PySide6 is the only active UI toolkit.
- `SectionCard` frames top-level subsections; do not add nested card layouts.
- Subsection headings use `Main_App.gui.components.SubsectionHeaderLabel`.
- Shared font, color, spacing, and component changes belong in
  `Main_App.gui.components`, `theme.py`, `typography.py`, or existing widget
  owners, not per-surface ad hoc QSS.
- Desktop FPVS workflows are utilitarian and data-focused; do not introduce
  landing-page, mobile-app, or web-dashboard patterns into the app shell.
