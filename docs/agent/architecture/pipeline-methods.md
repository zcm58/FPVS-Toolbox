# Processing method modules

The per-recording pipeline executes versioned methods through
`Main_App.processing.pipeline_plan`. It preserves the existing scientific
operations and their order. Each slot currently has one production method;
alternate filters, resamplers and other algorithms remain future work.

## Project workflow

`preprocessing.processing_pipeline` stores a JSON-safe schema version and a
complete map of step IDs to registered, versioned method IDs. Existing projects
without this field resolve the historical methods. New projects explicitly save
them. The existing project settings controls remain the user-facing parameter
editor: cutoff frequencies, target sampling, reference choices and optional QC
flags retain their current meanings. Settings drafts, Save/Cancel, project reload
and worker snapshots preserve the method selection.

Do not add single-option method dropdowns. When another method is implemented
and qualified, expose a compact selector within its existing settings section,
show only its relevant parameters and filter choices by recording capabilities.
Use the catalog's labels and parameter ownership as metadata, not GUI-derived
scientific policy. A method change applies to a subsequent run, never halfway
through an active run. A general pipeline editor is not yet implemented.

Unknown schemas, incomplete method maps, unknown IDs and methods selected in the
wrong slot fail explicitly. Project files cannot name Python modules or run code.
The project save transaction detects conflicting edits rather than silently
overwriting another saved selection.

## Executable boundaries

| Slots | Implementation owner and contract |
| --- | --- |
| `raw_screening`, `condition_raw_screening` | `processing/raw_channel_qc.py`; existing typed recording or block evidence, preserving review authority and disabled states. |
| `raw_spectral_screening` | `processing/raw_spectral_qc.py`; exact-span volts plus sampling/protocol settings produce `ConditionSpectralQCResult`. |
| `initial_reference`, `reference_channel_drop`, `channel_selection` | `processing/preprocess.py`; resolved recording metadata and project choices operate on the admitted Raw. |
| `temporal_filter`, `line_noise_filter`, `resample` | `processing/preprocess.py`; context-based methods preserve filter provenance, sample-grid rules and checkpoint state. |
| `bad_channel_screening` | Numerical kurtosis evidence only. Checkpoint publication, decisions and review gates remain in orchestration. |
| `interpolation`, `final_reference`, `condition_repairs` | `processing/preprocess.py`, with exact interval branches in `condition_electrode_interpolation.py`; branch interpolation/reference use the same selected methods. |
| `epoching` | `workers/process_runner.py`; approved spans produce occurrence × channel × sample arrays. Mandatory span checks and Epochs metadata remain outside the method. |
| `repetition_average` | Float64 time-domain averaging used by both spectral processing and source-ready derivatives. |
| `spectrum` | `exports/post_process.py`; microvolt time-domain values and sampling frequency produce the established frequency/amplitude arrays. |
| `full_snr`, `target_metrics`, `occurrence_average` | Existing neighboring-noise/SNR/Z/BCA calculations and aggregation, with unchanged reduction order. |

The registry order describes fixed slots and their phases. Review and admission
are separate execution paths; optional review is not falsely reported as a
mandatory numerical operation. The Raw preprocessing owner preserves its locked
reference → channel selection → FIR → optional multi-notch → resampling →
reviewed interpolation → final-reference order. Epoch and spectral owners retain
their own established sequence. There is no user-controlled reorder list.

BIDS admission, geometry validation, canonical markers, approved analysis spans,
resource admission, cancellation, review authorization and atomic output writes
remain mandatory surrounding operations. Replacing a numerical method does not
replace those safeguards. Cohort harmonic selection, Stats inference and FHC
remain separate locked contracts.

## Extension contract

The lightweight registry module imports no MNE or Qt. `PipelineStep` describes a
slot; `PipelineMethod` identifies its application-owned implementation and any
required boolean recording capabilities. `PipelineRegistry` is immutable and
retains the historical built-ins. `resolve_pipeline_plan(settings)` validates a
project selection; `PipelinePlan.execute(slot, builtin, ...)` invokes the selected
callable with the slot owner's arguments. Built-ins remain late-bound at their
current owners so public APIs and established test seams stay compatible.

Raw preprocessing methods accept `PreprocessingContext`, mutate its owned MNE
Raw and return `None`. `execute_preprocessing_stage` checks replacement methods
against the admitted channel roles/coordinates, marker samples, minimum channel
count and permitted sampling changes. Only removal/selection slots may remove
channels; only resampling may change an eligible sampling grid. Protected native
grids remain fixed. These checks do not certify a new method's scientific validity.

Occurrence aggregation receives the historical accumulated matrix and count.
For a nondefault method it also receives keyword-only `occurrence_values` (a
tuple of detached, read-only arrays in contributing-object order) and
`metric_name` (`fft`, `snr`, `z`, `bca`, `full_snr` or `full_fft`). This permits
real alternatives such as robust aggregation within that step. The default
method allocates no additional occurrence snapshots and retains its ordered
sum/count reduction.

To add a future method:

1. Implement the existing slot-specific input/output contract in its numerical
   owner or a focused module. Register a new versioned ID and callable in
   `get_pipeline_registry`; do not redefine a historical ID.
2. Declare required generic recording capabilities. Add validated method-specific
   parameter persistence and settings controls as needed; the current flat
   parameter settings remain authoritative and are not duplicated in the plan.
3. Preserve timing, channel/geometry and metadata contracts, report effective
   filter/notch support, honor cancellation, and fail instead of emitting partial
   results when the method cannot execute. Replacement exceptions have a distinct
   `PipelineExecutionError`; historical built-in exception handling is unchanged.
   Cooperative review cancellation uses the existing typed exceptions derived
   from `PipelineCancelled` and passes through dispatch unchanged.
4. Exercise full processing, QC preparation, checkpoint reuse, condition repair,
   both export paths and applicable hardware routes. A new method needs separate
   scientific evidence and acceptance, beyond the registry's software checks.
5. Update the locked method documentation and focused tests for any intended
   scientific change. New steps or changed schema semantics need an explicit
   migration; never silently fill a malformed explicit project plan.

## Identity and reuse

`pipeline_fingerprint_payload` produces no extra fields for the exact historical
plan, whether implicit or explicitly selected. Existing default numerical results,
fingerprints and caches therefore remain compatible. A different registered
method ID adds its canonical plan to preprocessing, processed-cache, preflight
evidence and processing-ledger identity. Prepared-kurtosis checkpoints inherit
the preprocessing fingerprint. Project/runtime selection disagreement fails
before a new run can label results with the wrong plan.

Checkpoint resume executes the same suffix after prepared evidence. Condition
repairs still branch from pre-interpolation data, apply interpolation and final
reference within approved intervals, then replace only those intervals in the
main stream. They are not ordinary interpolation after final reference.
Replacement repair methods may change EEG values only inside the frozen approved
spans and must return the exact prepared authoritative provenance. Channel/grid,
geometry, canonical events and all other samples are invariant. Verification
snapshots are allocated only for replacement methods; the builtin splice path
adds no signal copies.

The advanced Evoked input path already contains an averaged waveform. It rejects
a nondefault repetition-averaging selection because individual repetitions are
unavailable; ordinary Epochs and source-ready derivatives execute the same
registered averaging method.

Verification is tracked in the
[active implementation plan](../exec-plans/active/modular-processing-methods.md).
The [preprocessing contract](preprocessing-contract.md) remains the numerical
regression authority.
