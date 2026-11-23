---
name: legacy-boundary-review
description: Use for retired Main App or Source Localization boundaries, compatibility aliases, and refactors that preserve historical behavior through current public APIs or thin adapters.
---

# Legacy Boundary Review

## Workflow

1. Select the existing `.venv1` or `.venv` per the [development guide](../../../docs/agent/guides/development.md#local-environment). Run the wrapper before broad inspection and again after edits.

   ```console
   python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
   ```

   The wrapper checks retired Main App files, the retired Source Localization tree, and newly added Source Localization references. For committed changes, pass `--base-ref <revision>` or set `FPVS_AGENT_AUDIT_BASE_REF`. The default comparison for new references is `HEAD`.

2. Read the [legacy contract](../../../docs/agent/architecture/legacy-boundaries.md) and the relevant [canonical owner](../../../ARCHITECTURE.md). Use current public APIs and tests to understand historical behavior. When needed, keep adapters and caller-side normalization in the current purpose-based packages. Preserve processing order, exact scientific outputs, formats, exports, and workflows.
3. Keep `src/Main_App/Legacy_App/`, `src/Main_App/PySide6_App/`, and `src/Tools/SourceLocalization/` retired. Leave absent directories absent. Restoration requires explicit scope under the [root rules](../../../AGENTS.md). Leave the optional ignored `src/quarantine/` outside active runtime.
4. Preserve the `Main_App.Shared.*` and `Main_App.Performance.*` compatibility submodules as aliases to the same canonical module objects. New runtime calls use the canonical owners. Retain historical pickle lookups, logger names, resource roots, and the separate public wrappers in `src/Main_App/__init__.py` where required by their contracts. Use the [legacy-boundary focused scope](../../../docs/agent/quality/test-selection.md#scope-map) to check module identity and pickle compatibility when reviewing owner or alias changes.

   ```console
   python .agents/scripts/verify.py --scope legacy-boundary --tier focused
   ```

5. For [LORETA Visualizer](../../../src/Tools/LORETA_Visualizer/AGENTS.md), use the active implementation and contracts. The current L2-MNE and eLORETA producers live in `source_producers/`, while the renderer and adapters consume prepared payloads. Keep retired Source Localization code and quarantine out of the review.
6. For hardware, montage, pipeline-stage, or FPVS Studio changes, read the [shared roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md). Preserve the locked BioSemi order and use only qualified spatial methods.

## Response Requirements

- State the boundaries checked, any ownership or adapter changes, and the evidence for processing and output parity where applicable.
- Report the verification commands and results.
