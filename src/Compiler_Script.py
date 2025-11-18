# I use this script to compile the entire repo into a standalone .exe. I copy and paste the text below to the terminal
# and run it from there. It will create a standalone .exe inside your repo in a 'dist' folder

# After that, I package the .exe and other dependencies into an installer using Inno Setup.

pyinstaller `
  --clean `
  --noconfirm `
  --windowed `
  -n FPVS_Toolbox `
  --paths=src `
  -i "assets/ToolBox_Icon.ico" `
  --collect-all mne `
  --collect-data mne `
  --hidden-import=mne.io.bdf `
  --hidden-import=scipy `
  --hidden-import=scipy._cyutility `
  --hidden-import=pandas `
  --hidden-import=numpy `
  --hidden-import=statsmodels `
  --hidden-import=pyvista `
  --hidden-import=statsmodels `
    --hidden-import=patsy `
  -D src/main.py