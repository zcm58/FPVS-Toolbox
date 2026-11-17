# Design

The canonical OpenFPVS desktop experience spec is maintained in the private
OpenFPVS repository. From the Toolbox repository root, maintainers can find it
at `../OpenFPVS/DESKTOP_EXPERIENCE.md` in a sibling checkout.

Design for lab members doing routine work. Give new members guidance at the
point of need and keep detailed controls and evidence available to experts.
FPVS Studio is the visual and interaction reference. When a Toolbox surface
changes, use the corresponding Studio pattern where it fits the processing
task. Preserve current workflows and behavior unless the task explicitly
changes them. The [product scope](../product-specs/fpvs-toolbox.md) and
[GUI architecture](../architecture/gui.md) document the local contracts.

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
