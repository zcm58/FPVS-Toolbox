from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from Main_App.Shared import settings_manager as module
from Main_App.Shared.settings_manager import DEFAULTS, SettingsManager


def _seed(path: Path) -> SettingsManager:
    manager = SettingsManager(str(path))
    manager.set_roi_pairs([("Central", ["CZ"]), ("Test ROI", ["OZ"])])
    manager.save()
    return manager


def test_unrelated_stale_save_cannot_restore_deleted_roi(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    editor = _seed(path)
    stale = SettingsManager(str(path))
    editor.set_roi_pairs([("Central", ["CZ"])])
    editor.save()

    stale.set("updates", "last_checked_utc", "2026-09-07T13:40:36Z")
    stale.save()
    stale.set("paths", "data_folder", "new-data-folder")
    stale.save()

    saved = SettingsManager(str(path))
    assert saved.get_roi_pairs() == [("Central", ["CZ"])]
    assert stale.get_roi_pairs() == saved.get_roi_pairs()
    assert saved.get("updates", "last_checked_utc") == "2026-09-07T13:40:36Z"
    assert saved.get("paths", "data_folder") == "new-data-folder"


def test_rollback_config_assignment_preserves_unrelated_newer_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    editor = _seed(path)
    rollback = copy.deepcopy(editor.config)
    editor.set_roi_pairs([("Central", ["CZ"])])
    editor.save()
    other = SettingsManager(str(path))
    other.set("updates", "last_checked_utc", "new check")
    other.save()

    editor.config = rollback
    editor.save()

    saved = SettingsManager(str(path))
    assert saved.get_roi_pairs() == [("Central", ["CZ"]), ("Test ROI", ["OZ"])]
    assert saved.get("updates", "last_checked_utc") == "new check"


def test_concurrent_managers_merge_distinct_local_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    _seed(path)
    managers = [SettingsManager(str(path)) for _ in range(8)]

    def save_one(index: int) -> None:
        managers[index].set("concurrent", f"value_{index}", str(index))
        managers[index].save()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save_one, range(8)))

    saved = SettingsManager(str(path))
    assert dict(saved.config.items("concurrent")) == {f"value_{index}": str(index) for index in range(8)}


def test_local_option_and_section_removal_survive_save_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    manager = _seed(path)
    manager.set("extra", "first", "delete")
    manager.set("extra", "second", "keep")
    manager.set("retired", "value", "delete section")
    manager.save()
    stale = SettingsManager(str(path))
    manager.config.remove_option("extra", "first")
    manager.config.remove_section("retired")
    manager.save()

    stale.load()

    assert stale.get("extra", "first", "missing") == "missing"
    assert stale.get("extra", "second") == "keep"
    assert not stale.config.has_section("retired")


@pytest.mark.parametrize("operation", ["reset", "ini", "json"])
def test_reset_and_import_replace_stale_configuration(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "settings.ini"
    manager = _seed(path)
    manager.set("obsolete", "value", "remove")
    manager.save()
    other = SettingsManager(str(path))
    other.set("newer", "value", "also replaced by explicit reset/import")
    other.save()

    if operation == "reset":
        manager.reset()
    else:
        imported = tmp_path / f"import.{operation}"
        imported.write_text(
            "[analysis]\nalpha=0.01\n" if operation == "ini"
            else json.dumps({"analysis": {"alpha": "0.01"}}),
        )
        manager.load_from(str(imported))

    saved = SettingsManager(str(path))
    assert not saved.config.has_section("obsolete")
    assert not saved.config.has_section("newer")
    assert saved.get("rois", "names") == DEFAULTS["rois"]["names"]
    assert saved.get("analysis", "alpha") == ("0.05" if operation == "reset" else "0.01")


def test_failed_atomic_save_keeps_original_and_retryable_local_changes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "settings.ini"
    manager = _seed(path)
    original = path.read_bytes()
    manager.set_roi_pairs([("Central", ["CZ"])])
    replace = module.os.replace

    def deny_replace(*_args) -> None:
        raise PermissionError("blocked replacement")

    monkeypatch.setattr(module.os, "replace", deny_replace)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    with pytest.raises(PermissionError, match="blocked replacement"):
        manager.save()
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))

    monkeypatch.setattr(module.os, "replace", replace)
    manager.save()
    assert SettingsManager(str(path)).get_roi_pairs() == [("Central", ["CZ"])]


def test_atomic_save_retries_transient_permission_error(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "settings.ini"
    manager = _seed(path)
    manager.set_roi_pairs([("Central", ["CZ"])])
    replace = module.os.replace
    attempts = []
    delays = []

    def transient_lock(source, target) -> None:
        attempts.append((source, target))
        if len(attempts) < 3:
            raise PermissionError("scanner lock")
        replace(source, target)

    monkeypatch.setattr(module.os, "replace", transient_lock)
    monkeypatch.setattr(module.time, "sleep", delays.append)
    manager.save()

    assert len(attempts) == 3
    assert delays == [0.01, 0.02]
    assert SettingsManager(str(path)).get_roi_pairs() == [("Central", ["CZ"])]


def test_legacy_roi_migration_persists_against_loaded_baseline(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    path.write_text(
        f"[rois]\nnames={module._LEGACY_DEFAULT_ROI_NAMES}\n"
        f"electrodes={module._LEGACY_DEFAULT_ROI_ELECTRODES}\n"
        "[unrelated]\nvalue=preserved\n",
    )

    manager = SettingsManager(str(path))

    assert manager.get("rois", "names") == DEFAULTS["rois"]["names"]
    assert SettingsManager(str(path)).get("rois", "names") == DEFAULTS["rois"]["names"]
    assert manager.get("unrelated", "value") == "preserved"


def test_default_values_and_explicit_overrides_are_not_interpolated_or_duplicated(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    path.write_text("[DEFAULT]\nbase=one\n[custom]\nbase=explicit\nvalue=%(base)s/path\n")
    first = SettingsManager(str(path))
    second = SettingsManager(str(path))
    first.config["DEFAULT"]["base"] = "two"
    first.save()
    second.set("debug", "enabled", "True")
    second.save()

    saved = SettingsManager(str(path))
    assert saved.config.defaults()["base"] == "two"
    assert saved.get("custom", "value") == "explicit/path"
    assert saved.config.get("custom", "value", raw=True) == "%(base)s/path"
    assert "base" not in saved.config._sections["debug"]
