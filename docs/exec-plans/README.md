# Execution Plans

Use this directory for durable plans that need to survive across agent runs.

- `active/`: plans that should be read before changing the covered area. More than one active plan may exist when distinct refactor tracks overlap the same repo area.
- `future/`: approved ideas that are not active implementation work yet; read these when scoping or starting the matching effort.
- `completed/`: plans moved here after the tracked work is done.

Keep plans compact and current. Record phase status, decisions, touched areas, required doc updates, and verification commands. Small one-off changes do not need an execution plan.
