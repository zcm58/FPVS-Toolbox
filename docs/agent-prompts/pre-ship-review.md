# Pre-Ship Review Prompt Template

Use before handing off a non-trivial change.

1. Read `docs/reviews/pre_ship_checklist.md`.
2. Run `python scripts/agent_audit.py`.
3. Run the focused tests from `docs/quality/test-selection.md`.
4. Run broader gates if shared behavior changed.
5. Report failures with command, reason, and residual risk.
