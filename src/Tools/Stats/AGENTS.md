The stats directory contains scripts related to statistical analysis of FPVS
EEG BCA values. The active Summed BCA DV defaults to the group-level
significant-harmonics policy using the predefined-ROI electrode union for
significance detection and all non-base oddball harmonics through the highest
significant harmonic for summation. If more than 10 eligible non-base harmonics
lie strictly between the two highest significant peaks, the one-pass gap guard
omits the isolated highest peak and stops summation at the next-highest peak;
base-rate overlaps do not count and exactly 10 remains allowed. Fixed/predefined
harmonic summation remains available as an alternate policy. Preserve the
locked exact-column, common-harmonic-list, z > 1.64, gap-guard, and
neighboring-noise rules documented in `docs/agent/architecture/statistics-tools.md`.

Before broad manual inspection, run:

Prefer `.venv1` when present; if it is absent, substitute `.venv` in the
activation path below.

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use script output to decide what to read next.

The stats tool should be able to calculate and output everything 
that might be needed for a publication quality manuscript. 

The stats tool currently supports single-group statistical analysis only.

v2.1 project contract:

- `project.json` is canonical for group assignments. Prefer participant
  `group_id` and resolve labels/folder names through `project.groups`; legacy
  participant `group` values are compatibility input only.
- Stats workbook discovery must consume
  `Main_App.projects.load_project_dataset_index`. Keep
  `stats_data_loader` functions only as thin compatibility adapters for
  established Stats return shapes; do not add a second scanner, participant-ID
  parser, or group normalizer in this package.
- Do not infer a participant's group assignment from an Excel folder name.
  The shared index supplies the canonical manifest-owned group ID and retains
  the observed folder only for routing diagnostics.


IMPORTANT RULES for Codex:

The idea of the stats tool is to provide a quick look and understanding of the significant effects of the dataset  
to a non-expert user. As such, the log outputs should summarize the significant effects only, and provide a plain  
english explanation of the results. Somewhere in the log, we can write that the detailed results have been saved to 
excel files. 

