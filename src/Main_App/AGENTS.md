This directory contains the core functionality of the FPVS Toolbox. 
The GUI code should be kept separate from the functionality of the app.

Processing should always occur on a separate thread from the GUI
so that it does not become unresponsive. 

The eeg_preprocessing.py file should not be edited for any reason. 

The goal of this directory is to decrease the size of the core fpvs_app.py file
while ensuring that future updates are easier by modularizing the code.