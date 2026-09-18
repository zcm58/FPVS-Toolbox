"""Packaging inventory/candidate tests, not execution of the native Inno lifecycle."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from Main_App.updates.cache import recognized_cache_entry

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "packaging" / "build_installer_inventory.py"
SPEC = importlib.util.spec_from_file_location("toolbox_installer_inventory", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory
SPEC.loader.exec_module(inventory)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "application": "fpvs-toolbox",
        "releases": [
            {
                "tag": "v1.3.0",
                "asset_name": "FPVSToolbox-1.3.0-setup.exe",
                "asset_id": 534464281,
                "sha256": "a" * 64,
                "size_bytes": 260215143,
            }
        ],
        "files": [
            {"path": "FPVS_Toolbox.exe", "sha256": [_digest(b"old executable")]},
            {"path": "_internal/obsolete.dll", "sha256": [_digest(b"old library")]},
        ],
    }


def _legacy(tmp_path: Path, document: dict[str, object] | None = None) -> Path:
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(document or _source_document()), encoding="utf-8")
    return source


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "FPVS_Toolbox.exe").write_bytes(b"current executable")
    (root / "_internal").mkdir()
    (root / "_internal" / "current.txt").write_bytes(b"current data")
    return root


def test_first_inventory_does_not_invent_legacy_ownership(tmp_path):
    output = tmp_path / "inventories"
    result = inventory.build_inventories(
        bundle_root=_bundle(tmp_path), app_version="3.0.0",
        legacy_inventory=None, output_dir=output,
    )
    assert result["current_paths"] == 2
    assert result["legacy_paths"] == 0 and result["legacy_releases"] == 0
    legacy = (output / "legacy-owned-files.txt").read_text(encoding="utf-8-sig")
    assert "FPVS-TOOLBOX-OWNED-FILES-1" in legacy
    assert "FPVS_Toolbox.exe" not in legacy


@pytest.mark.parametrize(
    "relative",
    [
        "",
        ".",
        "..",
        "/outside.txt",
        "C:/outside.txt",
        "C:relative.txt",
        "//server/share/file",
        "_internal/../outside.txt",
        "_internal//file",
        "_internal/./file",
        "_internal\\file",
        "_internal/file.",
        "_internal/file ",
        "_internal/file:stream",
        "_internal/file|hash",
        "_internal/file\nnext",
        "_internal/CON.txt",
        "_internal/LPT1",
        "_internal/COM¹.txt",
        "project.json",
        "PROJECT.JSON",
        "runs/participant/file",
        "logs/file",
        "stimuli/file",
        ".fpvs-toolbox/templates/file",
        "cache/file",
        "unins000.exe",
        "unins000.dat",
        "fpvs-owned-files-v1.txt",
        "fpvs-pending-owned-files-v1.txt",
    ],
)
def test_unsafe_owned_paths_rejected(relative: str) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.validate_relative_path(relative)


@pytest.mark.parametrize(
    "relative",
    [
        "FPVS_Toolbox.exe",
        "pyproject.toml",
        "_internal/Main_App-1.3.0.dist-info/METADATA",
        "_internal/Unicode/naïve.txt",
        "_internal/multiple.dots.txt",
        "_internal/.hidden",
    ],
)
def test_safe_packaged_paths_preserve_spelling(relative: str) -> None:
    assert inventory.validate_relative_path(relative) == relative


def test_final_bundle_inventory_and_runtime_manifest_round_trip(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    output = tmp_path / "generated"
    summary = inventory.build_inventories(
        bundle_root=bundle,
        app_version="1.4.0",
        legacy_inventory=_legacy(tmp_path),
        output_dir=output,
    )
    assert summary == {
        "app_version": "1.4.0",
        "current_paths": 2,
        "legacy_paths": 2,
        "legacy_releases": 1,
    }
    wire = (output / "current-owned-files.txt").read_bytes()
    assert wire.startswith(b"\xef\xbb\xbf")
    current = inventory.parse_manifest(wire, expected_kind="current")
    assert current.files == {
        "_internal/current.txt": (_digest(b"current data"),),
        "FPVS_Toolbox.exe": (_digest(b"current executable"),),
    }
    old = inventory.parse_manifest(
        (output / "legacy-owned-files.txt").read_bytes(), expected_kind="legacy"
    )
    assert "_internal/obsolete.dll" in old.files


def test_missing_legacy_provenance_does_not_generate_inventories(tmp_path: Path) -> None:
    document = _source_document()
    document["releases"] = []
    with pytest.raises(inventory.InventoryError, match="provenance"):
        inventory.build_inventories(
            bundle_root=_bundle(tmp_path),
            app_version="1.4.0",
            legacy_inventory=_legacy(tmp_path, document),
            output_dir=tmp_path / "output",
        )
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("application", "another-app"),
        ("files", [{"path": "../outside.txt", "sha256": ["a" * 64]}]),
        ("files", [{"path": "FPVS_Toolbox.exe", "sha256": ["A" * 64]}]),
        ("files", [{"path": "FPVS_Toolbox.exe", "sha256": []}]),
        ("files", [{"path": "FPVS_Toolbox.exe", "sha256": ["a" * 64, "a" * 64]}]),
        (
            "files",
            [
                {"path": "FPVS_Toolbox.exe", "sha256": ["a" * 64]},
                {"path": "fpvs_toolbox.EXE", "sha256": ["b" * 64]},
            ],
        ),
        ("files", [{"path": "_internal/only.txt", "sha256": ["a" * 64]}]),
    ],
)
def test_malformed_legacy_inventory_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    document = _source_document()
    document[field] = value
    with pytest.raises(inventory.InventoryError):
        inventory.load_legacy_inventory(_legacy(tmp_path, document))


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.json"
    source.write_text('{"schema_version": 1, "schema_version": 2}', encoding="utf-8")
    with pytest.raises(inventory.InventoryError, match="Duplicate JSON"):
        inventory.load_legacy_inventory(source)


@pytest.mark.parametrize(
    "wire",
    [
        b"not a manifest",
        b"\xff\xff",
        b"FPVS-TOOLBOX-OWNED-FILES-1\nkind=pending\nversion=current\n",
        b"FPVS-TOOLBOX-OWNED-FILES-1\nkind=pending\nversion=pending\n../x|" + b"a" * 64,
        b"FPVS-TOOLBOX-OWNED-FILES-1\nkind=pending\nversion=pending\nx|bad",
    ],
)
def test_malformed_runtime_journal_rejected(wire: bytes) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.parse_manifest(wire, expected_kind="pending")


def test_empty_pending_journal_is_valid() -> None:
    wire = inventory.serialize_manifest(inventory.Inventory({}), kind="pending", version="pending")
    assert inventory.parse_manifest(wire.encode("utf-8"), expected_kind="pending").files == {}


def test_accumulated_ancestry_removes_only_obsolete_candidate_paths(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    obsolete = root / "_internal" / "obsolete.dll"
    obsolete.write_bytes(b"old library")
    unrelated = root / "lab-notes.txt"
    unrelated.write_text("user-owned", encoding="utf-8")
    previous, _ = inventory.load_legacy_inventory(_legacy(tmp_path))
    # Build the current inventory from the fresh package, not the dirty installation.
    current = inventory.Inventory(
        {
            "FPVS_Toolbox.exe": (_digest(b"current executable"),),
            "_internal/current.txt": (_digest(b"current data"),),
        }
    )
    candidates = inventory.obsolete_inventory(previous, current)
    assert candidates.files == {"_internal/obsolete.dll": (_digest(b"old library"),)}
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "owned"
    }
    # This helper is intentionally read-only; native deletion is still a VM acceptance check.
    assert obsolete.read_bytes() == b"old library"
    assert unrelated.read_text(encoding="utf-8") == "user-owned"


def test_modified_same_size_obsolete_file_preserved_in_pending_history(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "_internal" / "obsolete.dll").write_bytes(b"new library")
    candidates = inventory.Inventory({"_internal/obsolete.dll": (_digest(b"old library"),)})
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "modified"
    }
    assert inventory.pending_after_confirmed_cleanup(candidates, set()) == candidates


def test_missing_file_confirmation_does_not_forget_other_failures(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    candidates = inventory.Inventory(
        {
            "_internal/missing.dll": ("a" * 64,),
            "_internal/blocked.dll": ("b" * 64,),
        }
    )
    (root / "_internal" / "blocked.dll").write_bytes(b"modified")
    outcomes = inventory.inspect_obsolete_inventory(root, candidates)
    assert outcomes == {"_internal/missing.dll": "missing", "_internal/blocked.dll": "modified"}
    pending = inventory.pending_after_confirmed_cleanup(candidates, {"_internal/missing.dll"})
    assert pending.files == {"_internal/blocked.dll": ("b" * 64,)}
    encoded = inventory.serialize_manifest(pending, kind="pending", version="pending").encode()
    assert inventory.parse_manifest(encoded, expected_kind="pending") == pending


def test_hash_read_failure_remains_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _bundle(tmp_path)
    (root / "_internal" / "obsolete.dll").write_bytes(b"old library")
    candidates = inventory.Inventory({"_internal/obsolete.dll": (_digest(b"old library"),)})
    original_hash = inventory.sha256_file

    def denied(path: Path) -> str:
        raise PermissionError("synthetic sharing violation")

    monkeypatch.setattr(inventory, "sha256_file", denied)
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "unavailable"
    }
    pending = inventory.pending_after_confirmed_cleanup(candidates, set())
    monkeypatch.setattr(inventory, "sha256_file", original_hash)
    assert inventory.inspect_obsolete_inventory(root, pending) == {
        "_internal/obsolete.dll": "owned"
    }


def test_directory_at_owned_file_path_is_not_treated_as_owned(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "_internal" / "obsolete.dll").mkdir()
    candidates = inventory.Inventory({"_internal/obsolete.dll": ("a" * 64,)})
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "unsafe"
    }


def test_hardlinked_owned_file_is_unsafe(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    external = tmp_path / "user.txt"
    external.write_bytes(b"old library")
    os.link(external, root / "_internal" / "obsolete.dll")
    candidates = inventory.Inventory({"_internal/obsolete.dll": (_digest(b"old library"),)})
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "unsafe"
    }
    assert external.read_bytes() == b"old library"


def test_reparse_attribute_is_rejected_without_following_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _bundle(tmp_path)
    original = inventory.is_reparse_stat

    def pretend_reparse(details: os.stat_result) -> bool:
        return details.st_ino == (root / "_internal").stat().st_ino or original(details)

    monkeypatch.setattr(inventory, "is_reparse_stat", pretend_reparse)
    with pytest.raises(inventory.InventoryError, match="unsafe directory"):
        inventory.inventory_bundle(root)
    candidates = inventory.Inventory({"_internal/obsolete.dll": ("a" * 64,)})
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "unsafe"
    }


def test_broad_or_relative_roots_are_refused(tmp_path: Path) -> None:
    for root in (Path(tmp_path.anchor), Path("relative"), Path.home()):
        with pytest.raises(inventory.InventoryError):
            inventory.require_safe_directory(root)


def test_size_bound_is_checked_before_json_parse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(inventory, "MAX_MANIFEST_BYTES", 4)
    with pytest.raises(inventory.InventoryError, match="too large"):
        inventory.load_legacy_inventory(_legacy(tmp_path))


@pytest.mark.parametrize(
    "version", ["1banana", "1.0+", "1..2", "1/path", "1!2", "v1.0", "1.0+bad..local"]
)
def test_malformed_filename_versions_cannot_authorize_cache_cleanup(version: str) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.validate_version(version)


@pytest.mark.parametrize(
    "version", ["1.3.0", "0.9.0b5", "1.4.0rc1", "1.0.post2", "1.0.dev3", "1.0+local.2"]
)
def test_published_and_canonical_version_spellings_are_accepted(version: str) -> None:
    assert inventory.validate_version(version) == version


def test_read_only_tree_check_reports_owned_obsolete_sentinel_without_deleting(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)
    legacy = _legacy(tmp_path)
    generated = tmp_path / "generated"
    inventory.build_inventories(
        bundle_root=root,
        app_version="1.4.0",
        legacy_inventory=legacy,
        output_dir=generated,
    )
    expected = generated / "current-owned-files.txt"
    (root / inventory.CURRENT_MANIFEST_NAME).write_bytes(expected.read_bytes())
    command = [
        sys.executable,
        str(SCRIPT.with_name("check_installer_tree.py")),
        "--install-root",
        str(root),
        "--expected-manifest",
        str(expected),
        "--legacy-inventory",
        str(legacy),
    ]
    fresh = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    assert fresh.returncode == 0, fresh.stderr
    obsolete = root / "_internal" / "obsolete.dll"
    obsolete.write_bytes(b"old library")
    unrelated = root / "lab-notes.txt"
    unrelated.write_bytes(b"notes")
    dirty = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    assert dirty.returncode == 1, dirty.stderr
    assert json.loads(dirty.stdout)["remaining_obsolete_owned_files"] == ["_internal/obsolete.dll"]
    assert obsolete.read_bytes() == b"old library"
    assert unrelated.read_bytes() == b"notes"


@pytest.mark.parametrize(
    "name",
    [
        "FPVSToolbox-1banana-setup.exe",
        "FPVSToolbox-1banana-setup.exe.part",
        "FPVSToolbox-1banana-setup.exe.verified.json",
        "FPVSToolbox-1banana-setup.exe." + "a" * 32 + ".part",
        "FPVSToolbox-1.3.0-setup.exe.not-a-uuid.part",
        "FPVSToolbox-1.3.0-setup.exe.verified.not-a-uuid.tmp",
        "FPVSToolbox-1..3-setup.exe",
        "FPVSToolbox-1.3.0-setup.exe.notes",
        "FPVSToolbox-Setup-1+" + "a" * 178 + ".exe",
        "FPVSToolbox-Setup-1+" + "a" * 178 + ".exe.part",
        "FPVSToolbox-Setup-1+" + "a" * 178 + ".exe.verified.json",
        "FPVSToolbox-Setup-1+" + "a" * 178 + ".exe." + "b" * 32 + ".part",
        "FPVSToolbox-Setup-1+" + "a" * 178 + ".exe.verified." + "b" * 32 + ".tmp",
        "notes.verified.json",
    ],
)
def test_documented_uninstall_safety_fixtures_are_not_backend_owned(name: str) -> None:
    # Native source guards assert this contract is routed through the version/UUID
    # parsers. Executing the native matcher is still part of disposable-VM acceptance.
    assert recognized_cache_entry(name) is None


def test_failed_generated_file_replace_preserves_previous_and_removes_own_temporary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "current-owned-files.txt"
    target.write_bytes(b"previous manifest")

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError("synthetic replacement failure")

    monkeypatch.setattr(inventory.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        inventory._write_generated(target, "new manifest")
    assert target.read_bytes() == b"previous manifest"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing-violation diagnostic fixture")
def test_real_windows_locked_fixture_is_unavailable_then_retryable(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    target = root / "_internal" / "obsolete.dll"
    target.write_bytes(b"old library")
    candidates = inventory.Inventory({"_internal/obsolete.dll": (_digest(b"old library"),)})
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.CreateFileW(str(target), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        assert inventory.inspect_obsolete_inventory(root, candidates) == {
            "_internal/obsolete.dll": "unavailable"
        }
        assert inventory.pending_after_confirmed_cleanup(candidates, set()) == candidates
    finally:
        kernel32.CloseHandle(handle)
    assert inventory.inspect_obsolete_inventory(root, candidates) == {
        "_internal/obsolete.dll": "owned"
    }
    assert target.read_bytes() == b"old library"
