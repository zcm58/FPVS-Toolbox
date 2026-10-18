# Pre-Ship Review Prompt Template

Use before handing off a non-trivial change.

1. Read `docs/agent/reviews/pre_ship_checklist.md`.
2. Run the relevant first command from `docs/agent/agent-index.md` before broad manual inspection.
3. Run `python .agents/scripts/audit/agent_audit.py`.
4. Run the focused tests from `docs/agent/quality/test-selection.md`.
5. Run broader gates if shared behavior changed.
6. Confirm retired `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` paths were not recreated.
7. Confirm the retired `Tools.SourceLocalization` package remains removed and the current `Tools.LORETA_Visualizer` keeps estimation isolated in `source_producers/`.
8. Report failures with command, reason, residual risk, and whether architecture docs or scoped `AGENTS.md` needed updates.
9. For hardware, montage, pipeline, or Studio changes, review the
   [shared roadmap](../architecture/hardware-pipeline-studio-roadmap.md). Report
   the exact qualified capability/version and remaining gaps; do not claim
   complete Studio compatibility from a parser test or synthetic fixture alone.
