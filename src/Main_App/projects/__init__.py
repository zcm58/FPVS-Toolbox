"""Canonical Main App project import surface."""

from __future__ import annotations

import importlib
from typing import Any

_PROJECT_NAMES = {
    "Project",
    "DEFAULTS",
    "EXCEL_SUBFOLDER_NAME",
    "PROJECT_SCHEMA_VERSION",
    "REPEATED_SESSION_PROJECT_SCHEMA_VERSION",
    "SNR_SUBFOLDER_NAME",
    "STATS_SUBFOLDER_NAME",
    "_LEGACY_BANDPASS_WARNED",
}
_RECORDING_NAMES = {
    "ProjectRecordingContext",
    "RecordingConfigurationError",
    "RecordingInfo",
    "RecordingSourceInfo",
    "SessionInfo",
    "load_project_recording_context",
    "normalize_project_recording_sources",
    "normalize_project_recordings",
    "normalize_project_sessions",
    "project_recording_context",
}
_RECORDING_PREFLIGHT_NAMES = {
    "RecordingPreflightCancelled",
    "RecordingPreflightIssue",
    "RecordingPreflightReport",
    "RecordingPreflightRow",
    "derive_filename_token_rules",
    "preflight_repeated_recording_sources",
}
_RAW_IDENTITY_NAMES = {"infer_raw_participant_id"}
_SESSION_COMPATIBILITY_NAMES = {"repeated_session_tool_block_reason"}
_PROJECT_CONTEXT_NAMES = {"resolve_active_project_root"}
_EXPERIMENTAL_QC_SETTINGS_NAMES = {
    "EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION",
    "LEGACY_EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION",
    "RAW_SPECTRAL_SCREENING_BRIEF_TEXT",
    "RAW_SPECTRAL_SCREENING_POLICY_VERSION",
    "SUMMED_BCA_SCREENING_BRIEF_TEXT",
    "SUMMED_BCA_SCREENING_POLICY_VERSION",
    "ExperimentalQcSettings",
    "ExperimentalQcSettingsError",
    "RawSpectralScreeningSettings",
    "SummedBcaScreeningSettings",
    "normalize_experimental_qc_settings",
    "normalize_raw_spectral_screening_settings",
    "normalize_summed_bca_screening_settings",
}
_FREQUENCY_PROTOCOL_NAMES = {
    "DEFAULT_ODDBALL_EVERY_N",
    "DEFAULT_ODDBALL_MARKER_CODE",
    "DEFAULT_PRESENTATION_RATE_HZ",
    "DIRECT_HZ_DISPLAY_DECIMAL_PLACES",
    "DIRECT_HZ_DISPLAY_TOLERANCE_HZ",
    "EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT",
    "EXPECTED_CYCLES_SOURCE_MANUAL",
    "FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED",
    "FREQUENCY_PROTOCOL_STATUS_INCOMPLETE",
    "FREQUENCY_PROTOCOL_STATUS_READY",
    "FREQUENCY_PROTOCOL_VERSION",
    "LEGACY_FREQUENCY_PROTOCOL_VERSION",
    "FrequencyProtocol",
    "FrequencyProtocolError",
    "HarmonicTarget",
    "ODDBALL_INPUT_MODE_DIRECT_HZ",
    "ODDBALL_INPUT_MODE_RECURRENCE",
    "ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT",
    "ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55",
    "ODDBALL_MARKER_SOURCE_LEGACY_EVIDENCE",
    "ODDBALL_MARKER_SOURCE_MANUAL",
    "enumerate_exact_harmonics",
    "enumerate_protocol_harmonics",
    "new_manual_frequency_protocol",
    "normalize_frequency_protocol",
    "validate_protocol_condition_codes",
}
_GROUPING_NAMES = {
    "GroupConfigurationError",
    "GroupInfo",
    "ParticipantInfo",
    "ProjectGroupContext",
    "load_project_group_context",
    "make_group_id",
    "normalize_project_groups",
    "normalize_project_participants",
    "project_group_context",
    "resolve_group_output_directory",
    "resolve_output_directory",
    "validate_group_folder_name",
}
_DATASET_INDEX_NAMES = {
    "DatasetDiagnostic",
    "ProjectDatasetIndex",
    "WorkbookRecord",
    "group_labels_from_manifest",
    "infer_workbook_participant_id",
    "is_multi_group_manifest",
    "load_project_dataset_index",
    "participant_group_label_map_from_manifest",
}
_DATASET_PATH_NAMES = {
    "DatasetIndexError",
    "find_project_manifest_for_dataset_path",
    "load_project_manifest_for_dataset_path",
    "resolve_project_excel_root",
}
_PREPROCESSING_NAMES = {
    "ELECTRODE_MAPPING_PROFILE_ANATOMICAL",
    "ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1",
    "ELECTRODE_MONTAGE_BIOSEMI64",
    "HARMONIC_SELECTION_PROFILE_VERSION",
    "FIXED_HARMONIC_SELECTION_PROFILE",
    "LEGACY_HARMONIC_SELECTION_PROFILE",
    "MANUAL_REMOVED_ELECTRODES_ENABLED_KEY",
    "NEW_PROJECT_HARMONIC_SELECTION_PROFILE",
    "SIGNIFICANT_ONLY_HARMONIC_SELECTION_PROFILE",
    "PREPROCESSING_CANONICAL_KEYS",
    "PREPROCESSING_DEFAULTS",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY",
    "REPEATED_SESSION_PREPROCESSING_KEYS",
    "RemovedElectrodeDetectionConfirmationRequired",
    "SUPPORTED_ELECTRODE_MAPPING_PROFILES",
    "SUPPORTED_ELECTRODE_MONTAGES",
    "is_recording_condition_excluded",
    "confirm_removed_electrode_detection_choice",
    "is_participant_condition_excluded",
    "normalize_manual_excluded_participant_conditions",
    "normalize_manual_excluded_participants",
    "normalize_manual_excluded_recording_conditions",
    "normalize_manual_excluded_recordings",
    "normalize_electrode_mapping_profile",
    "normalize_electrode_montage",
    "normalize_preprocessing_settings",
    "new_project_preprocessing_settings",
    "removed_electrode_detection_choice_requires_confirmation",
    "removed_electrode_detection_choice_was_saved",
    "require_removed_electrode_detection_choice_ready",
}

__all__ = sorted(
    _DATASET_INDEX_NAMES
    | _DATASET_PATH_NAMES
    | _EXPERIMENTAL_QC_SETTINGS_NAMES
    | _FREQUENCY_PROTOCOL_NAMES
    | _GROUPING_NAMES
    | _PROJECT_NAMES
    | _PREPROCESSING_NAMES
    | _PROJECT_CONTEXT_NAMES
    | _RAW_IDENTITY_NAMES
    | _RECORDING_NAMES
    | _RECORDING_PREFLIGHT_NAMES
    | _SESSION_COMPATIBILITY_NAMES
)


def __getattr__(name: str) -> Any:
    if name in _DATASET_INDEX_NAMES:
        dataset_index = importlib.import_module("Main_App.projects.dataset_index")

        return getattr(dataset_index, name)
    if name in _DATASET_PATH_NAMES:
        dataset_paths = importlib.import_module("Main_App.projects.dataset_paths")

        return getattr(dataset_paths, name)
    if name in _GROUPING_NAMES:
        grouping = importlib.import_module("Main_App.projects.grouping")

        return getattr(grouping, name)
    if name in _FREQUENCY_PROTOCOL_NAMES:
        frequency_protocol = importlib.import_module(
            "Main_App.projects.frequency_protocol"
        )

        return getattr(frequency_protocol, name)
    if name in _EXPERIMENTAL_QC_SETTINGS_NAMES:
        experimental_qc_settings = importlib.import_module(
            "Main_App.projects.experimental_qc_settings"
        )

        return getattr(experimental_qc_settings, name)
    if name in _PROJECT_NAMES:
        project = importlib.import_module("Main_App.projects.project")

        return getattr(project, name)
    if name in _PROJECT_CONTEXT_NAMES:
        project_context = importlib.import_module("Main_App.projects.project_context")

        return getattr(project_context, name)
    if name in _RECORDING_NAMES:
        recordings = importlib.import_module("Main_App.projects.recordings")

        return getattr(recordings, name)
    if name in _RECORDING_PREFLIGHT_NAMES:
        recording_preflight = importlib.import_module(
            "Main_App.projects.recording_preflight"
        )

        return getattr(recording_preflight, name)
    if name in _RAW_IDENTITY_NAMES:
        raw_identity = importlib.import_module("Main_App.projects.raw_identity")

        return getattr(raw_identity, name)
    if name in _SESSION_COMPATIBILITY_NAMES:
        session_compatibility = importlib.import_module(
            "Main_App.projects.session_compatibility"
        )

        return getattr(session_compatibility, name)
    if name in _PREPROCESSING_NAMES:
        preprocessing_settings = importlib.import_module("Main_App.projects.preprocessing_settings")

        return getattr(preprocessing_settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
