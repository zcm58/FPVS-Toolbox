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
- Expose the page only when Beta Tools are enabled. Show a non-blocking beta
  banner and tabbed method/interpretation/reference information.

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
