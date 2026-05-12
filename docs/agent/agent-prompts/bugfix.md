# Bugfix Prompt Template

Use when fixing a specific defect.

1. Start from `docs/agent/agent-index.md` and run the narrowest relevant audit or skill-local script before broad manual inspection.
2. Reproduce or identify the failing behavior.
3. State the smallest safe interpretation of the bug and any assumptions.
4. Add or update a focused test when practical; otherwise document a manual smoke check.
5. Implement the narrowest behavior-preserving fix.
6. Run `python .agents/scripts/audit/agent_audit.py` plus the focused test or check for the touched area.
7. Report files changed, verification, skipped checks, residual risk, and why architecture docs did or did not need updates.

Preserve existing processing order, data formats, exports, project paths, and user workflows unless the bug explicitly requires changing them.
