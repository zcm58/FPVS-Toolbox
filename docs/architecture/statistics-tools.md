# Statistics And Tool Modules

Statistics and tool code is split between active PySide6 surfaces, shared logic, and legacy compatibility modules.

Primary paths:

- `src/Tools/Stats/PySide6/`: active statistics GUI.
- `src/Tools/Stats/Legacy/`: legacy statistical routines and compatibility modules.
- `src/Tools/Stats/shared_rois.py` and `src/Tools/Stats/roi_resolver.py`: shared ROI helpers.
- `src/Tools/Plot_Generator/`: plot generation GUI, workers, and manifest helpers.
- `src/Tools/Ratio_Calculator/`: ratio calculator GUI, pipeline, exports, and plots.
- `src/Tools/Individual_Detectability/`: detectability tool core, GUI, and worker.

Rules:

- Preserve statistical output schemas and plain-language reporting unless explicitly changing them.
- Keep GUI imports PySide6-only.
- Use focused tests around changed data transformations and exports.

Useful tests:

```powershell
python -m pytest tests/test_stats_pipeline_smoke.py tests/test_stats_layout_smoke.py -q
python -m pytest tests/test_ratio_calculator_plots.py tests/test_plot_generator_gui.py -q
```
