# Core Beliefs

- FPVS Toolbox should preserve scientific output behavior unless a behavior
  change is explicitly requested and documented.
- Processing is the core product; analysis and visualization are optional
  downstream consumers. Prioritize pipeline correctness, reproducibility,
  extensibility, and usable project configuration.
- The repo should be legible to future agents and humans through clear package
  ownership, compact maps, and focused architecture docs.
- `AGENTS.md` is a table of contents, not an encyclopedia.
- `docs/agent/` is the source of durable product, architecture, quality, and planning
  truth.
- Refactors should be small, behavior-preserving, and verified with focused
  tests or documented smoke paths.
- Shared runtime code should use the simplest implementation that remains
  compatible with Windows 11 and CachyOS (Arch Linux); OS-specific branches
  belong only at unavoidable packaging or system-integration boundaries.
- Processing pipeline changes require contract documentation and targeted tests
  before implementation.
- Separate hardware, montage, format, and event interpretation from shared
  processing. The project-local BIDS import boundary supplies MNE Raw; resolved
  policies supply capabilities. Extend these boundaries rather than copying
  the pipeline for each device.
- Future modular processing and full Studio compatibility are acceptance goals,
  not evidence of current support. Follow the
  [shared roadmap](../architecture/hardware-pipeline-studio-roadmap.md) and keep
  unresolved acquisition, method, and interoperability gaps visible.
- GUI changes should improve usability without making processing behavior less
  inspectable or harder to test.
