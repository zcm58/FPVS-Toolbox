---
name: frontend-design
description: Design or implement distinctive browser interfaces for explicitly web-scoped work, including HTML mockups and web components. Toolbox PySide6 desktop tasks use the desktop design skills.
license: Complete terms in LICENSE.txt
---

# Frontend Design

Adapted for FPVS Toolbox from [Anthropic's Frontend Design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design).

Apply to the browser surface named in the request, including an HTML mockup
when requested. For PySide6, start with the Toolbox
[desktop design guide](../../../docs/agent/design-docs/DESIGN.md) and
`pyside6-gui-cleanup`. Toolbox's `docs/agent/` holds its engineering knowledge
base. Tutorials belong to the OpenFPVS website under the
[product scope](../../../docs/agent/product-specs/fpvs-toolbox.md). Follow the
target website's own repository and publishing workflow for live-site work.

## Establish the direction

- Identify the audience, the job the page serves, and the real content.
  For a new visual direction, use details from the subject to decide the
  layout, typography, imagery, and palette.
- For a new page with room for visual exploration, sketch a short set of
  decisions about color, type roles, layout, and one distinctive visual
  element. An opening section should show the most relevant idea or action.
  Existing pages and small edits should follow their established system.
- Use hierarchy and structure to express real relationships. Dividers,
  numbering, and labels earn their place when they convey grouping, order,
  or navigation. Keep one focal point when competing elements obscure the task.
- Use the established vocabulary and active verbs. Keep the same action name
  across the flow. Add text where it helps someone interpret, choose, act, or
  recover. For empty and error states, explain what the user can do next.
- Add motion where it clarifies a state change, guides attention, or
  demonstrates something the page needs to explain. Use `emil-design-eng` for
  an explicit browser motion or interaction design task.

## Implement and check

Work with the existing framework, layout, and tokens. For a new surface,
choose a small set of reusable decisions. Use real content and meaningful
assets where available. Keep semantic HTML and visible keyboard focus,
honor reduced motion, and check behavior with touch and at narrow widths.
Preview the browser states you changed when a preview is available. Use
`web-design-guidelines` for an explicit web interface audit.
