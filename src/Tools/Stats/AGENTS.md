The stats directory contains scripts related to the statistical
analysis of BCA values that are summed up across FFT frequency harmonics
in EEG FPVS data. The Statistical tests that will be run will always
be paired, because all of the participants in FPVS experiments will 
complete multiple conditions. 

Ideally, the app needs to be able to compare conditions, run repeated 
measures anova, and alo impelement a linear mixed effects model. 

The stats tool should be able to calculate and output everything 
that might be needed for a publication quality manuscript. 

The Base Frequency user input should remain at a default of 6.0Hz. This allows 
the user to tell the Stats tool what frequency they ran their FPVS experiment at. 
This information is important because BCA values at the target frequency and its 
harmonics introduce falsely high visual responses that we don't need to include 
in the statistical analysis. 