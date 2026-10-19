# Reliability

Reliability rules:

- Preserve processing order, data formats, exports, and project paths unless a
  behavior change is explicitly scoped.
- Run focused tests before broad suites.
- Use `python .agents/scripts/audit/agent_audit.py` for repo-wide harness invariants.
- GUI changes need local non-GUI checks and a documented visible/manual smoke
  path; registered pytest-qt coverage executes in CI by default, never offscreen
  locally.
- Long-running GUI work must use workers and signals, not direct UI-thread work.

Future hardware/pipeline changes follow the
[roadmap](../architecture/hardware-pipeline-studio-roadmap.md). Keep the existing
BioSemi method as a versioned compatibility baseline. Select supported stages
from explicit acquisition/montage capabilities; unsupported repairs or spatial
methods must not silently run. Freeze units, channel roles/order, event timing,
stage identities/parameters and provenance so different plans cannot reuse
incompatible caches. A new montage requires its own fixtures and evidence;
existing BioSemi calibration does not automatically transfer.

Studio interoperability needs a declared producer/version support matrix,
paired import fixtures, explicit unknown-version failures and preserved
participant/session/condition identities. Inspection/import success alone does
not establish complete scientific or timing compatibility.

See `docs/agent/quality/verification-gates.md` for commands.
