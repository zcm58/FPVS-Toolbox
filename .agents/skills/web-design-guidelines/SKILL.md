---
name: web-design-guidelines
description: Review an explicitly scoped website or browser interface against Vercel Web Interface Guidelines. Toolbox PySide6 desktop reviews use the desktop design skills.
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

# Web Interface Guidelines

Review the requested website, browser component, or HTML mockup. For Toolbox
desktop work, use `pyside6-gui-cleanup` and the
[desktop design guide](../../../docs/agent/design-docs/DESIGN.md).

1. Use the available web retrieval tool to read the current
   [Vercel Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md).
   If the source is unavailable, say so when reporting any review completed
   from the supplied materials.
2. Use the requested files or URL. If the request describes an identifiable
   change or component, find its files from that context. Ask for the target
   only when the review surface remains ambiguous.
3. Apply relevant upstream rules to the actual browser surface. Follow the
   project's requirements for terminology and interaction. Use browser
   verification where a finding depends on rendered behavior, such as focus
   visibility or overflow. Identify behaviors you could only inspect in source.
4. Report concrete findings with `file:line` locations when source is
   available. For browser-only observations, name the page and control.
   State the impact and fix when useful. Edit the reviewed surface when
   requested.
