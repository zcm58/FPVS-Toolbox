"""Opt-in native Inno acceptance using inert payloads and unique test application IDs.

All fixture installs, sentinels, installers, and logs stay below build/. The actual
Inno script disables application closing and updater-cache cleanup for a test AppId.
No FPVS Toolbox executable, Qt application, or production installer is launched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from build_installer_inventory import (
    CURRENT_MANIFEST_NAME,
    build_inventories,
    inventory_bundle,
    read_manifest_file,
    require_safe_directory,
    sha256_file,
)
from build_patch import PATCH_MARKER_NAME, prepare_patch
from updater_metadata import windows_version

PRODUCTION_APP_ID = "77E578C2-2B30-4015-AE3F-9CE6191423F4"


def run(command: list[str], log: Path, *, success: bool = True) -> int:
    completed = subprocess.run(
        command,
        capture_output=True,
        timeout=120,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    log.write_bytes(completed.stdout + completed.stderr)
    if (completed.returncode == 0) != success:
        raise RuntimeError(f"Unexpected exit {completed.returncode}; see {log}")
    return completed.returncode


def tree_hashes(root: Path) -> dict[str, str]:
    require_safe_directory(root)
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def registration(app_id: str) -> dict[str, object] | None:
    import winreg

    path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{app_id}}}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            values = {}
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, _ = winreg.EnumValue(key, index)
                values[name] = value
            return values
    except FileNotFoundError:
        return None


def assert_installed(
    root: Path, bundle: Path, manifest: Path, *, expected_marker: bytes | None = None
) -> None:
    expected_bytes, expected = read_manifest_file(manifest, expected_kind="current")
    if (root / CURRENT_MANIFEST_NAME).read_bytes() != expected_bytes:
        raise RuntimeError("Installed ownership manifest differs from the final target.")
    if inventory_bundle(bundle) != expected:
        raise RuntimeError("Fixture bundle changed after manifest generation.")
    for relative, hashes in expected.files.items():
        if sha256_file(root / relative) != hashes[0]:
            raise RuntimeError(f"Installed target differs: {relative}")
    marker = root / PATCH_MARKER_NAME
    if expected_marker is None:
        if marker.exists():
            raise RuntimeError("Successful installation retained a patch transaction marker.")
    elif marker.read_bytes() != expected_marker:
        raise RuntimeError("Full repair changed an unrelated file using the marker filename.")


def make_bundle(root: Path, version: str, *, removed: str, added: str) -> Path:
    bundle = root / f"bundle-{version}"
    payloads = {
        "FPVS_Toolbox.exe": f"INERT NON-EXECUTABLE FIXTURE {version}\n",
        "_internal/unchanged.txt": "unchanged shared dependency\n",
        f"_internal/{added}": f"added in {version}\n",
        "_internal/toolbox-updater-version.json": json.dumps({"version": version}),
    }
    if removed:
        payloads[f"_internal/{removed}"] = "known obsolete fixture bytes\n"
    for relative, content in payloads.items():
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inno-compiler", type=Path, required=True)
    parser.add_argument(
        "--execute", action="store_true", help="Explicitly run isolated setup fixtures."
    )
    arguments = parser.parse_args()
    if os.name != "nt" or not arguments.execute:
        parser.error("Native lifecycle acceptance requires Windows and explicit --execute.")
    repo = Path(__file__).resolve().parents[2]
    check_root = repo / "build" / "patch-installer-lifecycle"
    require_safe_directory(check_root)
    check_root.mkdir(parents=True, exist_ok=True)
    fixture = Path(tempfile.mkdtemp(prefix="native-", dir=check_root))
    fixture.resolve().relative_to(check_root.resolve())
    require_safe_directory(fixture)
    sys.stdout.write(f"Native fixture evidence: {fixture}\n")
    sys.stdout.flush()
    production_before = registration(PRODUCTION_APP_ID)
    chain_id, fresh_id = str(uuid.uuid4()).upper(), str(uuid.uuid4()).upper()
    if registration(chain_id) or registration(fresh_id):
        raise RuntimeError("A generated fixture application ID is already registered.")
    installed = fixture / "installed-chain"
    fresh = fixture / "installed-fresh"
    steps: list[str] = []
    report: dict[str, object] = {
        "fixture_root": str(fixture),
        "application_ids": [chain_id, fresh_id],
        "source_sha256": {
            name: sha256_file(repo / name)
            for name in (
                "scripts/packaging/FPVS Toolbox Setup Script.iss",
                "scripts/packaging/patch_upgrade.iss",
                "scripts/packaging/owned_files.iss",
                "scripts/packaging/updater_cache.iss",
                "scripts/packaging/build_patch.py",
                "scripts/packaging/check_patch_installer_lifecycle.py",
            )
        },
        "steps": steps,
        "ok": False,
    }

    def compile_setup(
        version: str,
        app_id: str,
        label: str,
        patch: dict | None = None,
        *,
        fail_verification: bool = False,
        raise_verification: bool = False,
    ) -> Path:
        command = [
            str(arguments.inno_compiler.resolve()),
            "/Qp",
            f"/DAppVersion={version}",
            f"/DWindowsVersion={windows_version(version)}",
            f"/DAppIdGuid={app_id}",
            f"/DBundleRoot={bundles[version]}",
            f"/DOwnedInventoryRoot={inventories[version]}",
            f"/O{fixture / 'compiled'}",
            f"/F{label}",
        ]
        if patch is not None:
            command.extend(
                [
                    f"/DPatchFromVersion={patch['from_version']}",
                    f"/DPatchRoot={patch_root}",
                    f"/DPatchSourceSHA256={patch['source_inventory_sha256']}",
                    f"/DPatchTargetSHA256={patch['target_inventory_sha256']}",
                    f"/DPatchTransactionSHA256={patch['transaction_sha256']}",
                ]
            )
        if fail_verification:
            command.append("/DPatchTestFailVerification=1")
        if raise_verification:
            command.append("/DPatchTestRaiseVerification=1")
        command.append(str(repo / "scripts/packaging/FPVS Toolbox Setup Script.iss"))
        run(command, fixture / f"{label}-compile.log")
        return fixture / "compiled" / f"{label}.exe"

    def install(executable: Path, destination: Path, label: str, *, success: bool = True) -> int:
        destination.resolve().relative_to(fixture.resolve())
        require_safe_directory(destination)
        executable.resolve().relative_to((fixture / "compiled").resolve())
        return run(
            [
                str(executable),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                "/NOLAUNCH=1",
                "/NOSHORTCUTS=1",
                "/NOCLOSEAPPLICATIONS",
                f"/DIR={destination}",
                f"/GROUP=FPVS lifecycle {chain_id}",
                f"/LOG={fixture / (label + '-inno.log')}",
            ],
            fixture / f"{label}-process.log",
            success=success,
        )

    def uninstall(destination: Path, app_id: str, label: str) -> None:
        destination.resolve().relative_to(fixture.resolve())
        require_safe_directory(destination)
        record = registration(app_id)
        if (
            record is None
            or Path(str(record["InstallLocation"])).resolve() != destination.resolve()
        ):
            raise RuntimeError(
                "Fixture uninstall registration does not identify its isolated path."
            )
        executable = Path(str(record["UninstallString"]).strip('"'))
        if (
            executable.resolve().parent != destination.resolve()
            or re.fullmatch(r"unins[0-9]+\.exe", executable.name, re.IGNORECASE) is None
        ):
            raise RuntimeError("Fixture uninstall command escaped its isolated installation.")
        run(
            [
                str(executable),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                f"/LOG={fixture / (label + '-inno.log')}",
            ],
            fixture / f"{label}-process.log",
        )
        if registration(app_id) is not None:
            raise RuntimeError("Fixture uninstall registration was not removed.")

    try:
        bundles = {
            "0.0.1": make_bundle(fixture, "0.0.1", removed="obsolete.txt", added="base-only.txt"),
            "0.0.2": make_bundle(fixture, "0.0.2", removed="", added="patch-added.txt"),
            "0.0.3": make_bundle(fixture, "0.0.3", removed="", added="full-added.txt"),
        }
        inventories = {version: fixture / f"inventory-{version}" for version in bundles}
        for version, bundle in bundles.items():
            build_inventories(
                bundle_root=bundle,
                app_version=version,
                legacy_inventory=None,
                output_dir=inventories[version],
            )
        manifests = {
            version: path / "current-owned-files.txt" for version, path in inventories.items()
        }
        patch_root = fixture / "patch"
        patch = prepare_patch(
            baseline_inventory=manifests["0.0.1"],
            source_inventory_sha256=sha256_file(manifests["0.0.1"]),
            bundle_root=bundles["0.0.2"],
            target_inventory=manifests["0.0.2"],
            target_version="0.0.2",
            output_dir=patch_root,
        )
        base_setup = compile_setup("0.0.1", chain_id, "base")
        patch_setup = compile_setup("0.0.2", chain_id, "patch", patch)
        failed_patch_setup = compile_setup(
            "0.0.2", chain_id, "patch-failed-verification", patch, fail_verification=True
        )
        exception_patch_setup = compile_setup(
            "0.0.2", chain_id, "patch-verification-exception", patch, raise_verification=True
        )
        full_setup = compile_setup("0.0.3", chain_id, "full-upgrade")
        repair_setup = compile_setup("0.0.2", chain_id, "full-repair")
        fresh_setup = compile_setup("0.0.2", fresh_id, "fresh-target")
        # First Toolbox migration has no authenticated historical inventory.
        # Setup must establish ownership without claiming unknown legacy files.
        installed.mkdir(parents=True)
        (installed / "FPVS_Toolbox.exe").write_bytes(b"inert unrecorded legacy executable")
        legacy_file = installed / "unrecorded-legacy.dll"
        legacy_file.write_bytes(b"unknown legacy bytes must survive")
        install(base_setup, installed, "base")
        assert_installed(installed, bundles["0.0.1"], manifests["0.0.1"])
        if legacy_file.read_bytes() != b"unknown legacy bytes must survive":
            raise RuntimeError("Migration modified a file without ownership evidence.")
        steps.append("full migration without historical ownership inventory")
        sentinels = [
            legacy_file,
            installed / "lab-notes.txt",
            fixture / "user-data/project.json",
            fixture / "user-data/settings.ini",
            fixture / "user-data/runs/keep.txt",
            fixture / "user-data/logs/keep.txt",
            fixture / "user-data/.fpvs-toolbox/templates/keep.txt",
        ]
        for sentinel in sentinels:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("preserve fixture user data\n", encoding="utf-8")
        sentinel_hashes = {path: sha256_file(path) for path in sentinels}
        unchanged = installed / "_internal/unchanged.txt"
        original = unchanged.read_bytes()
        unchanged.write_bytes(b"X" * len(original))
        before = tree_hashes(installed)
        install(patch_setup, installed, "wrong-base", success=False)
        if tree_hashes(installed) != before:
            raise RuntimeError("Refused patch wrote to an incompatible installation.")
        unchanged.write_bytes(original)
        steps.append("same-size corrupt baseline refused before writes")
        collision = installed / "_internal/patch-added.txt"
        collision.write_bytes(b"Unrelated pre-existing user file.\n")
        before = tree_hashes(installed)
        install(patch_setup, installed, "added-path-collision", success=False)
        if tree_hashes(installed) != before:
            raise RuntimeError(
                "Refused patch changed a pre-existing file at an added payload path."
            )
        collision.unlink()
        steps.append("new payload path collision refused without modifying user content")
        hardlink_source = fixture / "hardlink-source.txt"
        hardlink_source.write_bytes(original)
        unchanged.unlink()
        os.link(hardlink_source, unchanged)
        try:
            before = tree_hashes(installed)
            install(patch_setup, installed, "retained-hardlink", success=False)
            if tree_hashes(installed) != before or hardlink_source.read_bytes() != original:
                raise RuntimeError("Refused patch changed retained hardlink content.")
        finally:
            unchanged.unlink()
            unchanged.write_bytes(original)
        steps.append("retained hardlink refused before writes")
        junction_script = fixture / "create-junction.ps1"
        junction_script.write_text(
            "param([string]$LinkPath, [string]$TargetPath)\n"
            "New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath "
            "-ErrorAction Stop | Out-Null\n",
            encoding="utf-8",
        )
        internal = installed / "_internal"
        junction_target = fixture / "junction-target"
        internal.rename(junction_target)
        try:
            run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(junction_script),
                    "-LinkPath",
                    str(internal),
                    "-TargetPath",
                    str(junction_target),
                ],
                fixture / "create-junction.log",
            )
            before = tree_hashes(junction_target)
            install(patch_setup, installed, "retained-junction", success=False)
            if tree_hashes(junction_target) != before:
                raise RuntimeError("Refused patch wrote through a retained directory junction.")
        finally:
            if internal.exists():
                os.rmdir(internal)
            junction_target.rename(internal)
        steps.append("retained directory junction refused without changing its target")
        install(patch_setup, installed, "valid-patch")
        assert_installed(installed, bundles["0.0.2"], manifests["0.0.2"])
        install(fresh_setup, fresh, "fresh-target")
        assert_installed(fresh, bundles["0.0.2"], manifests["0.0.2"])
        for old in inventory_bundle(bundles["0.0.1"]).files:
            if old not in inventory_bundle(bundles["0.0.2"]).files and (installed / old).exists():
                raise RuntimeError(f"Patch retained an obsolete owned file: {old}")
        steps.append("patched payload equals fresh target; obsolete owned files removed")
        install(full_setup, installed, "full-upgrade")
        assert_installed(installed, bundles["0.0.3"], manifests["0.0.3"])
        steps.append("subsequent full upgrade")
        uninstall(fresh, fresh_id, "uninstall-fresh")
        uninstall(installed, chain_id, "uninstall-chain")
        steps.append("full-upgraded chain uninstalled")
        install(base_setup, installed, "recovery-base")
        result = install(failed_patch_setup, installed, "failed-verification", success=False)
        if result != 12:
            raise RuntimeError(
                f"A failed patch did not report its repair-needed exit code: {result}"
            )
        failed_registration = registration(chain_id)
        if failed_registration is None or failed_registration["DisplayVersion"] != "0.0.2":
            raise RuntimeError("Post-copy failure did not exercise target-version recovery.")
        if (installed / PATCH_MARKER_NAME).read_bytes() != (
            patch_root / "patch-transaction.txt"
        ).read_bytes():
            raise RuntimeError("A failed patch did not retain its authenticated recovery marker.")
        for relative, hashes in inventory_bundle(bundles["0.0.1"]).files.items():
            if relative not in inventory_bundle(bundles["0.0.2"]).files:
                if sha256_file(installed / relative) != hashes[0]:
                    raise RuntimeError("Post-copy failure removed obsolete source recovery files.")
        steps.append("forced verification failure reports repair and preserves marker/source files")
        replaced = installed / "FPVS_Toolbox.exe"
        recovery_bytes = replaced.read_bytes() if replaced.exists() else None
        replaced.write_bytes(b"Unrecognized damaged recovery payload.\n")
        before = tree_hashes(installed)
        install(patch_setup, installed, "corrupt-recovery", success=False)
        if tree_hashes(installed) != before:
            raise RuntimeError("Refused recovery wrote to an unrecognized payload state.")
        if recovery_bytes is None:
            replaced.unlink()
        else:
            replaced.write_bytes(recovery_bytes)
        steps.append("unrecognized recovery bytes refused before writes")
        install(patch_setup, installed, "recovery-retry")
        assert_installed(installed, bundles["0.0.2"], manifests["0.0.2"])
        steps.append("normal patch retry recovered to complete target")
        uninstall(installed, chain_id, "uninstall-recovered")
        install(base_setup, installed, "full-repair-base")
        result = install(exception_patch_setup, installed, "verification-exception", success=False)
        if result != 12 or not (installed / PATCH_MARKER_NAME).exists():
            raise RuntimeError("A hashing exception did not report repair and retain its marker.")
        if not (installed / "_internal/obsolete.txt").exists():
            raise RuntimeError("A hashing exception incorrectly removed obsolete source files.")
        steps.append("hashing exception reports repair and preserves recovery state")
        install(repair_setup, installed, "repair-matched-marker")
        assert_installed(installed, bundles["0.0.2"], manifests["0.0.2"])
        steps.append("full target repair clears an authenticated failed-patch marker")
        marker = installed / PATCH_MARKER_NAME
        unrelated_markers = {
            "malformed": b"Unrelated lab notes using this filename.\n",
            "unrelated-fingerprints": (
                "FPVS-TOOLBOX-PATCH-TRANSACTION-1\r\nfrom=0.0.1\r\nto=0.0.2\r\n"
                f"source={'a' * 64}\r\ntarget={'b' * 64}\r\n"
            ).encode("utf-8-sig"),
        }
        for label, data in unrelated_markers.items():
            marker.write_bytes(data)
            install(repair_setup, installed, f"repair-{label}-marker")
            assert_installed(installed, bundles["0.0.2"], manifests["0.0.2"], expected_marker=data)
        steps.append("full repair preserves malformed and unrelated-fingerprint marker files")
        uninstall(installed, chain_id, "uninstall-full-repair")
        if marker.read_bytes() != unrelated_markers["unrelated-fingerprints"]:
            raise RuntimeError("Uninstall removed an unrelated marker-name file.")
        for path, digest in sentinel_hashes.items():
            if sha256_file(path) != digest:
                raise RuntimeError(f"Fixture user-data sentinel changed: {path}")
        for bundle in bundles.values():
            for relative in inventory_bundle(bundle).files:
                if (installed / relative).exists():
                    raise RuntimeError(f"Uninstall retained an owned fixture file: {relative}")
        steps.append("uninstall removed owned files and retained all user-data sentinels")
        report["ok"] = True
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["production_registration_unchanged"] = (
            registration(PRODUCTION_APP_ID) == production_before
        )
        (fixture / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if not report["production_registration_unchanged"]:
            raise RuntimeError(
                "The production uninstall registration changed during fixture acceptance."
            )
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
