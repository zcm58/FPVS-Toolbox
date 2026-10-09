# Ratio Calculator Removal

## Status

Future work, requested on 2026-10-09. Ratio Calculator remains available as an
opt-in Beta Tool in the current release. Removal is not part of the active v3
stabilization work and requires a separately scoped implementation.

## Current Decision

- Keep the existing `btn_ratio` entry in
  `src/Main_App/gui/sidebar.py::BETA_TOOL_SPECS`; the sidebar and Tools > Beta
  Tools menu share that registration and the existing beta acknowledgement.
- Defer Ratio Calculator-specific defects and unfinished migrations while
  preparing v3. Do not expand or promote the tool. Shared application defects
  that also affect supported workflows remain in scope for those workflows.
- The current deferred findings are incorrect ratios for conditions with the
  same label and discovery that does not respect the configured data root.
- Preserve the tool's current availability, behavior, settings, and generated
  outputs until removal begins.

## Removal Slice

1. Identify the Ratio Calculator entry points, embedded-page lifecycle,
   tool-local implementation, imports, packaging, tests, verification scope,
   and documentation links.
2. Remove those owned surfaces together without changing shared ROI settings,
   canonical project identities, processing, or other tools. Preserve existing
   project data and generated ratio summaries.
3. Update the tool inventory and navigation documentation. Resolve references
   in other plans so they no longer schedule work on the removed tool.

## Done When

- Ratio Calculator is absent from the sidebar and Tools menu, including when
  Beta Tools is enabled, and no active runtime import or packaging input
  requires its implementation.
- Focused non-Qt checks and the repository precommit gate pass; CI Qt coverage
  and a visible/manual navigation smoke confirm the remaining tools still open.
- Current documentation describes the reduced tool inventory and historical
  ratio outputs remain intact.
