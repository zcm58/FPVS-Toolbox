# Execution Plans

Use this directory for durable plans that need to survive across agent runs.

- `active/`: plans that should be read before changing the covered area. More than one active plan may exist when distinct refactor tracks overlap the same repo area.
- `future/`: approved ideas that are not active implementation work yet; read these when scoping or starting the matching effort.
- `completed/`: placeholder only. Completed plans are removed by default so
  routine agent work does not pay token cost for historical implementation logs.
  Use git history only when the user explicitly asks for completed-plan context.
- `tech-debt-tracker.md`: known debt that is not yet promoted to an active plan.

Keep plans compact and current. Record phase status, decisions, touched areas, required doc updates, and verification commands. Small one-off changes do not need an execution plan.

## Active Acquisition Support

- [Unicorn Hybrid Black support](active/unicorn-hybrid-black-support.md): active
  Phase 0 / early Phase 1 read-only format/acquisition/event inspection with
  raw BDF and continuous BDF+ fixtures and explicit discontinuity gates.
  The registered Unicorn policy requires native 250 Hz, eight-channel average
  reference and no interpolation; production preprocessing integration is not
  yet enabled. Existing BioSemi processing is unchanged. Implementation branch:
  `codex/unicorn-headset-support`; scientific qualification remains gated by
  source evidence and the plan's acceptance criteria.

## Active QC Implementation

- [QC scientific review and protocol flexibility](active/qc-scientific-and-protocol-flexibility.md):
  active v3-based implementation plan with 21 approved actions. During each
  action, load its shared contracts, its module, and only the dependencies named
  there. QC-15 is execution priority 1.
- [Analysis-window scope of preprocessing](future/analysis-window-preprocessing-scope.md):
  separate future evidence investigation. It does not authorize a temporal
  preprocessing change in the active QC implementation.
