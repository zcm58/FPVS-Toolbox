# QC-12: Protocol-Driven Rate Generalization

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, and QC-11 for the
rate foundation. Also load QC-14 when finalizing the replacement harmonic
domains.

**Status:** implementation in progress as of 2026-09-04. Support project-wide rates beyond 6/1.2 Hz
and allow either recurrence-count or direct-frequency entry. Both modes must
resolve to a whole-number stimulus recurrence. On 2026-09-04, the user
clarified that there is no universal 16.8-Hz analysis ceiling and then directed
that the live 16.8-Hz default be removed in favor of the project's filtering
settings. On 2026-09-04, the user accepted the complete +/-10-bin filter-range
rule and one shared Toolbox source of spectral eligibility.

### Implementation Progress

- `Main_App.processing.spectral_eligibility` now owns the exact technical
  domain. It combines the ready project protocol, realized exact-bin grid,
  applied nominal filter edges, Nyquist, and effective notch mask, and returns
  a reason for every unavailable target.
- Post-processing exports the complete one-sided FullFFT plus versioned
  `Spectral Eligibility` and per-channel `Spectral Metric QC` evidence. Live
  target generation no longer consumes the legacy 16.8-Hz or 40-Hz paths.
- Processing-time harmonic selection validates every included workbook's
  exported resolver evidence, takes the documented common eligible-order
  intersection, and fingerprints the protocol and per-workbook decisions.
  Adaptive profiles skip unavailable holes; fixed profiles preserve a declared
  unavailable harmonic and fail rather than silently reducing the sum.
- Managed single- and multi-group Stats paths consume the accepted
  processing-time selection. Cache misses no longer trigger an independent
  FullFFT target-list rebuild, and caller-supplied legacy ceilings are ignored
  for managed projects. Unmanaged legacy/direct APIs retain explicit historical
  values only for compatibility.
- Genuinely new projects seed the fixed/preregistered alternative by project-
  relative oddball harmonic order (upper harmonic 6). Existing projects with a
  missing mode still resolve to the historical exact 1.2-Hz list, and every
  explicitly saved fixed list remains unchanged.
- FullFFT grid QC now uses the project's exact oddball rate and declared
  expected cycle count, records the protocol fingerprint, validates rounded
  headers against exact rational spacing, and rejects rounded-label collisions.
- Neutral FullFFT provenance schema v3 now stamps and validates the canonical
  project frequency-protocol fingerprint. The post-processing worker fails on
  missing managed protocol evidence instead of stamping a global 6/1.2
  fallback, and a protocol change makes existing provenance stale.
- Condition-aware preflight crop-grid audits carry the project oddball rate and
  protocol fingerprint. Free Harmonic Clustering uses those project rates for
  frequency identity while remaining independent of the standard Stats
  selection.
- Plot Generator removes the managed-project BCA-ceiling path. It annotates
  only common technically eligible non-presentation harmonics, keeps that list
  separate from the Stats profile's selected harmonics, and clamps its display
  range to the observed FullSNR grid.
- Focused non-GUI coverage includes 3-Hz/every-10 and 10/2-Hz protocols,
  repeating-decimal rates, above-16.8-Hz eligibility, passband/Nyquist edges,
  notch holes, adaptive skipping, fixed-profile unavailability, cache
  invalidation, managed Stats consumers, neutral provenance staleness,
  protocol-aware preflight grids, and Plot Generator technical-domain behavior.
  Remaining GUI execution is reserved for CI or the documented visible smoke
  path.

## Accepted User Model

1. Provide two clear entry modes for the project oddball protocol:
   - presentation rate plus **oddball every N stimuli** (`N >= 2`); or
   - presentation rate plus a directly entered **oddball frequency**.
2. Keep the controls synchronized. Show the resolved oddball frequency and,
   when applicable, the implied integer recurrence count before saving. Store
   the chosen input mode and one canonical resolved protocol under QC-11.
3. Direct Hz entry must resolve `presentation_rate / oddball_rate` to a whole
   number `N >= 2`. Permit only a documented input/display-scale tolerance,
   then canonicalize to the exact derived `presentation_rate / N`. Show `N`
   before saving. Reject incompatible pairs with a short explanation and valid
   nearby choices; never silently round to a different protocol.
4. Use exact decimal/rational protocol identity internally; do not let display
   rounding choose FFT bins or harmonic identity. Require finite positive
   inputs and a usable result below Nyquist.

## Rate-Generalization Work

1. Replace active 1.2-Hz constants and silent 6/1.2 fallbacks in marker-gap
   checks, exact-bin crop planning, runner diagnostics, FFT/BCA targets,
   neighboring-bin exports, FullFFT grid QC, provenance callers, harmonic
   selection, Stats, labels, messages, caches, and fingerprints with QC-11's
   project protocol. Establish one pure exact base/oddball target enumerator in
   the rate foundation so the earlier QC-18 screen does not create its own
   frequency generator; later eligibility filters that sequence.
2. Preserve exact FFT-bin locking. If the marker-derived interval cannot
   provide a valid on-bin crop for the declared rate, report the conflict; do
   not select a nearest bin.
3. Remove the project-global BCA-ceiling field, GUI control, live 16.8-Hz
   default, and conflicting 40-Hz fallback. Generate base and oddball harmonics
   with exact arithmetic through the one common technically usable support
   derived from the immutable project preprocessing/filter snapshot. Profiles
   consume that canonical eligible sequence; a fixed/preregistered profile may
   declare a narrower subset. Never let a second ceiling or whichever workbook
   columns happen to exist silently define the search.
4. Represent fixed-profile defaults by harmonic order or project-aware exact
   identity instead of literal 1.2-Hz values. Preserve existing versioned
   profiles and saved exact lists through an explicit migration; do not change
   legacy project results silently.
5. Carry harmonic/bin identity and exact rate metadata across workbooks and
   Stats so repeating-decimal rates cannot fail because a displayed frequency
   header was rounded to four decimals. Preserve compatible display labels
   where they remain unique.
6. Verify oddball-marker spacing against the declared protocol as a QC result.
   This validates event timing consistency, not the monitor's physical refresh
   delivery; timing-log validation remains separate future scope.

## Accepted Filter-Owned Analysis Domain

Remove every live generic ceiling and derive analysis support from the
project's applied preprocessing settings as follows:

1. Preserve the complete one-sided FullFFT through Nyquist for audit and future
   reanalysis, with effective filter-response provenance. A bin's existence
   does not make it eligible for the standard analysis.
2. Define common usable support from exact FFT bins and the project's validated
   applied nominal filter passband, capped by Nyquist. For the current MNE FIR
   method, use the high-pass and low-pass values recorded after successful
   application as the nominal passband edges. Verify that they match the
   canonical project snapshot within a method-versioned `1e-9 Hz` representation
   tolerance; that tolerance cannot admit an additional FFT bin. Do not derive
   eligibility from an unversioned transfer-function threshold. Require a target and its complete
   QC-14 +/-10-bin neighborhood to remain inside the passband: the lowest used
   bin must be at or above the applied high-pass edge, the highest used bin must
   be at or below the applied low-pass edge, the lowest must be above DC, and
   the highest must be strictly below Nyquist. With FFT spacing
   `delta_f = sampling_rate / analyzed_samples = 1 / analyzed_duration`, require
   `target - 10*delta_f >= high_pass` and
   `target + 10*delta_f <= low_pass`, subject also to those DC/Nyquist guards.
   When a passband edge was deliberately omitted, use DC or Nyquist
   respectively. A failed or missing applied-filter result is a processing
   failure, not permission to infer the requested edge. For a
   50-Hz low-pass, use the highest exact
   harmonic whose upper tenth neighbor is at or below 50 Hz; do not
   automatically treat an exact 50-Hz target as eligible. Keep configured
   effective line-noise notches active regardless of base/oddball overlap and
   treat their attenuation support as discrete holes in eligibility rather
   than lowering the whole filter-derived boundary.
3. For the Dzhelyova/Poncet two-consecutive-failures profile, search all
   eligible harmonics through that common usable support and stop at its locked
   failure pair. Reaching technical support first leaves the cutoff unresolved.
4. Significant-only exploratory selection examines the shared eligible domain,
   records every tested harmonic and the total number tested, and remains
   explicitly exploratory because its local threshold is not a family-wise
   error correction. Fixed/preregistered selection retains its exact list,
   upper harmonic order, or upper frequency, intersected with shared technical
   eligibility.
5. Keep finite implementation/memory guards. Hitting one is a hard technical
   failure, never silent truncation. Version affected nonlegacy profiles.
   Historical artifacts retain the exact boundary actually used only as
   read-only provenance; the current resolver never consumes it, and 16.8 Hz
   is never a current default or fallback.
6. Implement one canonical spectral-eligibility resolver rather than another
   stored ceiling or duplicated target generator. It consumes the immutable
   project/run filter snapshot, exact sample rate and FFT grid, analyzed
   duration, project rates, QC-14 neighborhood contract, and method profile. It
   returns exact eligible harmonics plus a reason for every unavailable target.
   Post-processing, BCA/SNR/z export, frequency QC, adaptive selection, Stats,
   provenance, caches, and plot defaults consume that result; none rereads an
   application setting or rebuilds the target list independently. Where
   recording-condition durations or applied filters differ, calculate their
   eligibility separately and derive any shared analysis list from their
   documented intersection.
7. A target inside an effective notch attenuation band is unavailable for
   standard analysis. If only a required QC-14 noise bin intersects that band,
   the target amplitude may remain audit evidence, but its BCA, SNR, and local
   z are unavailable. Adaptive profiles skip such holes without treating them
   as significant or nonsignificant harmonics; two-consecutive-failure logic
   continues across the next eligible harmonic. A fixed/preregistered profile
   preserves its declared list and reports the affected result unavailable
   rather than silently calculating a reduced sum. Never exclude an entire
   recording-condition solely because one frequency was deliberately notched.

## Owners and Acceptance

Owners span `config.py`, `Main_App/Shared/fft_crop_utils.py`, the active process
runner, `Main_App/processing/fft_multinotch.py`, post-processing and Excel
exports, FullFFT/frequency QC, QC-11
provenance and fingerprints, and Stats harmonic-policy consumers. Update the
locked FFT-crop, post-processing/export, preprocessing, project-I/O, GUI, and
methods-reporting contracts with the implementation.

Acceptance covers unchanged per-frequency 6/1.2 results inside the previously
analyzed range plus an explicit versioned transition to the expanded domain;
3 Hz with every tenth stimulus (0.3 Hz); a published-style 10/2-Hz protocol; a valid repeating-decimal rate;
targets above 16.8 Hz when technically supported; exact high-pass, low-pass,
and Nyquist boundaries; complete +/-10-bin inclusion at each filter edge;
shared-resolver parity across all consumers; insufficient crop length;
marker-rate mismatch; rounded-header collision; legacy fixed/profile domains;
protocol changes requiring
reprocessing; and both GUI entry modes. Run focused non-GUI gates and document
a visible GUI smoke path. Qt execution remains CI-only.
