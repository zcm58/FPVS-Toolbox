# Security

Security and privacy boundaries:

- Do not hardcode local user paths.
- Keep project I/O rooted in the active project context.
- Do not introduce network behavior without explicit scope.
- Do not log sensitive local data beyond existing project diagnostics.
- Keep generated outputs and manifests compatible with existing project layout.

Use `.agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` for
path-discipline checks.
