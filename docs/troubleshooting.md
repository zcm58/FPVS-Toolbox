# Troubleshooting

Use this page when setup, processing, exports, or statistics are not working as expected.

Use this page for common setup, processing, and stats issues.

## Installation and startup

### App starts but cannot save outputs

- Verify your project root is a local writable folder.
- Avoid cloud-synced roots (OneDrive, network sync folders).
- Check that you have write permissions for the selected folder.

### Antivirus warning during install

Some environments flag unsigned installers. Verify you downloaded from the official project release page, then follow your institution's security policy.

## Processing issues

### "No events found" or missing condition outputs

- Confirm the selected `stim_channel` matches your recordings.
- Verify condition trigger codes in project settings match your PsychoPy task.
- Check that each condition has events in the raw file.

### Too many rejected channels or unstable results

- Review preprocessing thresholds (especially kurtosis rejection Z).
- Check whether channel labels and montage mapping are correct.
- Confirm raw data quality before strict rejection settings.

### Participant file not exported

- Check logs for condition-level warnings (zero events or zero epochs).
- Confirm the source `.bdf` file is readable and not locked by another process.

## Statistical issues

### RM-ANOVA fails due to missing cells

RM-ANOVA expects balanced repeated measures. Use mixed model analysis if a small number of condition x ROI cells are missing.

### Very different results between RM-ANOVA and mixed model

This can happen with imbalance, exclusions, or model assumptions. Compare included participants and data completeness before interpretation.

### Too many significant post-hoc results

Review correction method and family scope. Prefer corrected p-values and effect sizes for conclusions.

## Still blocked?

- Review [FAQ](faq.md)
- Re-run with a small pilot subset first
- Save logs and settings before requesting support
