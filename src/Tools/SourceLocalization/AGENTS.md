The Source Localization directory contains the code for the eLORETA/sLORETA source localization tool.
The GUI code should be kept separate from the functionality of the app.
Instructions for Codex:

The ultimate goal of the source localization tool is to provide a user-friendly way to find the source of the oddball
response to different FPVS conditions. Ideally we would want to be able to average out the source localization results
across all participants and conditions, but this is not currently implemented. 

For example, if we have 30 participants and 5 conditions in this format: 
- Condition 1: Fruit vs Veg
- Condition 2: Veg vs Fruit
- Condition 3: Green Fruit vs Green Veg
- Condition 4: Green Veg vs Red Veg
- Condition 5: Red Fruit vs Green Fruit
 

We also want to be able to view this average source localization in a 3D glass brain viewer so we can visually compare
the responses across conditions. This functionality is not currently implemented, but the 3D glass brain viewer is 
partially working. 


Additions or edits within this directory should be made with these goals in mind. Try to keep the code modular and 
if possible, 500 lines or less per file. We should design this module with future updates in mind. 

As of right now, the transparency functionality is not working, so we will need to 
think of multiple ways to fix this. 

When editing or adding features, please ensure that no screenshots are to be saved of the 3-D glass brain viewer. 
This is not necessary. 

Additionally, do not change the way the fsaverage directory is saved. 