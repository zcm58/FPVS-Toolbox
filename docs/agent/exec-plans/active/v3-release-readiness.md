# FPVS Toolbox v3.0.0 Release Readiness

## Status

Reviewed 2026-10-18. **v3.0.0 was published on 2026-10-15.** Release identity,
publication, source CI, and the automated Windows installer lifecycle are
complete. Human installed-app acceptance remains unclaimed; the user deferred
hands-on checks and any resulting bug fixes. Optional private full-cohort
comparisons were stopped at the user's direction and are not active blockers.

This compact ledger retains the release evidence and remaining acceptance
paths. It does not instruct agents to rebuild or republish the immutable v3.0.0
artifact. `codex/v3-release` and the former feature branches are historical
names. Inspect the current checkout and the selected release/feature base before
work; later `v3.0.1` and BIDS feature development is not part of this release
receipt.

## Publication — 2026-10-15

The public [v3.0.0 release](https://github.com/zcm58/FPVS-Toolbox/releases/tag/v3.0.0)
uses the exact qualified installer build
`9f7480b48fbdb2549148262206fde77bdb309e22`. The full installer, update JSON, and
both SHA-256 sidecars were published together. Anonymous downloads of all four
assets matched their verified bytes.

- Installer: `FPVSToolbox-3.0.0-setup.exe`.
- Size: 213,653,545 bytes.
- SHA-256: `d5af4da2f1fed4f2612d9ecf2ec97e3aab8cf8429b6f7ca2c0ea18b129752399`.
- [Source CI](https://github.com/zcm58/FPVS-Toolbox/actions/runs/38789774709):
  8,120 tests passed, 24 skipped, including registered Qt coverage; lint and
  Windows backend checks passed.
- [Agent harness](https://github.com/zcm58/FPVS-Toolbox/actions/runs/38789774698)
  and [documentation deployment](https://github.com/zcm58/FPVS-Toolbox/actions/runs/38789774785)
  passed.
- [Native Windows acceptance](https://github.com/zcm58/FPVS-Toolbox/actions/runs/38789774834)
  passed for those exact installer bytes. Installer artifact `12000572096`
  and diagnostic artifact `11999393539` supplied the verified acceptance receipt.

The hosted Windows run covered fresh installation, launch/close/second launch,
v2.1.2 upgrade, obsolete-file cleanup, installer-triggered relaunch with process
exit 0, and fresh/upgraded uninstall. Project, output, settings, log, and
template-cache sentinels survived both uninstall paths. All 2,818 current
payload files matched the owned-file inventory; the baseline's 2,788 files
matched its authenticated catalog. Source/frozen startup of all eight tool
pages, dependencies, synthetic processing/FHC/SNR/scalp workflows, and native
ownership/rollback fixtures passed. These automated checks do not establish
human visual acceptance or representative-project scientific qualification.

## Release closeout and open-source restoration — 2026-10-15

The public home is `zcm58/FPVS-Toolbox`, seeded from verified cleaned history.
The original `zcm58/FPVS-Toolbox-Repo` remains private; its old PR references
and cached objects were not copied. Private backups preserve removed research
material. The prepared GitHub Support request was not submitted after the user
chose the new repository. Cleaned source, historical tags/releases and
[documentation](https://zcm58.github.io/FPVS-Toolbox/) are public.

Published v2.1.2 binaries query the old repository, so their first v3 upgrade
requires the public full installer. Current update/identity URLs use the new
repository. Branch cleanup later removed the old release and feature branches;
that does not remove the published release tags or change the installer.

## Product boundary

Default tools are Free Harmonic Clustering and SNR Plots. Scalp Maps, Standard
FPVS Screening, Sensitivity Analysis, LORETA Visualizer, Sequence Figure, and
Individual Detectability remain opt-in beta surfaces. A support tier is not a
claim of universal scientific validation. General study-specific inference
remains export-first; the locked preprocessing, harmonic-selection, and FHC
contracts continue to apply.

App version and manifest schema are independent: ordinary projects use schema
`2.1.0`; repeated-session projects use `2.2.0`. Missing/unversioned harmonic
profiles resolve to Legacy; new projects explicitly select the versioned
Dzhelyova/Poncet two-consecutive-failures profile.

## Post-release source maintenance

The bounded technical-debt cleanup is complete in `7b026c65`, on
`codex/technical-debt-cleanup` at the 2026-10-18 review. It splits Settings page
construction, moves runtime implementations into canonical Main App packages,
consolidates shared workbook readers/adapters, removes proven dead helpers, and
narrows demonstrated error boundaries. `Shared` and `Performance` retain
compatibility aliases. Current ownership is in the
[module map](../../architecture/module-map.md) and
[debt tracker](../tech-debt-tracker.md).

The local handoff gate passed 7,614 non-Qt tests with 25 skips. Source
[CI](https://github.com/zcm58/FPVS-Toolbox/actions/runs/39133936133) passed 8,242
tests with 24 skips, including registered Qt coverage; Linux lint and Windows
backend checks passed. The
[agent harness](https://github.com/zcm58/FPVS-Toolbox/actions/runs/39133936110)
also passed. These are source-maintenance results, not a new packaged release
or a claim that v3.0.0 contains later cleanup changes.

## 3. Qualify processing and project compatibility

Completed bounded evidence on 2026-10-15: two recordings compared baseline
`38cc8ec1` with `99e2316e`; eight native outputs, 16 NPZ comparisons, 2,656
numeric workbook cells, and other scientific workbook cells matched exactly.
Four identity cells differed as intended. Prepared-cache outputs matched and
warm resume performed no repeated work. A historical prepared FHC replay at
`31b0a1f2` matched t values, cluster labels and null arrays byte-for-byte, with
the same p-value and cohort counts. Detailed receipts remain private.

These observations qualify their compared recordings/settings only. Fresh
project preparation, the current full cohort, and the full project/drive matrix
were not qualified by the archived inputs. Do not restart private-data work as
routine verification. If explicitly resumed, use a bounded protocol from the
[performance plan](bitwise-pipeline-performance.md), preserve current user
exclusions, and report the exact evidence scope.

The following remain manual acceptance paths, not prerequisites retroactively
imposed on the published release:

- Create/open a disposable representative project; process, cancel,
  resume/rebuild, inspect QC, and verify cache invalidation and canonical
  multi-group/repeated-session routing.
- Exercise one ordinary and one slow/external-drive project when qualifying
  those storage conditions; unmeasured storage behavior stays unclaimed.
- Verify companion corruption/recovery using the
  [FullFFT plan](fullfft-numpy-companion.md), and condition repair/retry using
  the [interpolation plan](condition-specific-interpolation.md).

## Free Harmonic Clustering

The reviewed powered null-calibration receipt and routine deterministic
regression remain distinct evidence. Do not repeat powered calibration for
branding, ownership moves, UI or export-layout changes. Reassessment is required
when the numerical calibration boundary changes; see the
[calibration guide](../../quality/free-harmonic-clustering-null-calibration.md).

Registered source CI covers the embedded page, maps and reporting. A human
packaged-app run remains unclaimed. Its visible path is a small paired or
independent run, cancellation, non-overwriting output, manifest/provenance,
result-folder action, and a synthetic repeated-session batch with All
comparisons/Exploratory findings and exported maps/reporting. Use the
[reporting](fhc-exploratory-reporting.md) and
[map](fhc-harmonic-cluster-maps.md) checklists. Archived cohort replay is not
fresh packaged-app qualification and is not a default verification command.

## 5. Perform one compact installed-app acceptance pass

The user will perform hands-on checks later. No local Qt execution or human
installed-app pass is claimed. When resumed, use the exact installed version:

- Check create/open/process/QC and FHC/SNR output with a disposable project.
- Check SNR multi-group order, per-ROI counts, empty-group handling,
  cancellation and matching PNG/PDF output using the Plot Generator scoped
  instructions.
- At the supported 1280x900 workspace and relevant Windows scaling/themes,
  inspect menus, Settings, ROI draft Save/Cancel/reopen and cached-consumer
  refresh. Follow the [GUI smoke path](../../architecture/gui.md) and
  [ROI plan](sssep-style-visual-roi-selector.md).
- Enable beta tools, check the shared per-tool acknowledgement and pages,
  export a repeated-session Scalp Map with long labels, and inspect matching
  PNG/PDF layouts. Use the [map layout plan](scalp-maps-repeated-session-figure-layout.md).
- Exercise LORETA model details, source/export navigation, cancellation and
  figure layouts via the [LORETA validation guide](../../quality/loreta-validation.md).
- Check About, title bar, update dialog and installer identity against the
  installed version. Automated hosted installer lifecycle evidence above
  remains separate from this human review.

## Future work

The agreed direction is modular hardware/montage support, a versioned pipeline
whose supported stages are selected by acquisition/montage capabilities, and
full FPVS Studio compatibility. The
[hardware/pipeline/Studio roadmap](../../architecture/hardware-pipeline-studio-roadmap.md)
owns that target and its acceptance gates. It is future work, not a claim that
all hardware or Studio versions are already supported. The
[Unicorn plan](unicorn-hybrid-black-support.md) records the inspection foundation
and uncompleted production/qualification gates.

The locked BioSemi processing order and results must remain unchanged during
structural work. New methods or changes in scientific authority need their own
explicit scope, versioned provenance and updated method/testing contracts.
