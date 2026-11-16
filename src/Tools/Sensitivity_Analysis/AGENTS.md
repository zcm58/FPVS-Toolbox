# Sensitivity Analysis Tool

## Boundary

- `calculator.py` owns widget-free sensitivity calculations and interpretation labels.
- `lmm_simulation.py` owns the input-only Monte Carlo sensitivity calculation for the supported random-intercept FPVS mixed model.
- `worker.py` owns the Qt worker shell that keeps mixed-model simulation off the GUI thread.
- `gui.py` owns the embedded PySide6 presentation and input validation feedback.
- `tool_info.py` owns the editable user-facing explanation of the supported designs and repeated-measure derivation.
- The tool is descriptive and input-only. It must not read project data, inspect participant files, persist settings, write exports, or join the Stats pipeline.
- Keep the Main App GUI as the only user-facing entry point; do not add a subprocess or standalone launcher.
- Keep study assumptions and results side by side in the full-width workspace.
  The calculation-specific controls and mixed-model tabs fit inside the page
  without workspace scrolling.

The [hardware, pipeline, and Studio roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
does not change this input-only boundary. Hardware support or successful Studio
import must not introduce observed-data reads, persistence, fitted residuals,
or claims that this calculator validates a recording or analysis pipeline.

## Verification

Run `python .agents/scripts/verify.py --scope sensitivity-analysis --tier focused`.
Qt interaction and layout smoke tests remain CI-only; manually open the embedded page in a normal visible Main App session when needed.
At 1280 × 900, switch through paired t-test, repeated-measures ANOVA, and both
mixed-model tabs. Check that the calculation and reset actions remain visible
with validation or progress displayed. Calculate a result, then use the
keyboard to select and copy the reporting summary.
