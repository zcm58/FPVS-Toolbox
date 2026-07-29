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

The Stats tool supports native single- and multi-group inference. Project mode
is manifest-owned: a true multi-group project must use canonical `group_id`
values and must not be silently pooled into the single-group pipeline. Both
modes freeze the QC/manual-eligible participant cohort before finding the
complete shared Condition x ROI core. Conditions may be excluded for
incomplete coverage; participants must not be dropped inside a model to rescue
a condition. The default strict `omnibus_effects_strict` family applies the
selected correction (Holm by default) to canonical single-group RM-ANOVA
effects or the four multi-group ML-LRT rows. If strict control is disabled,
the joint "Any group-related effect" test is the sole primary multi-group
omnibus question and the decomposition rows remain exploratory.

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

The Stats tool should give a non-expert a quick, accurate understanding of
three separate questions: response detection, within-subject Condition/ROI
effects, and between-group effects. At a Glance should use plain English and
only canonical reportable p-values, while Methods & Checks and the workbook
retain the complete audit trail. Do not hide a nonsignificant primary test:
describe it as "did not provide evidence" and never as proof of equivalence or
absence. Keep exploratory post-selection response tests and all robust,
resampling, or leave-one-out findings visibly labelled. Always identify the
detailed results workbook.

