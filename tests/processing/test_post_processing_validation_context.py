from __future__ import annotations

import os
from pathlib import Path

import pytest

from Main_App.processing.post_processing_context import (
    CACHE_MISS,
    cached_validation,
    capture_validation_files,
    post_processing_validation_scope,
    remember_validation,
    validation_scope_active,
)


def test_validation_scope_reuses_nested_reads_without_leaking_mutations(tmp_path: Path):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    with post_processing_validation_scope():
        remember_validation(
            "example", "key", {"rows": [1, 2]},
            files=capture_validation_files([source]),
        )
        with post_processing_validation_scope():
            value = cached_validation("example", "key")
            value["rows"].append(3)
        assert cached_validation("example", "key") == {"rows": [1, 2]}
    assert not validation_scope_active()
    with post_processing_validation_scope():
        assert cached_validation("example", "key") is CACHE_MISS


def test_validation_scope_is_released_after_exception():
    with pytest.raises(RuntimeError, match="stop"):
        with post_processing_validation_scope():
            remember_validation("example", "key", [1], files=())
            raise RuntimeError("stop")
    assert not validation_scope_active()
    assert cached_validation("example", "key") is CACHE_MISS


def test_validation_rejects_same_size_mtime_replacement_and_mid_read_change(tmp_path: Path):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    with post_processing_validation_scope():
        before = capture_validation_files([source])
        remember_validation("example", "key", [1], files=before)
        old_stat = source.stat()
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"modified")
        os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        replacement.replace(source)
        assert source.stat().st_size == old_stat.st_size
        assert source.stat().st_mtime_ns == old_stat.st_mtime_ns
        assert cached_validation("example", "key") is CACHE_MISS
        remember_validation("example", "key", [1], files=before)
        assert cached_validation("example", "key") is CACHE_MISS


def test_content_protection_rejects_in_place_change_with_identical_file_stats(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    with post_processing_validation_scope():
        before = capture_validation_files([source], hash_contents=True)
        remember_validation("example", "key", [1], files=before)
        old_stat = source.stat()
        actual_stat = Path.stat

        def unchanged_stat(path, *args, **kwargs):
            return old_stat if path == source else actual_stat(path, *args, **kwargs)

        source.write_bytes(b"modified")
        monkeypatch.setattr(Path, "stat", unchanged_stat)
        assert cached_validation("example", "key") is CACHE_MISS
