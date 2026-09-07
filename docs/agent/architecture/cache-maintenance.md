# Cache Maintenance

Cached numerical results are disposable copies, separate from recordings,
analysis NumPy companions, exported results, reviewed decisions, and processing
ledgers. Clearing caches must not change numerical methods or output readiness.

## Automatic QC Retention

`processing/preflight_qc_cache.py` publishes complete checksummed JSON entries.
`processing/preflight_qc_pruning.py` manages replacement within logical recording,
event, and condition-occurrence slots. Numerical settings remain part of the
cache fingerprint; a completed calculation under changed settings can replace
older entries for that same logical slot.

Only validated, unchanged entries recorded before successful publication are
eligible for deletion. A different occurrence, an excluded occurrence with no
replacement, an incomplete write, cancellation, corrupt/unrecognized metadata,
or an ambiguous source identity must not authorize pruning. Source state is
rechecked. Slot indexing handles existing valid entries once, without repeatedly
scanning all JSON evidence for every condition. Cross-process publication locks
are non-blocking and released by the OS after a crash; their files are retained.

## Explicit Cache Clearing

Advanced settings delegates to `gui/toolbox_cache_workflow.py` and
`workers/toolbox_cache_worker.py`. Inventory and removal run outside the UI
thread. A concrete file-count/size preview precedes removal; the dialog holds
the existing processing start/navigation guard and blocks clearing during work.

`processing/toolbox_cache.py` and `toolbox_cache_paths.py` discover only known
disposable caches in the active project, projects under the configured projects
folder, and canonical app-owned cache locations. They revalidate inventoried
files and path boundaries before removal, reject symlink/junction redirects,
retain live memory maps and publication-lock files, and report skipped or
failed items. Unregistered custom output folders are not searched. The Stats
manifest cache is separate from the accepted harmonic selection; only that
cache record is removable and the active project object must be synchronized.

Downloaded anatomical templates, project settings, source recordings, analysis
companions/exports, processing ledgers, and review decisions are preserved.
Clearing saved caches does not destroy data already displayed by open tools;
reopening tools or restarting releases remaining tool memory.

Restore excluded participants through **Manage Dataset Exclusions** in Settings,
not cache clearing. Removing the final manual processing exclusion now releases
the cached manual skip on the next processing plan. Clearing cache entries
continues to preserve saved processing and analysis exclusion decisions.

## Visible Smoke (Local Qt Execution Is Not Required)

Open Settings → Advanced while idle and choose Clear Toolbox Cache. Confirm
the count/size and optional location details, then Cancel and verify no files
changed. Repeat with disposable test-project caches, clear them, and confirm
results/settings/decisions remain. Check Stop, missing/locked files, and busy
processing/tool states. Run QC again to repopulate caches; change one condition
or setting and confirm only replaced logical entries are pruned.
