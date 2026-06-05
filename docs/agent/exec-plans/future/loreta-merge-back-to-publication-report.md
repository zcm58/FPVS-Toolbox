# LORETA Merge-Back To Publication Report Branch

## Status

Future plan. Use after Phase 1 of `codex/loreta-3d-visualizer` is verified.

## Goal

Merge the LORETA visualizer branch back into `codex/publication-report-workflow` before merging the publication-report branch into main.

## Steps

1. Verify `codex/loreta-3d-visualizer` with the focused non-offscreen checks from `loreta-3d-visualizer.md`.
2. Switch to `codex/publication-report-workflow`.
3. Merge `codex/loreta-3d-visualizer` into `codex/publication-report-workflow`.
4. Resolve conflicts in favor of preserving both Publication Report work and the embedded LORETA sidebar/tool integration.
5. Rerun GUI, legacy-boundary, source-localization, and publication-report checks before any merge toward main.

## Safety Notes

- Do not merge LORETA directly to main while `codex/publication-report-workflow` is still the integration branch.
- Keep `src/Tools/SourceLocalization/**`, retired Main App paths, preprocessing, Stats methods, and project I/O unchanged unless separately scoped.
