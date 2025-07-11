The Plot_Generator directory contains the standalone PySide6 tool that builds SNR
or BCA line plots from Excel files created by the FPVS Toolbox. GUI adjustments
and minor bug fixes are allowed. Keep processing code modular and under 500 lines
per file. ROI definitions should be loaded from the existing settings using the
utilities in `Tools.Stats`. Plots should be averaged across participants within
each condition and saved to a user selected output folder.

This tool will be use to generate publication quality figures within the FPVS Toolbox. Users should have the ability
to edit the plot title, x and y labels, and the scale of the x and y axes.

The plot generator should read the user-defined ROIs from the settings menu and generate plots for each ROI 
individually. The user must choose an excel file from which to pull data. This will typically be the same as the 
output folder in the main app GUI where the excel data is saved after processing .BDF files. 

Inside this folder, you'll find subfolders of varying names. The names of each of these folders represent the FPVS
conditions that were run. Within each subfolder, there will be excel files named like "P3 Fruit vs Veg_Results". 
You'll have one excel file per participant per condition. 

The app should read all of these excel files for each condition and generate an average ROI plot for each condition 
across all the participants, then plot that data. To further clarify, if you have 30 participants and 5 conditions,
You should generate one plot per condition per ROI. If the user defines 4 ROIS like "frontal, central, parietal, 
occipital", then you have 4 ROIs * 5 conditions = 20 plots. 

