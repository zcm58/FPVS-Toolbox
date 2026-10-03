"""Private memory-map directories and conservative dead-process cleanup."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.Shared import load_utils
from Main_App.io import memmap_paths
from Main_App.workers import process_runner


def test_memmaps_do_not_reuse_a_preplanted_pid_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(memmap_paths.tempfile, "gettempdir", lambda: str(tmp_path))
    predictable = tmp_path / "fpvs_memmap" / f"pid_{load_utils.os.getpid()}"
    predictable.mkdir(parents=True)
    sentinel = predictable / "participant_raw.dat"
    sentinel.write_bytes(b"outside content")

    private = load_utils._memmap_dir_for_pid()

    assert private != predictable
    assert private.parent == predictable.parent
    assert private == load_utils._memmap_dir_for_pid()
    assert process_runner._memmap_path_for_file(Path("participant.bdf")).parent == private
    assert sentinel.read_bytes() == b"outside content"


def test_scavenging_does_not_traverse_a_redirected_memmap_root(tmp_path, monkeypatch):
    monkeypatch.setattr(memmap_paths.tempfile, "gettempdir", lambda: str(tmp_path))
    base = tmp_path / "fpvs_memmap"
    dead = base / "pid_987654321"
    dead.mkdir(parents=True)
    sentinel = dead / "outside.txt"
    sentinel.write_bytes(b"outside content")
    original = Path.lstat

    def reparse_info(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == base:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_info)
    process_runner._scavenge_stale_memmaps()
    assert sentinel.read_bytes() == b"outside content"
    with pytest.raises(OSError, match="linked|directory"):
        load_utils._memmap_dir_for_pid()


def test_replaced_private_directory_is_neither_reused_nor_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(memmap_paths.tempfile, "gettempdir", lambda: str(tmp_path))
    private = memmap_paths.process_memmap_directory()
    info = private.lstat()
    identity = (info.st_dev, info.st_ino)
    private.rename(private.with_name("original"))
    private.mkdir()
    sentinel = private / "outside.txt"
    sentinel.write_bytes(b"outside content")

    with pytest.raises(OSError, match="changed"):
        memmap_paths.process_memmap_directory()
    memmap_paths._cleanup_private_directory(private, identity)

    assert sentinel.read_bytes() == b"outside content"


def test_scavenging_preserves_live_maps_and_removes_old_and_private_dead_maps(tmp_path, monkeypatch):
    import psutil
    monkeypatch.setattr(memmap_paths.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 123)
    root = tmp_path / "fpvs_memmap"
    directories = [root / name for name in ("pid_123", "pid_123-abc12345", "pid_456", "pid_456-abc12345")]
    for directory in directories:
        directory.mkdir(parents=True)
        (directory / "participant_raw.dat").write_bytes(b"map")

    process_runner._scavenge_stale_memmaps()

    assert all((directory / "participant_raw.dat").read_bytes() == b"map" for directory in directories[:2])
    assert all(not directory.exists() for directory in directories[2:])
