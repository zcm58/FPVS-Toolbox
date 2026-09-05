# Missing condition outputs

If processing reports no input for one condition, check its condition-start
code in the original recording. A missing code may mean the recording began
after the condition started, or that part of the source was removed earlier.
FPVS Toolbox does not overwrite the source BDF. It cannot reconstruct missing
EEG samples or safely invent a condition-start time.

If you have a complete original recording, select that source and rerun
Processing. Otherwise, you can explicitly exclude just the affected condition:

1. Open **Settings > Harmonics > Review FFT Crop Exclusions**.
2. Find the row labeled **No condition output**. New missing-condition rows
   start unchecked. Check the row only if you intend to omit that condition.
3. For repeated recordings, choose **This recording** to preserve the other
   visits. Choose participant scope only if the exclusion should cover all visits.
4. Save, then rerun **Processing** before using post-processing tools.

Other conditions keep their normal processing and output requirements. These
review rows do not count toward the FFT-grid reference. Whole-recording
exclusions remain separate, and file-writing errors require their own repair.
Saving alone or selecting **Recalculate Harmonics** does not resolve the old
incomplete processing result.
