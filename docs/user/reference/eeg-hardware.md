# EEG hardware

This page describes the development source, not the published v3.0.0 installer.
The four routes below enter the project-local BIDS adapter and the same MNE
processing pipeline. Support applies to these recording contracts, not every
product, acquisition mode, or cap sold by a manufacturer.

| Project hardware | Input | Processing policy |
| --- | --- | --- |
| BioSemi ActiveTwo | BDF | Existing validated BioSemi64 layout, selected EXG reference pair, project filters and sampling settings, final average reference. |
| BioSemi ActiveThree | BDF | Recorded scalp labels and explicit channel roles; recorded reference or selected channels; recorded coordinates or an explicitly selected template; final average reference. No default 64-channel limit. |
| Brain Products | BrainVision `.vhdr` or single-participant BVRF 1.0.0 `.bvrh`, with companions | Recorded channels, explicit reference/montage settings, and final average reference. See [format limits](brain-products.md). |
| Unicorn Hybrid Black | Raw classic BDF or continuous BDF+ | All eight declared scalp channels at native 250 Hz, final eight-channel average reference, no resampling or interpolation. |

Choose the acquisition system in **Settings > Preprocessing > EEG hardware**.
The choice, montage, and processing settings survive app restarts. Changing
hardware requires confirmation and reprocessing. Keep different acquisition
systems in separate projects. A BDF filename does not identify the hardware:
BioSemi documents the same format for ActiveTwo and ActiveThree, and Unicorn
Recorder also writes BDF. [BioSemi format documentation](https://www.biosemi.com/faq/file_format.htm),
[Unicorn Recorder manual](https://github.com/unicorn-bi/Unicorn-Recorder-Hybrid-Black/blob/main/README.md).

## ActiveThree setup

Select the actual scalp montage and channel roles. Channel count does not establish
electrode positions or reference wiring. BDF files usually need an explicitly
selected matching template when individual coordinates are unavailable. Spectral
processing can retain channels without coordinates; spatial operations cannot
invent them. A template is not a participant-specific digitization.

The initial reference keeps the recorded values unless reference channels are
selected explicitly. Mark non-scalp auxiliary signals with the channel-type
overrides before processing. This adapter does not combine hyperscanning subjects
or claim support for every auxiliary sensor. BioSemi documents variable channel
configurations and a different ActiveThree hyperscanning arrangement; those do
not imply a fixed BioSemi64 layout.
[ActiveThree specifications](https://www.biosemi.com/activethree_full_specs.htm),
[ActiveThree FAQ](https://www.biosemi.com/faq/All_questions_about_the_Active3_system.htm).

## Unicorn setup and limits

Use the Recorder's **raw** EEG output. The required scalp labels are Fz, C3, Cz,
C4, Pz, PO7, Oz, and PO8. If the file uses `EEG 1`–`EEG 8`, explicitly select
the factory mapping only after confirming the actual cap wiring. The documented
factory layout does not establish a custom configuration.
[Unicorn hardware manual](https://github.com/unicorn-bi/Unicorn-Suite-Hybrid-Black-User-Manual/blob/main/UnicornHybridBlack.md).

Toolbox keeps the native 250 Hz grid and all eight scalp channels. Missing samples
or channels are not reconstructed. Discontinuous BDF+, malformed timing,
ambiguous units/mapping, and nonfinite telemetry are rejected. When telemetry
headers declare identity-scaled unitless values, `VALID` must equal 1 and `CNT`
must contain consecutive integers; rollover needs review. Other telemetry
calibrations/units and absent telemetry remain explicitly unverified and are
preserved without rounding or reconstruction. They do not establish wireless
sample integrity. The current input contract accepts the
eight EEG channels, Status, and optional CNT/VALID/DT, BAT, ACC X/Y/Z, and
GYR X/Y/Z channels on the same native grid. These auxiliaries remain non-EEG
metadata streams. Unknown sensor channels, live Bluetooth/LSL/UDP acquisition,
CSV, and XDF are outside this route. The narrow `?V` correction requires the
previously reviewed EEG/CNT/VALID/DT/Status header pattern; other layouts must
declare recognized EEG units.

Every nonzero Status sample is an event, preserving adjacent repeated codes.
Recorded annotation events require an explicit project event policy and code
mapping; numeric annotation text is not interpreted automatically. This advanced
configuration currently has no dedicated GUI editor. Studio send logs alone do
not establish EEG-sample or physical stimulus timing.

## Preservation and validation

Import preserves originals and records source identities. BioSemi BDF and
BrainVision signal bytes remain unchanged. Unicorn retains its original BDF
under `sourcedata`; only the narrowly validated Recorder `?V` unit-header case
is normalized to `uV` in its imported copy, with packed samples unchanged.
BVRF uses the documented lossless FIF64 derivative exception. BIDS organizes
recordings and metadata; it permits multiple signal formats.
[EEG-BIDS specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html).

Generated-fixture tests establish software reading, event preservation, project
persistence, and shared-pipeline behavior. They do not measure a device's physical
gain, actual reference wiring, wireless loss, or stimulus latency. Representative
laboratory recordings and visible workflow checks remain release acceptance work.

BioSemi64-calibrated raw-channel/kurtosis reviews and spatial add-ons remain
restricted to their existing ActiveTwo64 policy. They are not enabled for
ActiveThree, Brain Products, or Unicorn merely because import succeeds. Their
unavailability does not prevent supported core spectral processing.
