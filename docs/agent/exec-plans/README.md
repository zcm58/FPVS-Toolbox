# Execution Plans

Use this directory for durable plans that survive across agent runs. Review
status was reconciled with the repository on 2026-10-19.

- `active/`: unfinished implementation, qualification, or visible acceptance.
  A retained plan may describe implemented code while preserving uncompleted
  acceptance; its opening status distinguishes these cases.
- `future/`: scoped ideas without active implementation. Read when starting the
  matching effort; a future plan does not override current scientific contracts.
- `completed/`: placeholder only. Remove completed plans after durable contracts
  and any remaining checks have an owner. Use Git history for old implementation
  chronology when explicitly requested.
- `tech-debt-tracker.md`: unresolved bounded maintenance and review context.

Keep plans compact. Date evidence, distinguish source tests from installer and
human acceptance, and retain no completed check as an open blocker. Old branch
names and baseline hashes in dated implementation records are historical
provenance, not checkout instructions; inspect current Git state before work.
The former `codex/v3-release` branch is historical. Current work may use an
explicitly selected release base such as `codex/v3.0.1-release`; do not switch
or merge branches merely because a historical plan names `main`.

## Current routing

| Area | Current status / plan |
| --- | --- |
| v3.0.0 | [Published release ledger](active/v3-release-readiness.md): exact installer and automated lifecycle qualified; human installed-app acceptance deferred by the user. |
| Modular hardware, montage-selected pipeline, FPVS Studio | [Durable roadmap](../architecture/hardware-pipeline-studio-roadmap.md): agreed future direction and evidence gates; full compatibility is a goal, not an implemented claim. |
| Brain Products | [Processing support](active/brain-products-support.md): supported BrainVision routes and persistent project hardware are implemented; laboratory and visible acceptance remain pending. |
| BIDS/shared MNE pipeline | [Import and comparison](active/bids-shared-pipeline.md): project-local import and shared processing implemented; requested synthetic equivalence passed. This is source-branch evidence, not a released installer or arbitrary pipeline editor. |
| Unicorn Hybrid Black | [Acquisition plan](active/unicorn-hybrid-black-support.md): read-only inspection, unit-correct Raw adapter and project profile metadata exist; production preprocessing and hardware qualification remain gated. |
| QC scientific/protocol work | [QC plan](active/qc-scientific-and-protocol-flexibility.md): all 21 action implementations integrated; empirical calibration and manual acceptance remain bounded by the associated modules. QC-15 is no longer an unstarted priority. |
| QC/processing performance | [QC reuse](active/qc-performance.md) and [bitwise performance](active/bitwise-pipeline-performance.md): implemented, source CI passed; optional broader private-data qualification stopped, visible acceptance unclaimed. |
| Project integration | [Multi-group](active/multi-group-project-foundation.md): shared index implemented; Individual Detectability still lacks explicit group controls. [Repeated sessions](active/repeated-session-project-foundation.md) and [FullFFT companions](active/fullfft-numpy-companion.md): implemented, visible acceptance retained. |
| Combined-study trigger maps and identities | [Implementation plan](active/source-trigger-maps-and-participant-identity.md): design scaffold only; source-specific condition/oddball maps, group setup, and distinct source-local participant labels. Runtime implementation has not started. |
| Feature-specific manual acceptance | [Condition repair](active/condition-specific-interpolation.md), [FHC reporting](active/fhc-exploratory-reporting.md), [FHC maps](active/fhc-harmonic-cluster-maps.md), [Scalp Map layout](active/scalp-maps-repeated-session-figure-layout.md), [ROI editor](active/sssep-style-visual-roi-selector.md), [source PSD](active/hauk-source-psd.md), and [LORETA improvements](active/loreta-validated-improvements.md): implemented; preserve contracts and visible checks without repeating completed development. |
| Timing investigations | [Original-rate epoching](active/original-rate-epoching-investigation.md) and [analysis-window scope](future/analysis-window-preprocessing-scope.md): investigations only; no authorization to change the locked processing order or numerical method. |
| Technical debt | The bounded 2026-10-18 cleanup is complete. The [tracker](tech-debt-tracker.md) retains larger architectural review signals without calling them proven bugs. |

## Evidence discipline

- Do not restart real-project/cohort comparisons merely because an old plan has
  an unchecked item. The release ledger records the user's deferral; routine
  verification uses synthetic fixtures and the normal verification driver.
- Source CI success does not qualify a rebuilt installer. Native automated
  acceptance does not establish human visual/scientific review.
- Acquisition inspection is not production processing or hardware validation.
  Montage support requires qualified channel roles/geometry/units, event timing,
  stage capabilities, provenance and downstream-tool compatibility.
- FPVS Studio schema/version support must be demonstrated with current producer
  documentation and paired fixtures. Do not infer a contract from a project name
  or silently accept unknown metadata.
