# Public Experiment Library

**Status** · Implemented on `codex/GUI_Polish` and publicly published on 2026-11-17.
Windows source acceptance passed on the internal laptop display.

## Task and acceptance

Implement the approved flat mockup at **View → Experiment Library** on Welcome
and in an open project. The public **Simulated FPVS-Oddball Demo** requires no
OpenFPVS account or lab membership. Its description is “Simulated FPVS-oddball
experiment. Download this to test FPVS Toolbox on your PC.”

The primary action downloads an immutable public package, verifies its archive
and per-file digests, installs atomically under the configured projects root,
and opens the normal Toolbox Home. Existing installations offer **Open project**
and preserve local processing outputs. Discovery and installation stay in workers.
Cancellation and failures leave no partial project. Offline reopening uses an
explicit installed receipt.

The 32 paired synthetic recordings, processing protocol and measured reference
results are described in the [dataset specification](../future/color-oddball-demo-dataset.md).
The public data release uses CC BY 4.0 and includes a recommended dataset citation,
following the user's request for attribution on 2026-11-17.

## Work

- [x] Native page, menu and worker lifecycle, with flat content and one action area.
- [x] Anonymous typed catalog, verified installation and offline reopening.
- [x] Data-only release archive, public OpenFPVS publication and anonymous round trip.
- [x] Focused non-Qt checks, registered Qt coverage, repository precommit and docs checks.
- [x] Visible review on the approved internal laptop display.

## Evidence

The exact 251,090,004-byte public release passed full archive/member validation,
current ClamAV scanning and signed admission. A fresh, unlinked native Toolbox
session downloaded, verified and installed it through OpenFPVS, opened all 32
participants and enabled Start Processing. The normal installed reopen and a
simulated unavailable-network reopen both passed. The complete live native
delivery/open/reopen sequence took 22.17 seconds on this laptop.

Focused checks passed with 795 GUI/non-Qt tests and 1,236 project-I/O tests.
The bounded repository precommit passed with 150 tests. Seven scoped native Qt
tests passed on the laptop display, and all three new page tests passed again
after the typography review. Strict MkDocs, the verification registry, all
OpenFPVS Node tests and the service dry build passed.

The next release acceptance covers the rebuilt Windows installer and supported
cross-platform targets.

## Branch reconciliation

On 2026-11-17, remote GUI polish and current main were integrated with the
Library and local layout refinements. The Library uses the shared menu action
registry and the current 1200 × 800 shell. Its title style uses the retained
canonical font-size/weight helpers. The workflow guide lives in
`docs/agent/guides/experiment-library.md`.

The merged source passed 795 GUI checks, 1,347 project checks, 10 native laptop
Qt cases and 459 repository precommit tests. Processing checks passed 3,713
cases initially; five cases passed on repeat with shorter temporary paths after
the first run exceeded Windows path limits. A fresh live anonymous Library
download again opened all 32 participants, enabled processing and reopened the
installed project through the shared actions.

## Visible acceptance

At the current 1200 × 800 application size in Light and Dark, open the Library from Welcome
and an active project. Inspect loading, empty/offline/error, download, verification,
setup, cancellation/retry and installed states. The dataset and preview stay in
place during installation, and all actions and wrapped copy fit without page
scrolling. Verify keyboard navigation and disabled motion. Download into an empty
projects root, open Home, inspect 32 participants and both conditions, then reopen
offline without changing processed outputs. The native source installation is
distinct from installer qualification.
