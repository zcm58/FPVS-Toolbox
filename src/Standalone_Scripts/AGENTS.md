# Standalone scripts: opt-in agent boundary

## Default rule

Ignore this directory and its entire subtree unless the current user request
explicitly asks to inspect, run, audit, or edit a standalone script or workflow.
Do not list, search, read, import, execute, modify, or use files here as
precedent for active application architecture during ordinary FPVS Toolbox
work.

Relevance alone is not authorization. A general request about statistics,
figures, preprocessing, exports, or the GUI does not permit work in this
directory. If access would materially help but has not been authorized, explain
why and obtain the user's approval before entering the directory.

## After authorization

This directory is not a black box. Once the user explicitly scopes a standalone
workflow or approves access, inspect only the smallest relevant subtree and
follow any more-specific `AGENTS.md` found there. Existing standalone scripts
remain developer-operated utilities and must not be treated as active runtime,
public APIs, or architectural precedent for `Main_App` or `Tools` packages.

Keep generated analysis outputs outside the repository unless the user
explicitly requests otherwise. Do not edit generated CSV, JSON, workbook,
figure, or report files by hand when the authorized workflow can reproduce
them from source data and configuration.
