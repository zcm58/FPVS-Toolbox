# Brain Products recordings

This feature is developed on the v3.0.1 feature branch; it is not part of the
published v3.0.0 installer.

Select **Brain Products** when creating the project or in **Settings >
Preprocessing > EEG hardware**. The setting belongs to the project and survives
app restarts. Opening BrainVision recordings offers a hardware confirmation.
Changing an existing hardware choice requires a warning and reprocessing;
keep each hardware platform in its own project.

## Files and setup

Select the recording header, leaving its companions together:

| Format | Header | Companions |
| --- | --- | --- |
| BrainVision Core Data Format | `.vhdr` | Referenced `.vmrk` and signal file, normally `.eeg` |
| BrainVision Recording Format 1.0.0 | `.bvrh` | Same-stem `.bvrm`, `.bvrd`, and optional `.bvri` |

The reader uses the saved channel names, sample rate, units, and calibration.
It does not choose an amplifier or cap from channel count. Numeric `Stimulus/S`
markers supply the condition and oddball event stream; `Response/R` markers
are retained as annotations and are not treated as stimulus codes.

Choose the actual recording montage. **Recorded coordinates** keeps available
recorded positions; if positions are absent, spectral processing remains possible
but interpolation is unavailable. A selected standard montage is a template,
not participant-specific digitization. Never select a cap solely because its
channel count matches. Channel-type overrides, such as `VEOG=eog`, can exclude
auxiliary channels from scalp analysis when a file does not identify their role.
For BVRF, recorded CapTrak positions require complete EEG electrode composition
and coordinates, plus nasion/left/right preauricular fiducials in the same
CapTrak coordinate frame. Electrode and fiducial units must both be declared as
millimetres. Unanchored or MNI positions are not treated as individual head
coordinates.

The initial reference defaults to the reference already present in the samples.
You may choose recorded reference channels explicitly and choose whether to drop
them afterward. Processing finishes with the shared average EEG reference.
All recorded EEG channels are retained by default; no 64-channel limit is applied.

## Scope

Support is defined by the recording format and declared channel semantics,
not an exhaustive list of amplifier models. BVRF currently accepts a single
participant per recording, the documented four numeric sample types, and
version 1.0.0. Unsupported versions, ambiguous units, incomplete companions,
and stimulus collisions that cannot be represented faithfully are errors.
Export each participant separately for a multi-participant BVRF acquisition.
Supply continuous, unaveraged, referential scalp EEG. The reader rejects
segmentation/averaging declared in BVCDF headers, acquisition gaps identified by
markers, and bipolar EEG explicitly declared in BVRF channel composition. It
cannot detect every incompatible acquisition when that metadata is absent.

BioSemi-calibrated automatic raw-channel/kurtosis screens and their review
policies are unavailable for Brain Products. LORETA, Scalp Maps, and Free Harmonic
Clustering currently require the qualified BioSemi64 spatial model and are
unavailable for Brain Products projects. Source-format tests establish software reading
and processing behavior; they do not establish an amplifier's physical gain
calibration or stimulus-to-EEG latency.

Spectral group analysis preserves individual digitizations and requires matching
ordered scalp-channel identities and processing policies. A configured ROI whose
electrodes were not recorded has missing values with explicit availability
reporting; the software does not substitute nearby electrodes. Valid configured
ROIs remain usable. The existing BioSemi scalp-map ROI editor does not configure
arbitrary custom cap labels.

Future Studio importers can supply hardware evidence for confirmation. The
current Studio interchange is not assumed to contain a verified hardware field.

## Format references

- [Brain Products BVCDF specification](https://www.brainproducts.com/download/specification-of-brainvision-core-data-format-1-0/)
- [Brain Products BVRF documentation](https://www.brainproducts.com/support-resources/brainvision-recording-format/)
- [BVRF 1.0.0 header schema](https://www.brainproducts.com/schemas/json/BVRF/BVRFHeader-1.0.0.json)
- [Vendor BVRF reader](https://github.com/brain-products/bvrf_reader)
- [MNE 1.9 BrainVision reader](https://mne.tools/1.9/generated/mne.io.read_raw_brainvision.html)
- [MNE standard montage definitions](https://mne.tools/1.9/generated/mne.channels.make_standard_montage.html)
