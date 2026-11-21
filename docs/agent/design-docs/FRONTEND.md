# Frontend

Use the [desktop design guide](DESIGN.md) and the existing workflow when
revising a surface. Implement shared widgets, typography and appearance in
`Main_App.gui.components`, `theme.py` and `typography.py`. The [GUI contract](../architecture/gui.md#visual-layout-rules)
owns the PySide6 layout rules. The [agent index](../agent-index.md#skill-map)
routes desktop changes to repo-local skills and [verification gates](../quality/verification-gates.md)
covers CI and visible smoke checks.

For hardware or montage controls, present the capabilities of the resolved
profile. The [pipeline roadmap](../architecture/hardware-pipeline-studio-roadmap.md)
tracks future method choices. Preserve the locked processing order.

The current Toolbox shell uses native menu styling for hover, popups and
keyboard feedback. Settings, dialogs and embedded tools use the shared Slate
& Signal Teal tokens in `Main_App.gui.style_tokens` and `theme.py`. Scientific
canvases and figure exports keep their scientific palettes.
