# Free Harmonic Clustering GUI v1

## Objective

Embed the clean-room Free Harmonic Clustering Analysis backend as a beta,
project-bound PySide6 tool while preserving source project metadata and the
existing one-contrast statistical contract.

## Locked Product Decisions

- Offer one ordered two-level contrast per run: paired conditions, optionally
  within one canonical group, or two independent canonical groups within one
  condition.
- Prepare first, review the frozen cohort and harmonic domain, then run 10,000
  whole-participant permutations from the in-memory prepared tensors.
- Default to Hermann automatic harmonic selection; fixed mode chooses the
  highest oddball harmonic and fills through it while dynamically excluding
  all base-rate overlaps.
- Read conditions, groups, exclusions, base/oddball rates, FFT availability,
  and workbooks from the active managed project. The tool never edits
  `project.json`, ledgers, QC state, or source workbooks.
- Use the independently reconstructed fixed 197-edge FieldTrip-style BioSemi64
  adjacency for new analyses and record its version, edge list, and hash.
- Show current-session results only, with significant clusters first. Defer
  plots, a historical-run browser, and clipboard/manuscript helpers.
- Publish additive, non-overwriting run bundles beneath
  `3 - Statistical Analysis Results/Free Harmonic Clustering Analysis/`,
  including a polished human-readable Excel workbook and machine-readable
  provenance artifacts.
- Expose the page only when Beta Tools are enabled and provide tabbed
  method/interpretation/reference information from the page header.

## Implementation Steps

- [x] Update the fixed adjacency and export workbook contract.
- [x] Add the tool-local threaded PySide6 page and information content.
- [x] Register the beta sidebar route and project-switch cleanup.
- [x] Add synthetic backend coverage and CI-only GUI smoke definitions.
- [x] Update tool architecture and user-facing documentation.
- [x] Run focused and precommit verification.
- [ ] Manually reproduce the canonical ACR Neutral Happy result through the
      GUI: 18 anxious versus 16 non-anxious, retained H1/H2, positive H1
      C1/Cz/CPz cluster, raw one-tail p approximately .0043.

The identical public inspection, preparation, and permutation APIs passed a
read-only headless replay on the canonical ACR project (raw tail
`p = .00429957`). The checkbox remains open because local Qt execution requires
separate approval for a safe visible session.

## Release Gate

The GUI is not accepted as v1 unless the canonical Neutral Happy analysis is
reproduced end to end. Automated repository tests must remain synthetic and
must not bundle or depend on the private ACR project.

## Local Qt Constraint

Do not run Qt or pytest-qt locally on Windows. Run static/import/non-GUI checks
locally, keep GUI smoke definitions for CI, and document a visible manual smoke
path.

## Scroll-Free Task Tabs Follow-Up (2026-08-15)

- [x] Replace the page-level setup/results scroll areas with gated **1. Setup**,
      **2. Review and Run**, and **3. Results** task tabs.
- [x] Keep status and context-aware actions visible in a compact footer; split
      preparation review and result tables into bounded, task-focused views.
- [x] Summarize unusually long cohort/audit values in the cards while retaining
      their full values in tooltips and completed exports.
- [x] Update the CI-only Qt smoke contract and scoped/user documentation.
- [x] Run focused and precommit non-Qt verification and record the results.

Verification:

- `verify.py --scope free-harmonic-clustering --tier focused`: passed, including
  80 backend tests.
- `verify.py --scope gui --tier focused`: passed static/import checks.
- `verify.py --scope repo --tier precommit`: audits, lint, compilation, and
  1,576 tests passed; 3 tests were skipped. Three unrelated preprocessing
  memmap tests initially hit sandbox-denied Windows temp paths, then passed 3/3
  when rerun outside the sandbox.
- Qt/pytest-qt execution remains assigned to CI or an approved visible session.

## Setup Simplification Follow-Up (2026-08-15)

- [x] Remove the redundant inline beta banner, Hermann profile card, contrast
      swap button, and visible FullFFT/base-overlap detail rows.
- [x] Consolidate the fixed statistical profile in the page-header info
      dialog's **Method** tab and point contrast-order guidance at the A/B
      selectors.
- [x] Let the Setup card and dynamically populated selectors use the available
      width, and keep paired Condition A/B choices distinct automatically.
- [x] Make the dataset-diagnostics banner identify the exact review tab and
      row where exclusions appear.
- [x] Run focused and precommit non-Qt verification and record the results.

Verification:

- `verify.py --scope free-harmonic-clustering --tier focused`: passed, including
  81 backend and method-information tests.
- `verify.py --scope gui --tier focused`: passed static/import checks.
- `verify.py --scope repo --tier precommit`: audits, lint, compilation, and
  1,580 tests passed; 3 tests were skipped.
- Qt/pytest-qt execution remains assigned to CI or an approved visible session.

## Prepare Enablement Follow-Up (2026-08-15)

- [x] Normalize the analysis-design and harmonic-mode combo-box values at the
      Qt boundary so Windows string round-tripping cannot invalidate visible
      selections and leave **Prepare Analysis** disabled.
- [x] Add CI-only pytest-qt coverage for the canonical independent-groups setup,
      including enabled state and preparation dispatch without starting real
      analysis work.

Verification:

- `verify.py --scope free-harmonic-clustering --tier focused`: passed, including
  80 backend tests.
- `verify.py --scope gui --tier focused`: passed static/import checks.
- `verify.py --scope repo --tier precommit`: audits, lint, compilation, and
  1,576 tests passed; 3 tests were skipped. Three unrelated preprocessing
  memmap tests initially hit sandbox-denied Windows temp paths, then passed 3/3
  when rerun outside the sandbox.
- Qt/pytest-qt execution remains assigned to CI or an approved visible session.
