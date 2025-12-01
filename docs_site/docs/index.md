# FPVS Toolbox Documentation

The Fast Periodic Visual Stimulation (FPVS) Toolbox allows you to easily process
EEG data from FPVS experiments and run statistical analyses on the resulting
metrics. 

> Current app version: **v1.5.0**

---

## Quick start

1. **Install FPVS Toolbox**  
   Download the latest installer from the GitHub Releases page and run it
   on Windows. You may have to bypass Windows Defender if prompted. 


2. **Create or open a project**  
   From the main window, choose a project root folder and set basic metadata
   (project name, groups, subject list, trigger IDs).


3. **Process EEG data**  
   - Select an EEG file or batch folder.  
   - Configure preprocessing (reference, downsampling, filters, artifact
     handling) in the Settings panel.  
   - Click **Start Processing** to run the pipeline and generate metrics
     and Excel outputs.
   

4. **Run statistical analysis**

   - Open **Statistical Analysis** in the sidebar to run single-group or
   between-group analyses on the processed data.

---

## Core documentation

- [Processing Pipeline](processing-pipeline.md)  
  Detailed description of how recordings are loaded, preprocessed, epoched,
  and converted to frequency-domain metrics.

- [Statistical Analysis](statistical-analysis.md)  
  Overview of single-group and between-group analyses, models used, and
  how to interpret the outputs.

- [Relevant Publications](publications.md)  
  Papers describing FPVS, SSVEP/frequency-tagging methods, preprocessing
  choices, and statistical approaches used in this toolbox.

- [Tutorials & Walkthroughs](tutorials/quickstart.md)  
  Step-by-step examples on how to use the FPVS Toolbox.

---

## Project links

- GitHub repository: `https://github.com/zcm58/FPVS-Toolbox-Repo>`