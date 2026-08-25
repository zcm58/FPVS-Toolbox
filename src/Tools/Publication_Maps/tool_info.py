"""Editable user-facing information for the Scalp Maps tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SCALP_MAPS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Scalp Maps tool exports publication-ready topographic figures from
processed FPVS workbooks. It can render BCA, SNR, and Z-score maps for selected
conditions using the significant-harmonic list saved when processing completed.
</p>

<h3>Typical Workflow</h3>
<p>
Open a managed project, choose one canonical group (or All groups for separate
group outputs), then select conditions and map types on the Generate Maps tab.
That tab keeps generation status, progress, and the
<strong>Generate Scalp Maps</strong> action together. Advanced Settings owns
the full-width output-folder controls, color scales, and optional
paired-condition or two-group figure layouts. <strong>View Generation
Log</strong> opens the live history in a focused dialog; closing and reopening
it does not discard messages. The project&apos;s canonical processed-Excel root is
selected automatically and cannot be narrowed to a subgroup folder. When two
conditions are selected, the paired condition figure option creates
side-by-side maps. In an exactly-two-group project, choose All groups and one
condition to export a descriptive side-by-side group comparison. Each group is
aggregated independently; the figure is not a between-group statistical test.
If processing-time harmonic
selection is missing or stale, the Post-processing Required dialog can launch
the shared rebuild workflow; EEG preprocessing is not repeated.
</p>
<p>
Repeated-session projects explicitly choose one session for the ordinary
condition workflow or two sessions for a group-column by session-row grid.
During Session comparison, Advanced Settings hides the inapplicable Figure
layout section and expands Map appearance; switching to Condition restores the
applicable ordinary layout options.
The grid shares color limits and can add a paired comparison-minus-reference
row. It omits the internal figure title, shows `(A)` and `(B)` canonical group
headers once above the map columns, places canonical session labels vertically
to the left, and keeps color scales outside the maps on the right. Visit numbers
and sample sizes are omitted. Canonical recording/session identity is required.
</p>

<h3>Output Notes</h3>
<p>
The tool writes matching high-resolution PNG and PDF figure assets only.
Ordinary multi-group runs write each group into its own named output folder.
Two-group comparison mode writes one combined figure at the selected base
output. Repeated-session grids use the full 6.5-inch text width of a US Letter
page with 1-inch horizontal margins, omit explanatory footers, and separate
the canonical group columns with a neutral divider. Groups are never pooled
implicitly. Fixed color ranges are useful when comparing conditions or groups.
</p>
"""

SCALP_MAPS_TOOL_INFO = ToolInfoContent(
    key="scalp_maps",
    title="About Scalp Maps",
    html=SCALP_MAPS_TOOL_INFO_HTML,
)

__all__ = ["SCALP_MAPS_TOOL_INFO", "SCALP_MAPS_TOOL_INFO_HTML"]
