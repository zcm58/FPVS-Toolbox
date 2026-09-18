"""Cache retention/path tests use only tmp_path, including real Windows byte locks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from threading import Event

import pytest

from Main_App.updates.cache import (
    cleanup_update_cache,
    default_update_cache_dir,
    receipt_name,
    recognized_cache_entry,
)
from Main_App.updates.cache_io import LOCK_FILENAME, locked_cache
from Main_App.updates.models import InstallerAsset, UpdateCacheBusy, UpdateCancelled, UpdateError


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows handle bindings")
def test_guarded_reads_reuse_api_binding_but_read_fresh_files(tmp_path, monkeypatch):
    import ctypes

    from Main_App.updates import cache_io

    original = ctypes.WinDLL
    loads = []

    def counted_load(name, **kwargs):
        loads.append(name)
        return original(name, **kwargs)

    cache_io._windows_file_api.cache_clear()
    monkeypatch.setattr(ctypes, "WinDLL", counted_load)
    try:
        folder = tmp_path / "nested"
        folder.mkdir()
        for index in range(8):
            path = folder / f"file-{index}.txt"
            path.write_bytes(b"first")
            with cache_io.guarded_read_path(path) as source:
                assert source.read() == b"first"
            path.write_bytes(b"updated")
            with cache_io.guarded_read_path(path) as source:
                assert source.read() == b"updated"
        # The frozen loader probes the filesystem on each WinDLL construction.
        # A baseline contains thousands of files with multiple ancestor handles.
        assert loads == ["kernel32"]
    finally:
        cache_io._windows_file_api.cache_clear()


def _cached(cache: Path, version: str, payload: bytes = b"installer") -> Path:
    name = f"FPVSToolbox-{version}-setup.exe"
    asset = InstallerAsset(
        name,
        f"https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v{version}/{name}",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        version,
        123,
    )
    target = cache / name
    target.write_bytes(payload)
    (cache / receipt_name(name)).write_text(
        json.dumps({"schema": 1, **asdict(asset)}), encoding="utf-8"
    )
    return target


@pytest.mark.parametrize(
    "name",
    [
        "FPVSToolbox-1.3.0-setup.exe",
        "FPVSToolbox-1.3.0-beta.2-setup.exe",
        "FPVSToolbox-1.3.0rc1-setup.exe",
        "FPVSToolbox-1.3.0.post2-setup.exe",
        "FPVSToolbox-1.3.0-setup.exe.part",
        "FPVSToolbox-1.3.0-setup.exe." + "f" * 32 + ".part",
        "FPVSToolbox-1.3.0-setup.exe.verified.json",
        "FPVSToolbox-1.3.0-setup.exe.verified." + "f" * 32 + ".tmp",
    ],
)
def test_recognizes_only_updater_filenames(name: str) -> None:
    assert recognized_cache_entry(name) is not None


@pytest.mark.parametrize(
    "name",
    [
        "../FPVSToolbox-1.3.0-setup.exe",
        r"folder\FPVSToolbox-1.3.0-setup.exe",
        "FPVSToolbox-1.3.0-setup.exe:stream",
        "FPVSToolbox-other-setup.exe",
        "FPVSToolbox-1.3.0-setup.exe.user.part",
        "FPVSToolbox-1.3.0-setup.exe.verified.not-a-uuid.tmp",
        "FPVSToolbox-1.3.0-setup.exe ",
        "unrelated.exe",
        ".fpvs-update.lock",
        "notes.part",
        "settings.json",
    ],
)
def test_leaves_unrecognized_names_out_of_policy(name: str) -> None:
    assert recognized_cache_entry(name) is None


def test_retains_only_highest_valid_newer_version_and_prunes_completed_old(tmp_path: Path) -> None:
    old = _cached(tmp_path, "1.1.0")
    running = _cached(tmp_path, "1.3.0")
    lower = _cached(tmp_path, "2.0.0")
    best = _cached(tmp_path, "2.1.0")
    corrupt = _cached(tmp_path, "2.2.0")
    corrupt.write_bytes(b"corrupted")

    result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)

    assert result.kept_installer == best
    assert not result.warnings
    assert not result.busy
    assert best.read_bytes() == b"installer"
    for removed in (old, running, lower, corrupt):
        assert not removed.exists()
        assert not (tmp_path / receipt_name(removed.name)).exists()
    assert set(tmp_path.iterdir()) == {
        best,
        tmp_path / receipt_name(best.name),
        tmp_path / LOCK_FILENAME,
    }
    assert cleanup_update_cache("2.1.0", cache_dir=tmp_path).kept_installer is None
    assert set(tmp_path.iterdir()) == {tmp_path / LOCK_FILENAME}


def test_all_unlocked_partials_are_abandoned_regardless_of_age(tmp_path: Path) -> None:
    names = [
        "FPVSToolbox-2.0.0-setup.exe.part",
        f"FPVSToolbox-2.0.0-setup.exe.{'a' * 32}.part",
        f"FPVSToolbox-2.0.0-setup.exe.{'b' * 32}.part",
        f"FPVSToolbox-2.0.0-setup.exe.verified.{'c' * 32}.tmp",
    ]
    for index, name in enumerate(names):
        target = tmp_path / name
        target.write_bytes(b"abandoned")
        timestamp = time.time() + (index - 1) * 100_000
        os.utime(target, (timestamp, timestamp))

    result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)

    assert {path.name for path in result.removed_files} == set(names)
    assert set(tmp_path.iterdir()) == {tmp_path / LOCK_FILENAME}


def test_unverified_payload_and_orphan_receipt_are_not_retained(tmp_path: Path) -> None:
    target = _cached(tmp_path, "2.0.0")
    (tmp_path / receipt_name(target.name)).unlink()
    orphan = tmp_path / "FPVSToolbox-3.0.0-setup.exe.verified.json"
    orphan.write_text("{}", encoding="utf-8")

    result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)

    assert result.kept_installer is None
    assert set(tmp_path.iterdir()) == {tmp_path / LOCK_FILENAME}


@pytest.mark.parametrize(
    "change",
    [
        {"schema": 2},
        {"schema": True},
        {"name": "../outside.exe"},
        {"download_url": "https://example.com/untrusted.exe"},
        {"sha256": None},
        {"sha256": "sha512:" + "a" * 64},
        {"version": "99.0.0"},
        {"size_bytes": True},
        {"asset_id": True},
    ],
)
def test_malformed_receipts_cannot_keep_a_payload(
    tmp_path: Path, change: dict[str, object]
) -> None:
    target = _cached(tmp_path, "2.0.0")
    receipt = tmp_path / receipt_name(target.name)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    receipt.write_text(json.dumps({**data, **change}), encoding="utf-8")

    assert cleanup_update_cache("1.3.0", cache_dir=tmp_path).kept_installer is None
    assert not target.exists()


def test_oversize_receipt_is_bounded(tmp_path: Path) -> None:
    target = _cached(tmp_path, "2.0.0")
    (tmp_path / receipt_name(target.name)).write_bytes(b" " * (16 * 1024 + 1))
    assert cleanup_update_cache("1.3.0", cache_dir=tmp_path).kept_installer is None
    assert not target.exists()


def test_studio_legacy_alias_cannot_authorize_toolbox_receipt(tmp_path: Path) -> None:
    target = _cached(tmp_path, "0.9.10")
    receipt = tmp_path / receipt_name(target.name)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["version"] = "0.9.9.10"
    data["download_url"] = data["download_url"].replace("/v0.9.10/", "/v0.9.9.10/")
    receipt.write_text(json.dumps(data), encoding="utf-8")

    assert cleanup_update_cache("0.9.9", cache_dir=tmp_path).kept_installer is None
    assert cleanup_update_cache("0.9.9.10", cache_dir=tmp_path).kept_installer is None
    assert not target.exists()


def test_cleanup_preserves_unrecognized_files_and_all_directories(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("user data", encoding="utf-8")
    arbitrary = tmp_path / "someone-elses-installer.exe"
    arbitrary.write_bytes(b"keep")
    for name in ("projects", "runs", "logs", "FPVSToolbox-2.0.0-setup.exe"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "sentinel.txt").write_text("keep", encoding="utf-8")

    result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)

    assert result.warnings  # A recognized basename that is a directory is unsafe, not removable.
    assert settings.read_text(encoding="utf-8") == "user data"
    assert arbitrary.read_bytes() == b"keep"
    assert len(list(tmp_path.glob("*/sentinel.txt"))) == 4


def test_default_cache_is_independent_of_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_update_cache_dir() == tmp_path / "FPVS Toolbox" / "updates"
    assert cleanup_update_cache("1.3.0").warnings == ()
    assert not (tmp_path / "FPVS Toolbox").exists()  # No empty cache created on normal startup.


def test_missing_local_app_data_uses_only_explicit_system_temp_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr("Main_App.updates.cache.tempfile.gettempdir", lambda: str(tmp_path))
    assert default_update_cache_dir() == tmp_path / "FPVS Toolbox" / "updates"


@pytest.mark.parametrize("path", [Path("relative/updates"), Path("C:"), Path("..")])
def test_cleanup_rejects_nonabsolute_paths_without_mutation(path: Path) -> None:
    result = cleanup_update_cache("1.3.0", cache_dir=path)
    assert result.warnings
    assert not result.removed_files


def test_cleanup_rejects_drive_root_and_traversal(tmp_path: Path) -> None:
    for path in (Path(tmp_path.anchor), tmp_path / ".." / "escape"):
        assert cleanup_update_cache("1.3.0", cache_dir=path).warnings


def test_invalid_version_cleanup_is_nonfatal(tmp_path: Path) -> None:
    assert cleanup_update_cache("not-a-version", cache_dir=tmp_path).warnings
    assert list(tmp_path.iterdir()) == []


def test_cleanup_permission_error_is_logged_and_other_files_can_be_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = _cached(tmp_path, "1.0.0")
    removable = _cached(tmp_path, "1.1.0")
    original = Path.unlink

    def unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == blocked:
            raise PermissionError("simulated in-use executable")
        original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)
    assert result.warnings
    assert blocked.exists()
    assert not removable.exists()
    assert "update_cache_cleanup_failed" in caplog.text


def test_cancellation_during_hash_releases_lock_and_preserves_valid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _cached(tmp_path, "2.0.0")
    cancel = Event()
    original = hashlib.sha256

    class CancelHash:
        def __init__(self) -> None:
            self.digest = original()

        def update(self, chunk: bytes) -> None:
            self.digest.update(chunk)
            cancel.set()

        def hexdigest(self) -> str:
            return self.digest.hexdigest()

    monkeypatch.setattr("Main_App.updates.cache.hashlib.sha256", CancelHash)
    with pytest.raises(UpdateCancelled):
        cleanup_update_cache("1.3.0", cache_dir=tmp_path, cancel_event=cancel)
    assert target.exists()
    with locked_cache(tmp_path):
        pass


def test_an_active_lock_prevents_cleanup_and_second_writer(tmp_path: Path) -> None:
    partial = tmp_path / "FPVSToolbox-2.0.0-setup.exe.part"
    partial.write_bytes(b"active writer")
    with locked_cache(tmp_path):
        result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)
        assert result.busy
        assert partial.read_bytes() == b"active writer"
        with pytest.raises(UpdateCacheBusy):
            with locked_cache(tmp_path):
                pytest.fail("A second cache writer acquired the lock")
    assert not cleanup_update_cache("1.3.0", cache_dir=tmp_path).busy
    assert not partial.exists()


def test_os_lock_serializes_processes_and_is_released_after_process_termination(
    tmp_path: Path,
) -> None:
    code = (
        "import sys; from pathlib import Path; "
        "from Main_App.updates.cache_io import locked_cache; "
        "scope=locked_cache(Path(sys.argv[1])); cache=scope.__enter__(); "
        "print('locked', flush=True); sys.stdin.read(1); scope.__exit__(None,None,None)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == b"locked"
        assert cleanup_update_cache("1.3.0", cache_dir=tmp_path).busy
        process.terminate()
        process.communicate(timeout=5)
        assert not cleanup_update_cache("1.3.0", cache_dir=tmp_path).busy
        assert (tmp_path / LOCK_FILENAME).is_file()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("target_name", [LOCK_FILENAME, "FPVSToolbox-2.0.0-setup.exe"])
def test_hardlinked_cache_files_are_never_opened_or_deleted(
    tmp_path: Path, target_name: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "user-file"
    original.write_bytes(b"keep")
    cache = tmp_path / "cache"
    cache.mkdir()
    os.link(original, cache / target_name)

    result = cleanup_update_cache("1.3.0", cache_dir=cache)
    assert result.warnings
    assert (cache / target_name).exists()
    assert original.read_bytes() == b"keep"


@pytest.mark.parametrize("linked", ["root", "ancestor", "payload", "lock"])
def test_symlinked_cache_paths_are_refused_without_following(tmp_path: Path, linked: str) -> None:
    real = tmp_path / "real"
    real.mkdir()
    sentinel = real / "FPVSToolbox-2.0.0-setup.exe"
    sentinel.write_bytes(b"outside")
    cache = tmp_path / "cache"
    try:
        if linked in {"root", "ancestor"}:
            cache.symlink_to(real, target_is_directory=True)
            if linked == "ancestor":
                cache = cache / "child"
                (real / "child").mkdir()
        else:
            cache.mkdir()
            name = sentinel.name if linked == "payload" else LOCK_FILENAME
            (cache / name).symlink_to(sentinel)
    except OSError as error:
        pytest.skip(f"This Windows account cannot create a test symlink: {error}")

    result = cleanup_update_cache("1.3.0", cache_dir=cache)
    assert result.warnings
    assert sentinel.read_bytes() == b"outside"


def test_windows_reparse_attribute_is_refused_even_without_symlink_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from Main_App.updates import cache_io

    target = _cached(tmp_path, "2.0.0")
    actual = cache_io._is_reparse
    identity = target.lstat().st_ino
    monkeypatch.setattr(
        cache_io, "_is_reparse", lambda info: info.st_ino == identity or actual(info)
    )
    result = cleanup_update_cache("1.3.0", cache_dir=tmp_path)
    assert result.warnings
    assert target.read_bytes() == b"installer"


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows junction semantics")
@pytest.mark.parametrize("linked", ["root", "ancestor", "payload", "lock"])
def test_native_windows_junctions_are_refused_without_symlink_privilege(
    tmp_path: Path, linked: str
) -> None:
    import _winapi

    real = tmp_path / "real"
    real.mkdir()
    sentinel = real / "user-data.txt"
    sentinel.write_text("outside", encoding="utf-8")
    cache = tmp_path / "cache"
    if linked in {"root", "ancestor"}:
        _winapi.CreateJunction(str(real), str(cache))
        if linked == "ancestor":
            (real / "child").mkdir()
            cache = cache / "child"
    else:
        cache.mkdir()
        name = "FPVSToolbox-2.0.0-setup.exe" if linked == "payload" else LOCK_FILENAME
        _winapi.CreateJunction(str(real), str(cache / name))

    result = cleanup_update_cache("1.3.0", cache_dir=cache)
    assert result.warnings
    assert sentinel.read_text(encoding="utf-8") == "outside"


@pytest.mark.skipif(os.name != "nt", reason="Windows filename and sharing semantics")
@pytest.mark.parametrize("component", ["CON", "NUL.txt", "bad:name", "bad?", "trailing."])
def test_invalid_windows_component_does_not_create_any_prefix(
    tmp_path: Path, component: str
) -> None:
    prefix = tmp_path / "must-not-be-created"
    with pytest.raises(UpdateError):
        with locked_cache(prefix / component / "updates"):
            pytest.fail("An unsafe directory was accepted")
    assert not prefix.exists()
