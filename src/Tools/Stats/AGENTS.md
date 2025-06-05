The stats directory contains scripts related to the statistical
analysis of BCA values that are summed up across FFT frequency harmonics
in EEG FPVS data. The Statistical tests that will be run will always
be paired, because all of the participants in FPVS experiments will 
complete multiple conditions. 

The stats tool should be able to calculate and output everything 
that might be needed for a publication quality manuscript. 

The Base Frequency user input should remain at a default of 6.0Hz. This allows 
the user to tell the Stats tool what frequency they ran their FPVS experiment at. 
This information is important because BCA values at the target frequency and its 
harmonics introduce falsely high visual responses that we don't need to include 
in the statistical analysis. 

IMPORTANT RULES for Codex:

The explanatory log output text should not be removed these files. 
It is important that an explanation of the results is provided in the output text
log so that the user can understand the results more easily. 

None of the statistical analysis should be altered in any way. The only exception is
if you are trying to reduce module size; in that case, you can move sections of code 
into new files, but do not change the content of the code or the functionality. 

If you're adding a new statistical analysis method, we should always include a new
button so that the user can access the new method. 