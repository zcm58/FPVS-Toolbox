The Sequence_Figure directory owns the embedded FPVS Sequence Figure tool. It
builds publication-oriented illustrations of the stimulus sequence from
manually selected stimulus images.

Current ownership map:

- `renderer.py`: widget-free validation, image normalization, timing scaffold
  drawing, and PNG/PDF/SVG export.
- `worker.py`: QThread-compatible QObject shell that runs renderer work and
  emits progress, errors, and completion without touching widgets.
- `gui.py`: embedded PySide6 page for manual base/oddball image slots,
  frequency labels, output folder selection, and dialog-based export feedback.

Keep this tool separate from `Tools.Plot_Generator`, which remains SNR-line-plot
only. Do not add EEG processing, SNR plotting, condition-folder sampling, or
project manifest writes here unless explicitly scoped.

Before broad manual inspection, run:

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

For renderer changes, start with:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Sequence_Figure\renderer.py src\Tools\Sequence_Figure\worker.py src\Tools\Sequence_Figure\gui.py
.\.venv1\Scripts\python.exe -m pytest tests\sequence_figure -q
```
