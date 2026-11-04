# Agent Knowledge Base

Start with root [AGENTS.md](../../AGENTS.md) and the
[agent index](agent-index.md). Use [ARCHITECTURE.md](../../ARCHITECTURE.md)
for ownership, then read only the focused contract needed for the task.
User documentation lives in `docs/user/`; shell setup belongs in
[development](guides/development.md).

## Directory Map

| Directory | Contents |
| --- | --- |
| `architecture/` | Runtime ownership and behavior contracts. |
| `design-docs/` | [Design](design-docs/DESIGN.md), [PySide6 frontend](design-docs/FRONTEND.md), and [product direction](design-docs/PRODUCT_SENSE.md). |
| `exec-plans/` | [Active/future plan routing](exec-plans/README.md) and [bounded debt](exec-plans/tech-debt-tracker.md). |
| `guides/` | Developer setup and maintenance. |
| `product-specs/`, `references/` | Product workflows and reference material. |
| `generated/` | Generated references; do not edit by hand. |
| `quality/` | [Test selection](quality/test-selection.md), [gates](quality/verification-gates.md), [quality posture](quality/QUALITY_SCORE.md), [reliability](quality/RELIABILITY.md), and [security](quality/SECURITY.md). |
| `reviews/` | [Pre-ship checklist](reviews/pre_ship_checklist.md) and scoped review evidence. |

Current contracts describe checked-out source. The
[hardware/pipeline/Studio roadmap](architecture/hardware-pipeline-studio-roadmap.md)
separates implemented support from future goals. Release tags and their
acceptance receipts define shipped behavior; historical reviews apply only to
their named revision. Keep detailed methods, calibration, and evidence in their
focused contracts instead of duplicating them in routing pages.
