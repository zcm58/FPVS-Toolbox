# Harness Engineering Reference

Source: [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/).

Repo-local interpretation:

- Keep `AGENTS.md` compact and map-like.
- Treat `docs/` as the durable system of record.
- Use execution plans for work that must survive across agent runs.
- Keep architecture, quality, reliability, and product guidance versioned in the
  repo.
- Prefer progressive disclosure: agents should know where to look next without
  reading every document by default.
- Enforce stable invariants mechanically through scripts or CI when the check is
  low-noise.
