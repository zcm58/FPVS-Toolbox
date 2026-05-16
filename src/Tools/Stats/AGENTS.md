The stats directory contains scripts related to the statistical
analysis of BCA values that are summed up across significant (z > 1.64) FFT frequency harmonics
in EEG FPVS data. 

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

The stats tool should support statistical analysis of one group or multiple groups. There may be two groups in which
we need to compare the FPVS responses between Group A and Group B using ANOVA, Linear Mixed Models, followed 
with post-hoc t-tests. 


IMPORTANT RULES for Codex:

The idea of the stats tool is to provide a quick look and understanding of the significant effects of the dataset  
to a non-expert user. As such, the log outputs should summarize the significant effects only, and provide a plain  
english explanation of the results. Somewhere in the log, we can write that the detailed results have been saved to 
excel files. 

