"""Detached, project-owned drafts for the optional guided processing setup.

The editor uses the existing method registry and scientific validators. Saving
patches processing settings in one manifest transaction; it never executes the
pipeline, removes results, or publishes unrelated application settings.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, TYPE_CHECKING

from Main_App.processing.pipeline_plan import (
    PIPELINE_STEPS, resolve_pipeline_plan,
)
from Main_App.processing.pipeline_settings_freshness import (
    apply_pipeline_setup_freshness, pipeline_settings_identity,
)
from .experimental_qc_settings import (
    ExperimentalQcSettings, normalize_experimental_qc_settings, normalize_project_experimental_qc_settings,
)
from .frequency_protocol import (
    FrequencyProtocol, FrequencyProtocolError, normalize_frequency_protocol,
    validate_protocol_condition_codes,
)
from .hardware import (
    HardwareChangeConfirmationRequired, brain_products_qc_defaults,
    confirm_hardware_selection, hardware_supports_calibrated_qc,
    require_hardware_ready, resolve_hardware, RECORDED_GEOMETRY_PLATFORMS,
)
from .manifest_store import manifest_file_path, project_manifest_transaction
from .preprocessing_settings import (
    confirm_removed_electrode_detection_choice, normalize_preprocessing_settings,
    require_removed_electrode_detection_choice_ready, RemovedElectrodeDetectionConfirmationRequired,
    SUPPORTED_ELECTRODE_MONTAGES, SUPPORTED_ELECTRODE_MAPPING_PROFILES,
)
from .project import _electrode_geometry_settings, _pipeline_settings, _preprocessing_manifest_payload
from .recordings import project_recording_context_from_manifest

if TYPE_CHECKING:
    from Main_App.io.recording_contract import RecordingContract
    from .project import Project


@dataclass(frozen=True)
class PipelineSetupPage:
    id: str
    label: str
    stage_ids: tuple[str, ...] = ()


PIPELINE_SETUP_PAGES = (
    PipelineSetupPage("recording", "Recording setup"),
    PipelineSetupPage("reference", "Reference & channels", (
        "initial_reference", "reference_channel_drop", "channel_selection")),
    PipelineSetupPage("filtering", "Filtering", ("temporal_filter", "line_noise_filter")),
    PipelineSetupPage("resampling", "Resampling", ("resample",)),
    PipelineSetupPage("qc", "Channel QC & repair", (
        "raw_screening", "condition_raw_screening", "raw_spectral_screening",
        "bad_channel_screening", "interpolation", "final_reference", "condition_repairs")),
    PipelineSetupPage("epochs", "Epochs & spectra", (
        "epoching", "repetition_average", "spectrum", "full_snr", "target_metrics", "occurrence_average")),
    PipelineSetupPage("review", "Review"),
)
_PAGES = {page.id: page for page in PIPELINE_SETUP_PAGES}
_STAGE_PAGES = {stage: page.id for page in PIPELINE_SETUP_PAGES for stage in page.stage_ids}
_NAMESPACES = ("preprocessing", "frequency_protocol", "experimental_qc")
_METHOD_LABELS = {
    "qualified_raw_screening_v1": "Qualified raw-signal screening",
    "qualified_condition_screening_v1": "Qualified condition screening",
    "condition_spectral_screening_v1": "Condition spectral screening",
    "resolved_reference_v1": "Configured initial reference",
    "selected_reference_drop_v1": "Configured reference-channel removal",
    "ordered_scalp_limit_v1": "Ordered scalp-channel selection",
    "fir_hamming_zero_double_v1": "FIR · Hamming · zero-double phase",
    "fft_multinotch_v1": "FFT multi-notch",
    "guarded_fft_resample_v1": "FFT resampling",
    "reviewed_kurtosis_v1": "Reviewed kurtosis screening",
    "mne_spherical_spline_v1": "MNE spherical-spline interpolation",
    "scalp_average_v1": "Scalp average",
    "reviewed_interval_repairs_v1": "Reviewed condition intervals",
    "reviewed_onbin_epochs_v1": "Reviewed, frequency-aligned epochs",
    "float64_repetition_mean_v1": "Arithmetic mean of repetitions",
    "fft_amplitude_v1": "FFT amplitude spectrum",
    "neighbor_noise_full_snr_v1": "Neighboring-noise SNR",
    "fpvs_neighbor_noise_v1": "FPVS neighboring-noise metrics",
    "equal_occurrence_mean_v1": "Equal-weight occurrence mean",
}
_FIELD_PAGES = {
    "hardware_platform": "recording", "hardware_confirmed": "recording",
    "hardware_selection_source": "recording", "acquisition_profile": "recording",
    "electrode_montage": "recording", "electrode_mapping_profile": "recording",
    "channel_types": "recording", "recording_event_policy": "recording", "stim_channel": "recording",
    "ref_chan1": "reference", "ref_chan2": "reference", "initial_reference": "reference",
    "initial_reference_channels": "reference", "drop_reference_channels": "reference",
    "max_chan_idx_keep": "reference", "low_pass": "filtering", "high_pass": "filtering",
    "line_noise_filter_enabled": "filtering", "line_noise_frequency_hz": "filtering",
    "downsample": "resampling",
}
_FIELD_LABELS = {
    "high_pass": "High-pass cutoff (Hz)", "low_pass": "Low-pass cutoff (Hz)",
    "downsample": "Target sampling rate (Hz)", "max_chan_idx_keep": "Retained scalp channels",
    "ref_chan1": "Initial reference channel 1", "ref_chan2": "Initial reference channel 2",
    "reject_thresh": "Kurtosis threshold", "hardware_platform": "EEG hardware",
}


class PipelineSetupConflict(ValueError):
    """The project changed after the draft was opened; reload before saving."""


@dataclass(frozen=True)
class PipelineSettingChange:
    section: str
    key: str
    label: str
    before: Any
    after: Any


@dataclass(frozen=True)
class PipelineControlPolicy:
    """Project-owned form applicability; numerical capabilities remain separate."""

    initial_reference_editable: bool
    initial_reference_editor: str
    montage_editable: bool
    mapping_editable: bool
    channel_roles_editable: bool
    channel_limit_editable: bool
    allowed_montages: tuple[tuple[str, str], ...]
    allowed_mappings: tuple[tuple[str, str], ...]


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError("The project manifest must contain a JSON object.")
    return value


def _namespace_snapshot(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    return deepcopy({key: manifest[key] for key in _NAMESPACES if manifest is not None and key in manifest})


def _live_state(project: Project) -> dict[str, Any]:
    return {
        "preprocessing": deepcopy(normalize_preprocessing_settings(project.preprocessing)),
        "frequency_protocol": normalize_frequency_protocol(project.frequency_protocol).to_manifest(),
        "experimental_qc": normalize_experimental_qc_settings(project.experimental_qc_settings).to_manifest(),
    }


def _saved_state(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw = manifest.get("preprocessing", {})
    try:
        preprocessing = normalize_preprocessing_settings(raw, allow_legacy_inversion=True)
    except ValueError:
        if "hardware_platform" in raw or "processing_pipeline" in raw:
            raise
        preprocessing = normalize_preprocessing_settings({})
    qc = normalize_project_experimental_qc_settings(manifest)
    if "experimental_qc" not in manifest and not hardware_supports_calibrated_qc(preprocessing):
        qc = brain_products_qc_defaults(qc)
    protocol = (normalize_frequency_protocol(manifest["frequency_protocol"]) if "frequency_protocol" in manifest
                else FrequencyProtocol.confirmation_required())
    return {"preprocessing": preprocessing, "frequency_protocol": protocol.to_manifest(), "experimental_qc": qc.to_manifest()}


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    result = {}
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, Mapping) and child:
            result.update(_flatten(child, name))
        else:
            result[name] = child
    return result


def _live_manifest_after_save(live: Mapping[str, Any], saved: Mapping[str, Any], *, freshness_changed: bool) -> dict[str, Any]:
    """Prepare all potentially failing merges before the atomic publication."""
    updated = deepcopy(dict(live))
    for namespace in _NAMESPACES:
        if namespace in saved:
            updated[namespace] = deepcopy(saved[namespace])
        else:
            updated.pop(namespace, None)
    if freshness_changed:
        tools = deepcopy(dict(updated.get("tools") or {}))
        processing = deepcopy(dict(tools.get("processing") or {}))
        saved_processing = saved["tools"]["processing"]
        processing["pipeline_setup_requirements"] = deepcopy(saved_processing["pipeline_setup_requirements"])
        saved_provenance = saved_processing.get("full_fft_provenance")
        if isinstance(saved_provenance, Mapping):
            provenance = deepcopy(dict(processing.get("full_fft_provenance") or {}))
            provenance.update({key: deepcopy(saved_provenance[key]) for key in ("status", "stale_reason", "stale_at")})
            processing["full_fft_provenance"] = provenance
        qc = deepcopy(dict(tools.get("frequency_domain_qc") or {}))
        qc.update({key: deepcopy(saved["tools"]["frequency_domain_qc"][key])
                   for key in ("downstream_outputs_stale", "stale_reason", "stale_at")})
        tools.update(processing=processing, frequency_domain_qc=qc)
        updated["tools"] = tools
    return updated


class PipelineSetupDraft:
    """Editable values detached from an opened project's live and saved state."""

    @classmethod
    def from_project(cls, project: Project) -> PipelineSetupDraft:
        draft = cls()
        draft.project_root = Path(project.project_root).resolve()
        draft.manifest_path = manifest_file_path(project.manifest_path)
        draft._disk_baseline = _read_manifest(draft.manifest_path)
        draft._live_baseline = _live_state(project)
        if draft._disk_baseline is not None and _saved_state(draft._disk_baseline) != draft._live_baseline:
            raise PipelineSetupConflict("Processing settings differ from the saved project. Reload the project before guided setup.")
        draft._context_manifest = deepcopy(project.manifest)
        draft._context_manifest["event_map"] = deepcopy(project.event_map)
        draft.preprocessing = deepcopy(draft._live_baseline["preprocessing"])
        draft.frequency_protocol = normalize_frequency_protocol(project.frequency_protocol)
        draft.experimental_qc_settings = normalize_experimental_qc_settings(project.experimental_qc_settings)
        draft._approved_hardware_platform = resolve_hardware(draft.preprocessing).platform
        draft._detector_choice_was_persisted = project._removed_electrode_detection_choice_was_persisted
        return draft

    @property
    def capabilities(self) -> RecordingContract:
        from Main_App.io.acquisition_metadata import resolve_recording_contract

        settings = normalize_preprocessing_settings(self.preprocessing)
        # Preview applicability without claiming that unconfirmed hardware has
        # passed admission. The Recording page and final validation enforce it.
        if "hardware_platform" in settings:
            settings["hardware_confirmed"] = True
        return resolve_recording_contract(settings)

    @property
    def control_policy(self) -> PipelineControlPolicy:
        platform = resolve_hardware(self.preprocessing).platform
        recorded = platform in RECORDED_GEOMETRY_PLATFORMS
        fixed = platform == "unicorn"
        montages = (tuple(item for item in SUPPORTED_ELECTRODE_MONTAGES if item[0] != "unicorn8")
                    if recorded else tuple(item for item in SUPPORTED_ELECTRODE_MONTAGES
                                           if item[0] == ("unicorn8" if fixed else "biosemi64")))
        mappings = {"anatomical_labels"}
        if not recorded:
            mappings.add("unicorn_factory_v1" if fixed else "biosemi64_1020_ab_v1")
        return PipelineControlPolicy(
            not fixed, "fixed" if fixed else "selected_channels" if recorded else "legacy_pair",
            recorded, not recorded, recorded, not fixed, montages,
            tuple(item for item in SUPPORTED_ELECTRODE_MAPPING_PROFILES if item[0] in mappings),
        )

    def update_preprocessing(self, values: Mapping[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(self.preprocessing)
        candidate.update(deepcopy(dict(values)))
        if (resolve_hardware(candidate).platform == "unicorn" and
                candidate.get("electrode_mapping_profile") != self.preprocessing.get("electrode_mapping_profile")):
            profile = candidate.get("acquisition_profile")
            if isinstance(profile, dict):
                profile.pop("source_to_canonical", None)
                profile.pop("label_mapping_evidence", None)
        normalized = normalize_preprocessing_settings(candidate)
        self._require_approved_hardware(normalized)
        self.preprocessing = normalized
        return deepcopy(normalized)

    def update_frequency_protocol(self, value: FrequencyProtocol | Mapping[str, Any]) -> FrequencyProtocol:
        self.frequency_protocol = normalize_frequency_protocol(value)
        return self.frequency_protocol

    def update_experimental_qc_settings(self, value: ExperimentalQcSettings | Mapping[str, Any]) -> ExperimentalQcSettings:
        if isinstance(value, Mapping):
            candidate = self.experimental_qc_settings.to_manifest()
            candidate.update(deepcopy(dict(value)))
            value = candidate
        self.experimental_qc_settings = normalize_experimental_qc_settings(value)
        return self.experimental_qc_settings

    def confirm_hardware(self, platform: str, *, confirmed_change: bool = False) -> None:
        candidate = confirm_hardware_selection(self.preprocessing, platform, confirmed_change=confirmed_change)
        normalized = normalize_preprocessing_settings(candidate)
        qc = self.experimental_qc_settings
        if not hardware_supports_calibrated_qc(normalized):
            qc = brain_products_qc_defaults(qc)
            normalized = confirm_removed_electrode_detection_choice(normalized, "off")
        self.preprocessing = normalized
        self.experimental_qc_settings = qc
        self._approved_hardware_platform = resolve_hardware(normalized).platform

    def confirm_removed_electrode_choice(self, mode: Any) -> None:
        self.preprocessing = confirm_removed_electrode_detection_choice(self.preprocessing, mode)

    def select_method(self, stage_id: str, method_id: str) -> None:
        selection = resolve_pipeline_plan(self.preprocessing).to_config()
        if stage_id not in selection["methods"]:
            raise ValueError(f"Unknown processing step: {stage_id!r}.")
        selection["methods"][stage_id] = method_id
        resolve_pipeline_plan({"processing_pipeline": selection}).validate_capabilities(self.capabilities)
        self.update_preprocessing({"processing_pipeline": selection})

    def method_rows(self, page_id: str) -> tuple[tuple[str, str], ...]:
        page = _PAGES[page_id]
        plan = resolve_pipeline_plan(self.preprocessing)
        steps = {step.id: step for step in PIPELINE_STEPS}
        contract = self.capabilities
        qc = self.experimental_qc_settings
        raw_screening_enabled = qc.raw_signal_screening_enabled or self.preprocessing["auto_detect_removed_electrodes"]
        applicability = {
            "raw_screening": (contract.raw_screening_supported, raw_screening_enabled),
            "condition_raw_screening": (contract.raw_screening_supported, raw_screening_enabled),
            "raw_spectral_screening": (True, qc.raw_spectral_screening.enabled),
            "bad_channel_screening": (contract.kurtosis_screening_supported, qc.kurtosis_screening_enabled),
            "interpolation": (contract.interpolation_allowed, True),
            "condition_repairs": (contract.condition_repair_supported, qc.condition_specific_interpolation_enabled),
            "line_noise_filter": (True, self.preprocessing["line_noise_filter_enabled"]),
            "resample": (contract.resampling_allowed, True),
        }
        rows = []
        for method in plan.methods:
            if method.stage_id not in page.stage_ids:
                continue
            supported, enabled = applicability.get(method.stage_id, (True, True))
            label = _METHOD_LABELS.get(method.method_id, method.label)
            if not supported:
                label += " (unavailable for this recording setup)"
            elif not enabled:
                label += " (off)"
            rows.append((steps[method.stage_id].label, label))
        return tuple(rows)

    def _require_approved_hardware(self, settings: Mapping[str, Any]) -> None:
        if resolve_hardware(settings).platform != self._approved_hardware_platform:
            raise HardwareChangeConfirmationRequired(
                "Changing EEG hardware can break Toolbox functionality or invalidate existing results. "
                "Confirm the hardware change before saving this pipeline."
            )

    def validate_page(self, page_id: str) -> None:
        if page_id not in _PAGES:
            raise ValueError(f"Unknown pipeline setup page: {page_id!r}.")
        if page_id == "review":
            self.validate()
            return
        settings = normalize_preprocessing_settings(self.preprocessing)
        self._require_approved_hardware(settings)
        contract = self.capabilities
        resolve_pipeline_plan(settings).validate_capabilities(contract)
        if page_id == "recording":
            require_hardware_ready(settings)
        elif page_id == "filtering":
            for key in ("low_pass", "high_pass"):
                if not math.isfinite(float(settings[key])):
                    raise ValueError("Filter cutoffs must be finite numbers.")
        elif page_id == "resampling":
            if settings["downsample"] <= 0:
                raise ValueError("Target sampling rate must be a positive whole number.")
        elif page_id == "qc":
            qc = normalize_experimental_qc_settings(self.experimental_qc_settings)
            try:
                require_removed_electrode_detection_choice_ready(settings)
            except RemovedElectrodeDetectionConfirmationRequired as exc:
                raise ValueError(str(exc)) from exc
            if not math.isfinite(float(settings["reject_thresh"])) or float(settings["reject_thresh"]) <= 0:
                raise ValueError("Kurtosis threshold must be a finite positive number.")
            contract.validate_qc({**settings, **qc.to_manifest()})
            requirements = (
                ("raw_signal_screening_enabled", contract.raw_screening_supported),
                ("kurtosis_screening_enabled", contract.kurtosis_screening_supported),
                ("interpolation_burden_review_enabled", contract.condition_repair_supported),
                ("condition_specific_interpolation_enabled", contract.condition_repair_supported),
            )
            for key, supported in requirements:
                if getattr(qc, key) and not supported:
                    raise ValueError(f"{key.replace('_', ' ').capitalize()} is unavailable for this recording setup.")
            if not contract.removed_electrode_screening_supported and settings["auto_detect_removed_electrodes"]:
                raise ValueError("Removed-electrode detection is unavailable for this recording setup.")
        elif page_id == "epochs":
            self._validate_protocol(self._context_manifest, settings)

    def _validate_protocol(self, manifest: Mapping[str, Any], settings: Mapping[str, Any]) -> None:
        protocol = normalize_frequency_protocol(self.frequency_protocol)
        if not protocol.is_ready:
            raise FrequencyProtocolError("Confirm the project protocol and analysis duration before saving the pipeline.")
        validate_protocol_condition_codes(protocol, (manifest.get("event_map") or {}).values())
        if protocol.condition_trigger_maps is not None:
            from Main_App.projects.condition_trigger_maps import validate_project_trigger_maps
            validate_project_trigger_maps(dict(manifest, frequency_protocol=protocol))
        # Validate the new target grid without rewriting imported provenance.
        resolved = protocol.resolve_analysis_window(
            target_sampling_rate_hz=settings["downsample"], source_sampling_rates_hz=(),
        )
        resolved.expected_analyzed_samples(settings["downsample"])
        if protocol.recording_oddball_marker_codes:
            context = project_recording_context_from_manifest(self.project_root, manifest)
            expected = ({row.recording_id.casefold() for row in context.recordings} if context.is_repeated_session
                        else {row.participant_id.casefold() for row in context.participants})
            supplied = {recording_id.casefold() for recording_id, _codes in protocol.recording_oddball_marker_codes}
            if not expected or supplied != expected:
                raise FrequencyProtocolError("Review recording-specific trigger schemas against the project's registered recordings.")

    def validate(self) -> None:
        for page in PIPELINE_SETUP_PAGES[:-1]:
            self.validate_page(page.id)

    def _canonical_preprocessing(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        normalized = normalize_preprocessing_settings(settings)
        return _preprocessing_manifest_payload(
            normalized, repeated_session=bool(self._context_manifest.get("recordings")),
            include_removed_electrode_choice=(self._detector_choice_was_persisted or
                normalized["removed_electrode_detection_choice_status"] == "ready"),
        )

    def _draft_state(self) -> dict[str, Any]:
        return {"preprocessing": self._canonical_preprocessing(self.preprocessing),
                "frequency_protocol": normalize_frequency_protocol(self.frequency_protocol).to_manifest(),
                "experimental_qc": normalize_experimental_qc_settings(self.experimental_qc_settings).to_manifest()}

    def review_changes(self) -> tuple[PipelineSettingChange, ...]:
        baseline = deepcopy(self._live_baseline)
        baseline["preprocessing"] = self._canonical_preprocessing(baseline["preprocessing"])
        before, after = _flatten(baseline), _flatten(self._draft_state())
        changes = []
        for key in sorted(before.keys() | after.keys()):
            old, new = before.get(key), after.get(key)
            if old == new:
                continue
            namespace, _, field = key.partition(".")
            root_field = field.partition(".")[0]
            section = "epochs" if namespace == "frequency_protocol" else "qc"
            if namespace == "preprocessing":
                section = _FIELD_PAGES.get(root_field, "qc")
                if field.startswith("processing_pipeline.methods."):
                    section = _STAGE_PAGES.get(field.rsplit(".", 1)[-1], "review")
            label = _FIELD_LABELS.get(field, field.replace("_", " ").replace(".", " · ").capitalize())
            changes.append(PipelineSettingChange(section, key, label, deepcopy(old), deepcopy(new)))
        return tuple(changes)

    @property
    def requires_reprocessing(self) -> bool:
        return pipeline_settings_identity(self._live_baseline) != pipeline_settings_identity(self._draft_state())

    def save(self, project: Project) -> bool:
        """Atomically save this draft; failures leave the live project untouched."""
        if Path(project.project_root).resolve() != self.project_root or manifest_file_path(project.manifest_path) != self.manifest_path:
            raise ValueError("This processing draft belongs to a different project.")
        self.validate()
        if _live_state(project) != self._live_baseline:
            raise PipelineSetupConflict("Processing settings changed while setup was open. Reopen guided setup before saving.")
        normalized = normalize_preprocessing_settings(self.preprocessing)
        protocol = normalize_frequency_protocol(self.frequency_protocol)
        qc = normalize_experimental_qc_settings(self.experimental_qc_settings)
        candidate_state = self._draft_state()
        baseline_state = deepcopy(self._live_baseline)
        baseline_state["preprocessing"] = self._canonical_preprocessing(baseline_state["preprocessing"])
        geometry = _electrode_geometry_settings(normalized)
        pipeline = _pipeline_settings(normalized)
        with project_manifest_transaction(self.manifest_path) as transaction:
            current = _read_manifest(self.manifest_path)
            if _namespace_snapshot(current) != _namespace_snapshot(self._disk_baseline):
                raise PipelineSetupConflict("Processing settings changed in another window. Reopen guided setup before saving.")
            data = deepcopy(current if current is not None else project.manifest)
            self._validate_protocol(data, normalized)
            for namespace in _NAMESPACES:
                if candidate_state[namespace] == baseline_state[namespace]:
                    continue
                if namespace == "preprocessing":
                    # Patch changed canonical values only. Hidden Stats/ROI and
                    # extension fields retain their exact persisted contents.
                    payload = deepcopy(data.get(namespace, {}))
                    for key in candidate_state[namespace].keys() | baseline_state[namespace].keys():
                        if candidate_state[namespace].get(key) != baseline_state[namespace].get(key):
                            if key in candidate_state[namespace]:
                                payload[key] = deepcopy(candidate_state[namespace][key])
                            else:
                                payload.pop(key, None)
                    data[namespace] = payload
                else:
                    data[namespace] = deepcopy(candidate_state[namespace])
            freshness_changed = apply_pipeline_setup_freshness(data, current if current is not None else project.manifest)
            live_manifest = _live_manifest_after_save(project.manifest, data, freshness_changed=freshness_changed)
            written = transaction.write(data)

        # Mutate runtime state only after the complete atomic publication succeeds.
        project.preprocessing = deepcopy(normalized)
        project.frequency_protocol = protocol
        project.experimental_qc_settings = qc
        project.manifest = live_manifest
        project._electrode_geometry_baseline = geometry
        project._processing_pipeline_baseline = pipeline
        project._frequency_protocol_was_persisted = "frequency_protocol" in data
        project._removed_electrode_detection_choice_was_persisted = (
            self._detector_choice_was_persisted or normalized["removed_electrode_detection_choice_status"] == "ready")
        self._detector_choice_was_persisted = project._removed_electrode_detection_choice_was_persisted
        self._disk_baseline = deepcopy(data)
        self._live_baseline = _live_state(project)
        self._context_manifest = deepcopy(data)
        return written
