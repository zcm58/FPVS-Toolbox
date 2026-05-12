# Reliability

Reliability rules:

- Preserve processing order, data formats, exports, and project paths unless a
  behavior change is explicitly scoped.
- Run focused tests before broad suites.
- Use `python .agents/scripts/audit/agent_audit.py` for repo-wide harness invariants.
- GUI changes need pytest-qt coverage or a documented manual smoke path.
- Long-running GUI work must use workers and signals, not direct UI-thread work.

See `docs/quality/verification-gates.md` for commands.
