Instructions for Codex: 

If you are instructed to make edits in a specific directory that will not affect other directories, please review 
the AGENTS.md file in that directory for specific instructions. To save time, you do not have to review the AGENTS.md
file of other directories if your edits will not affect them. If your edits will affect other directories, please review 
the AGENTS.md file in each directory for specific instructions before making major edits. 

In general, the app GUI should not be altered significantly unless a new button or
toolbar option is needed when adding new features.

main_app.py is the main file for the application based in PySide6 that has replaced fpvs_app.py's customtkinter GUI. 
When suggesting changes or refactor options to this file, please do not change or edit code, just suggest ways to copy
and paste code from main_window.py into new standalone .py files that you place in 
the Main_App\PySide6_App directory. You can add imports into the main_window.py file where needed.


When adding new features, please try to keep the code modular and under 500 lines per file. You are allowed to import
functions from other files into the main_window.py file, but please do not add new functions to the main_window.py file. 