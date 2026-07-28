"""Canonical Main App project import surface."""

from __future__ import annotations

import importlib
from typing import Any

_PROJECT_NAMES = {
    "Project",
    "DEFAULTS",
    "EXCEL_SUBFOLDER_NAME",
    "PROJECT_SCHEMA_VERSION",
    "SNR_SUBFOLDER_NAME",
    "STATS_SUBFOLDER_NAME",
    "_LEGACY_BANDPASS_WARNED",
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
    "PREPROCESSING_CANONICAL_KEYS",
    "PREPROCESSING_DEFAULTS",
    "normalize_preprocessing_settings",
}

__all__ = sorted(
    _DATASET_INDEX_NAMES
    | _DATASET_PATH_NAMES
    | _GROUPING_NAMES
    | _PROJECT_NAMES
    | _PREPROCESSING_NAMES
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
    if name in _PROJECT_NAMES:
        project = importlib.import_module("Main_App.projects.project")

        return getattr(project, name)
    if name in _PREPROCESSING_NAMES:
        preprocessing_settings = importlib.import_module("Main_App.projects.preprocessing_settings")

        return getattr(preprocessing_settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
