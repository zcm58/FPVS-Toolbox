# Technical Debt Tracker

The five backend performance items are implemented. The [performance measurements](active/bitwise-pipeline-performance.md#dataset-indexing-and-spectral-exports) record their scope and parity checks.

Large QC, Stats, source and worker modules remain review candidates. Size,
broad-exception counts and absence of direct calls do not prove a bug or dead
code. Review one coherent responsibility with behavioral evidence; preserve
scientific kernels, public/compatibility APIs and terminal cleanup boundaries.
Current ownership lives in the [module map](../architecture/module-map.md) and
[Main App layout](../architecture/main-app-target-layout.md), not dated censuses.

For each new item, record a stable `TD-###` ID, owner, concrete evidence, bounded
next step and observable completion condition. Reverify before implementation;
move active work to an execution plan. Remove fixed/accepted items after updating
durable contracts, using Git history for completed cleanup chronology.
