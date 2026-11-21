import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Main_App.io.condition_data import write_condition_companion
from Main_App.io.result_manifest import write_result_manifest
from Main_App.io.spectral_data import write_spectral_companion
from Main_App.processing import source_release_files as release


def _outcomes(root: Path):
    anchor = root / "result.fpvs"
    frame = pd.DataFrame({"Electrode": ["O1"], "0.0000_Hz": [1.5]})
    spectral = write_spectral_companion(anchor, {"FullFFT Amplitude (uV)": frame})
    condition = write_condition_companion(anchor, {"BCA (uV)": frame})
    schema = write_result_manifest(
        anchor, spectral_companion=spectral, condition_companion=condition,
        sheet_names=[*spectral["sheets"], *condition["sheets"]],
    )
    stat = anchor.stat()
    written = dict(
        version="workbook_write_receipt_v1", status="written", path=str(anchor), schema_validation=schema,
        artifact=dict(path=str(anchor), sha256=hashlib.sha256(anchor.read_bytes()).hexdigest(),
                      size=stat.st_size, mtime_ns=stat.st_mtime_ns),
        spectral_companion=spectral, condition_companion=condition,
    )
    ready = SimpleNamespace(status="partially_retained", export_receipt=dict(path=str(anchor), workbook_write=written))
    return SimpleNamespace(cells=[ready, SimpleNamespace(status="excluded", export_receipt=None)])


@pytest.mark.parametrize("member", ["anchor", "spectral_companion", "condition_companion"])
def test_verifies_every_native_member_with_open_writer_and_restored_timestamp(tmp_path, member):
    outcomes = _outcomes(tmp_path)
    files = release.NativeReleaseFiles.from_outcomes(outcomes, project_root=tmp_path)
    written = outcomes.cells[0].export_receipt["workbook_write"]
    anchor = Path(written["path"])
    assert files.anchors == {anchor}
    assert files.companion_paths == tuple(tmp_path / written[k]["path"] for k in ("spectral_companion", "condition_companion"))
    assert files.current(1)
    assert files.current(16)
    target = anchor if member == "anchor" else tmp_path / written[member]["path"]
    stat = target.stat()
    with target.open("r+b") as writer:
        changed = bytes([writer.read(1)[0] ^ 1])
        writer.seek(0)
        writer.write(changed)
        writer.flush()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert target.stat().st_size == stat.st_size
        assert not files.current(2)


@pytest.mark.parametrize("damage", [
    "legacy", "duplicate", "missing_descriptor", "new_descriptor", "outside", "aliased_descriptor",
    "sha_missing", "path_escape", "missing_file", "wrong_size", "wrong_anchor_time", "blocked", "unavailable_only",
])
def test_unattested_or_ambiguous_releases_use_full_validation(tmp_path, damage):
    root = tmp_path / "project"
    root.mkdir()
    outcomes = _outcomes(root)
    cell = outcomes.cells[0]
    written = cell.export_receipt["workbook_write"]
    anchor = Path(written["path"])
    if damage in {"legacy", "outside"}:
        path = anchor.with_suffix(".xlsx") if damage == "legacy" else tmp_path / anchor.name
        anchor.rename(path)
        cell.export_receipt["path"] = written["path"] = written["artifact"]["path"] = str(path)
    elif damage == "duplicate":
        outcomes.cells.append(cell)
    elif damage == "missing_descriptor":
        del written["spectral_companion"]
    elif damage == "new_descriptor":
        written["condition_companion"]["sha256"] = "0" * 64
    elif damage == "aliased_descriptor":
        condition = root / written["condition_companion"]["path"]
        condition.unlink()
        os.link(root / written["spectral_companion"]["path"], condition)
        written["condition_companion"]["size_bytes"] = condition.stat().st_size
        declaration = json.loads(anchor.read_bytes())
        declaration["condition_companion"] = written["condition_companion"]
        anchor.write_text(json.dumps(declaration), encoding="utf-8")
        written["artifact"].update(size=anchor.stat().st_size, mtime_ns=anchor.stat().st_mtime_ns,
                                   sha256=hashlib.sha256(anchor.read_bytes()).hexdigest())
    elif damage == "sha_missing":
        written["artifact"]["sha256"] = ""
    elif damage == "path_escape":
        written["condition_companion"]["path"] = "../outside.npz"
    elif damage == "missing_file":
        (root / written["spectral_companion"]["path"]).unlink()
    elif damage == "wrong_size":
        written["artifact"]["size"] += 1
    elif damage == "wrong_anchor_time":
        written["artifact"]["mtime_ns"] += 1
    elif damage == "blocked":
        cell.status = "blocked"
    else:
        cell.status = "unavailable"
    assert release.NativeReleaseFiles.from_outcomes(outcomes, project_root=root) is None


def test_unavailable_threads_still_check_all_release_bytes(tmp_path, monkeypatch):
    files = release.NativeReleaseFiles.from_outcomes(_outcomes(tmp_path), project_root=tmp_path)

    def unavailable_pool(*, max_workers):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(release, "ThreadPoolExecutor", unavailable_pool)
    assert files.current(16)
    target = files.companion_paths[-1]
    target.write_bytes(b"X" * target.stat().st_size)
    assert not files.current(16)


def test_edit_after_checksum_invalidates_the_proof(tmp_path, monkeypatch):
    files = release.NativeReleaseFiles.from_outcomes(_outcomes(tmp_path), project_root=tmp_path)
    path = next(iter(files.anchors))
    original = release.hashlib.file_digest

    def change_after_read(stream, algorithm):
        digest = original(stream, algorithm)
        if stream.name == str(path):
            # An ordinary timestamp edit is permitted while the descriptor is open on Windows.
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        return digest

    monkeypatch.setattr(release.hashlib, "file_digest", change_after_read)
    assert not files.current(1)


def test_alias_retarget_after_creation_invalidates_the_proof(tmp_path):
    files = release.NativeReleaseFiles.from_outcomes(_outcomes(tmp_path), project_root=tmp_path)
    target = files.companion_paths[0]
    other = target.with_suffix(".bak")
    target.rename(other)
    try:
        target.symlink_to(other)
    except OSError:
        pytest.skip("File symlink creation unavailable")
    assert not files.current(2)
