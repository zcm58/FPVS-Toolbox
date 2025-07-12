This directory contains code for a separate window so that the 
user can average the epochs together of multiple files AFTER pre-processing 
the files but BEFORE any post processing is applied. You are allowed to make 
GUI edits and minor bug fixes to this directory.

Tooltips should be added (if not already present) to inform the user what 
"Pooled Average" and "Average of Averages" means in the context. 

The Pooled average button means that all epochs from both datafiles will be added
to the pool and averaged simultaneously. This gives equal weight to all of the
epochs and is considered the preferred method. 

The Average of Averages method would first calculate the average of all the 
epochs in file 1, then file 2, then average file 1 and 2 together. This gives
equal weight to both files, but not all epochs. 

As with the rest of this directory, the GUI code should be kept separate from the functionality of the app. Keep 
each .py file under 500 lines if possible, and separate functions into their own files that make sense for a human
user. If any files are over roughly 500 lines, please suggest ways to break them up into smaller files. 