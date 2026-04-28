# Bugfix Prompt Template

Use when fixing a specific defect.

1. Reproduce or identify the failing behavior.
2. State the smallest safe interpretation of the bug.
3. Add or update a focused test when practical.
4. Implement the narrowest fix.
5. Run `python scripts/agent_audit.py` and the focused test.
6. Report files changed, verification, and any residual risk.
