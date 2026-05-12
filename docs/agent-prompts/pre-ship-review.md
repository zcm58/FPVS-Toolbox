# Pre-Ship Review Prompt Template

Use before handing off a non-trivial change.

1. Read `docs/reviews/pre_ship_checklist.md`.
2. Run the relevant first command from `docs/agent-index.md` before broad manual inspection.
3. Run `python .agents/scripts/audit/agent_audit.py`.
4. Run the focused tests from `docs/quality/test-selection.md`.
5. Run broader gates if shared behavior changed.
6. Confirm retired `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` paths were not recreated.
7. Confirm Source Localization/eLORETA remains removed from active runtime unless explicitly restored.
8. Report failures with command, reason, residual risk, and whether architecture docs or scoped `AGENTS.md` needed updates.
