# FPVS Toolbox Documentation

The Fast Periodic Visual Stimulation (FPVS) Toolbox allows you to easily process
EEG data from FPVS experiments and run statistical analyses on the resulting
metrics. As of now, FPVS Toolbox only supports the BioSemi data format (.BDF) and FPVS experiments ran with PsychoPy. 

**This documentation page is a work in progress and is not yet complete.**

> Current app version: **v1.6.0**

---

## Quick start

**Install FPVS Toolbox**  
   Download the latest installer from the GitHub Releases page and run it
   on Windows. You may have to bypass Windows Defender if prompted. When you run FPVS Toolbox for the first time, you
   will be asked to select a "Project Root". This is where all the different results from various projects you create
   within FPVS Toolbox will live. I recommend that you avoid using cloud based folders like OneDrive - it sometimes
   causes issues with Statistical Analysis. 

--- 

**Create or open a project**  

From the main window, choose "Create New Project". You will be prompted to title your project, select the number
of experimental groups, and to name each group. Next, you will select the input folder for each group (wherever you
have stored your .BDF files).


   You will need to input titles for each FPVS Condition in your experiment in the Main App GUI, as well as the 
   PsychoPy trigger code associated with that condition. 

--- 


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

- [Relevant Publications](relevant-publications.md)  
  A brief overview of relevant publications on FPVS and the preprocessing pipeline used
inside the FPVS Toolbox. 

- [Tutorials & Walkthroughs](tutorial.md)  
  Step-by-step examples on how to use the FPVS Toolbox.

---

## Project links

- GitHub repository: `https://github.com/zcm58/FPVS-Toolbox-Repo>`
