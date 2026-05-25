from __future__ import annotations

from Tools.Plot_Generator.manifest_utils import (
    extract_group_names,
    normalize_participants_map,
)


def test_manifest_utils_resolve_v2_group_ids_to_labels() -> None:
    manifest = {
        "groups": {
            "control": {
                "label": "Control Group",
                "folder_name": "Control",
            },
            "clinical": {
                "label": "Clinical Group",
                "folder_name": "Clinical",
            },
        },
        "participants": {
            "P01": {"group_id": "control"},
            "P02": {"group_id": "clinical"},
        },
    }

    assert extract_group_names(manifest) == ["Clinical Group", "Control Group"]
    assert normalize_participants_map(manifest) == {
        "P01": "Control Group",
        "P02": "Clinical Group",
    }


def test_manifest_utils_keep_legacy_group_names() -> None:
    manifest = {
        "groups": {"GroupA": {}, "GroupB": {}},
        "participants": {
            "P01": {"group": "GroupA"},
            "P02": {"group": "GroupB"},
        },
    }

    assert extract_group_names(manifest) == ["GroupA", "GroupB"]
    assert normalize_participants_map(manifest) == {
        "P01": "GroupA",
        "P02": "GroupB",
    }
