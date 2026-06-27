The stats directory contains scripts related to statistical analysis of FPVS
EEG BCA values. The active Summed BCA DV defaults to the group-level
significant-harmonics policy using the predefined-ROI electrode union for
significance detection and all non-base oddball harmonics through the highest
significant harmonic for summation. Fixed/predefined harmonic summation remains
available as an alternate policy. Preserve the locked exact-column,
common-harmonic-list, z > 1.64, and neighboring-noise rules documented in
`docs/agent/architecture/statistics-tools.md`.

Before broad manual inspection, run:

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
- Excel scanning should treat top-level folders under `1 - Excel Data Files/`
  as conditions. Multi-group output may add a group folder inside each
  condition; scan those files recursively while keeping the condition name from
  the top-level folder.
- Do not infer a participant's group assignment from the Excel folder name when
  a manifest is available.


IMPORTANT RULES for Codex:

The idea of the stats tool is to provide a quick look and understanding of the significant effects of the dataset  
to a non-expert user. As such, the log outputs should summarize the significant effects only, and provide a plain  
english explanation of the results. Somewhere in the log, we can write that the detailed results have been saved to 
excel files. 

