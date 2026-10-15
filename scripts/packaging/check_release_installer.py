"""Qualify the exact release installer on a disposable GitHub Windows runner.

Unlike the inert patch fixtures, this installs the actual application and opens
native windows. It deliberately refuses ordinary developer machines, existing
Toolbox registrations, and install paths outside RUNNER_TEMP. No release is
published. Evidence is retained under build/release-acceptance.
"""

from __future__ import annotations

import argparse
import configparser
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import psutil

from build_installer_inventory import read_manifest_file, sha256_file
from updater_metadata import version_data

APP_ID = "77E578C2-2B30-4015-AE3F-9CE6191423F4"
BASELINE_SHA256 = "192d43972e8b2031566d3b1bcbc9ae2b46305f39a544d3e12a7e46e6730178a6"
QT_PLATFORM_ENV = "QT_QPA_PLATFORM"
HEADLESS_QT_PLATFORMS = frozenset({"offscreen", "minimal"})


def require_disposable_runner(environ: dict[str, str], platform: str) -> Path:
    if platform != "win32" or environ.get("GITHUB_ACTIONS") != "true" or environ.get("CI") != "true":
        raise RuntimeError("Real installer acceptance is restricted to a disposable GitHub Windows runner.")
    root = Path(environ.get("RUNNER_TEMP", ""))
    if not root.is_absolute() or not root.is_dir():
        raise RuntimeError("RUNNER_TEMP must identify an existing absolute directory.")
    if environ.get(QT_PLATFORM_ENV, "").split(":", 1)[0].casefold() in HEADLESS_QT_PLATFORMS:
        raise RuntimeError("Real installer acceptance requires native visible Windows Qt.")
    return root.resolve()


def registrations() -> list[dict[str, object]]:
    import winreg

    found = []
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{APP_ID}}}_is1"
    for hive_name, hive in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    values = {"hive": hive_name, "view": view}
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _ = winreg.EnumValue(key, index)
                        values[name] = value
                    found.append(values)
            except FileNotFoundError:
                pass
    return found


def run(command: list[str], log: Path, *, env: dict[str, str], timeout: int = 300) -> None:
    completed = subprocess.run(command, env=env, capture_output=True, timeout=timeout, check=False)
    log.write_bytes(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}); see {log.name}.")


def require_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    if resolved == root.resolve():
        raise RuntimeError("An installation must use a child of its disposable root.")
    return resolved


def verify_release_metadata(installer: Path, version: str) -> dict[str, str]:
    metadata = installer.parent / f"FPVSToolbox-Update-{version}.json"
    document = json.loads(metadata.read_text(encoding="utf-8"))
    if (document.get("schema_version") != 1 or document.get("target_version") != version
            or document.get("platform") != "windows-x64"):
        raise RuntimeError("Release update metadata does not identify the target Windows version.")
    digests = {}
    for artifact in (installer, metadata):
        digest = sha256_file(artifact)
        sidecar = artifact.with_suffix(artifact.suffix + ".sha256")
        if sidecar.read_text(encoding="ascii").strip() != f"{digest}  {artifact.name}":
            raise RuntimeError(f"Release checksum sidecar differs from final artifact bytes: {artifact.name}")
        digests[artifact.name] = digest
    return digests


def seed_user_data(root: Path) -> dict[Path, bytes]:
    projects = root / "projects"
    settings = root / "config/settings"
    settings.mkdir(parents=True)
    projects.mkdir()
    ini = configparser.ConfigParser()
    ini.read_dict({"paths": {"projectsRoot": str(projects)}, "recent": {"projects": "[]"},
                   "updates": {"last_checked_utc": "2099-01-01T00:00:00+00:00"}})
    with (settings / "settings.ini").open("w", encoding="utf-8") as stream:
        ini.write(stream)
    sentinels = {}
    for relative in ("projects/study/project.json", "projects/study/outputs/result.csv",
                     "config/settings/researcher-notes.txt", "logs/analysis.log", ".fpvs_cache/template.bin"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        value = f"preserved user data: {relative}\n".encode()
        path.write_bytes(value)
        sentinels[path] = value
    return sentinels


def assert_sentinels(sentinels: dict[Path, bytes]) -> None:
    for path, expected in sentinels.items():
        if not path.is_file() or path.read_bytes() != expected:
            raise RuntimeError(f"Installer changed user data: {path}")


def assert_installed(destination: Path, manifest_path: Path, version: str) -> dict[str, object]:
    expected_bytes, manifest = read_manifest_file(manifest_path, expected_kind="current")
    if (destination / "fpvs-owned-files-v1.txt").read_bytes() != expected_bytes:
        raise RuntimeError("Installed ownership manifest differs from the release build.")
    for relative, digests in manifest.files.items():
        if sha256_file(destination / relative) != digests[0]:
            raise RuntimeError(f"Installed release bytes differ: {relative}")
    records = registrations()
    if not records or any(Path(str(record["InstallLocation"])).resolve() != destination.resolve()
                          or record.get("DisplayVersion") != version for record in records):
        raise RuntimeError("Installed registration does not identify the release and its isolated path.")
    return {"version": version, "owned_files_verified": len(manifest.files), "registration": records}


class NativeWindows:
    """Small Win32 adapter used only by the disposable acceptance process."""

    def __init__(self) -> None:
        from ctypes import wintypes

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user32.EnumChildWindows.argtypes = [wintypes.HWND, self.callback_type, wintypes.LPARAM]

    def text(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(2048)
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def windows(self, pids: set[int]) -> list[tuple[int, str]]:
        found = []

        @self.callback_type
        def visit(hwnd: int, _data: int) -> bool:
            pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and self.user32.IsWindowVisible(hwnd):
                found.append((hwnd, self.text(hwnd)))
            return True

        self.user32.EnumWindows(visit, 0)
        return found

    def advance_setup(self, hwnd: int) -> str | None:
        buttons = []

        @self.callback_type
        def visit(child: int, _data: int) -> bool:
            text = self.text(child).replace("&", "").strip()
            if text in {"Next >", "Install", "Finish"} and self.user32.IsWindowVisible(child) and self.user32.IsWindowEnabled(child):
                buttons.append((child, text))
            return True

        self.user32.EnumChildWindows(hwnd, visit, 0)
        if buttons:
            self.user32.PostMessageW(buttons[0][0], 0x00F5, 0, 0)  # BM_CLICK
            return buttons[0][1]
        return None

    def close(self, hwnd: int) -> None:
        self.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def app_processes(executable: Path) -> list[psutil.Process]:
    result = []
    for process in psutil.process_iter(["exe"]):
        try:
            if process.info["exe"] and Path(process.info["exe"]).resolve() == executable.resolve():
                result.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return result


def visible_relaunch(installer: Path, destination: Path, evidence: Path, env: dict[str, str]) -> dict[str, object]:
    """Exercise the real non-silent /RELAUNCH=1 branch and close its Main Window."""
    native = NativeWindows()
    executable = destination / "FPVS_Toolbox.exe"
    command = [str(installer), "/SP-", "/CURRENTUSER", "/SUPPRESSMSGBOXES", "/NORESTART",
               "/NOSHORTCUTS=1", "/RELAUNCH=1", f"/DIR={destination}", f"/LOG={evidence / 'relaunch-inno.log'}"]
    actions = []
    titles = set()
    launched = False
    process = subprocess.Popen(command, env=env)
    deadline = time.monotonic() + 300
    try:
        while time.monotonic() < deadline:
            setup_pids = {process.pid}
            try:
                setup_pids.update(child.pid for child in psutil.Process(process.pid).children(recursive=True))
            except psutil.NoSuchProcess:
                pass
            for hwnd, title in native.windows(setup_pids):
                titles.add(title)
                action = native.advance_setup(hwnd)
                if action:
                    actions.append(action)
            running = app_processes(executable)
            windows = native.windows({app.pid for app in running})
            for hwnd, title in windows:
                if "FPVS Toolbox" in title:
                    launched = True
                    native.close(hwnd)
            if process.poll() is not None and launched and not app_processes(executable):
                if process.returncode:
                    raise RuntimeError(f"Interactive relaunch installer exited {process.returncode}.")
                return {"main_window_opened_and_closed": True, "installer_actions": actions,
                        "installer_window_titles": sorted(titles)}
            time.sleep(0.5)
        raise RuntimeError(f"Installer relaunch timed out; actions={actions}, windows={sorted(titles)}.")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)
        for remaining in app_processes(executable):
            remaining.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--baseline", type=Path, required=True)
    arguments = parser.parse_args()
    if not arguments.execute:
        parser.error("Explicit --execute is required.")
    runner_root = require_disposable_runner(dict(os.environ), sys.platform)
    if registrations():
        raise RuntimeError("Refusing to replace an existing FPVS Toolbox registration.")
    if sha256_file(arguments.baseline) != BASELINE_SHA256:
        raise RuntimeError("The v2.1.2 baseline does not match its reviewed published SHA-256.")
    repo = Path(__file__).resolve().parents[2]
    _, version = version_data(repo)
    installer = repo / "installers" / f"FPVSToolbox-{version}-setup.exe"
    manifest = repo / "build/installer-inventory/current-owned-files.txt"
    evidence = repo / "build/release-acceptance"
    evidence.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="fpvs-release-", dir=runner_root))
    destination = require_within(root / "installed", root)
    user_root = root / "user"
    sentinels = seed_user_data(user_root)
    env = dict(os.environ, FPVS_CONFIG_HOME=str(user_root / "config"), MPLCONFIGDIR=str(user_root / "matplotlib"),
               MNE_DONTWRITE_HOME="true", _MNE_FAKE_HOME_DIR=str(user_root / "mne"))
    report: dict[str, object] = {"passed": False, "version": version, "source_commit": os.environ.get("GITHUB_SHA"),
                               "installer_sha256": sha256_file(installer), "baseline_sha256": BASELINE_SHA256,
                               "runner_root": str(root), "steps": []}
    steps: list[dict[str, object]] = report["steps"]  # type: ignore[assignment]

    def install(setup: Path, label: str) -> None:
        require_within(destination, root)
        run([str(setup.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER",
             "/NOLAUNCH=1", "/NOSHORTCUTS=1", f"/DIR={destination}", f"/LOG={evidence / (label + '-inno.log')}"],
            evidence / f"{label}-process.log", env=env)
        assert_sentinels(sentinels)

    def probe(label: str) -> None:
        command = ["pwsh", "-NoProfile", "-File", str(repo / "scripts/packaging/smoke_packaged_app.ps1"),
                   "-ExePath", str(destination / "FPVS_Toolbox.exe"), "-ExpectedVersion", version, "-AllowVisibleGui"]
        if label in {"fresh", "upgraded"}:
            command.append("-RunScientificWorkflows")
        run(command, evidence / f"{label}-smoke.log", env=env, timeout=600)
        assert_sentinels(sentinels)

    def uninstall(label: str) -> None:
        records = registrations()
        if not records or any(Path(str(record["InstallLocation"])).resolve() != destination for record in records):
            raise RuntimeError("Uninstall registration escaped the disposable installation.")
        run([str(destination / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={evidence / (label + '-inno.log')}"], evidence / f"{label}-process.log", env=env)
        if registrations() or (destination / "FPVS_Toolbox.exe").exists():
            raise RuntimeError("Uninstall left the application executable or registration behind.")
        assert_sentinels(sentinels)

    try:
        report["release_artifact_sha256"] = verify_release_metadata(installer, version)
        install(installer, "fresh")
        steps.append({"name": "fresh-install", **assert_installed(destination, manifest, version)})
        probe("fresh")
        probe("second-launch")
        steps.append({"name": "fresh-launch-close-relaunch", "passed": True})
        uninstall("fresh-uninstall")
        steps.append({"name": "fresh-uninstall-preserves-user-data", "passed": True})
        install(arguments.baseline, "v2-baseline")
        baseline_records = registrations()
        if not baseline_records or any(record.get("DisplayVersion") != "2.1.2" for record in baseline_records):
            raise RuntimeError("Published baseline did not register v2.1.2.")
        steps.append({"name": "published-v2.1.2-installed", "registration": baseline_records})
        install(installer, "v3-upgrade")
        steps.append({"name": "upgrade-v2.1.2", **assert_installed(destination, manifest, version)})
        probe("upgraded")
        steps.append({"name": "installer-relaunch", **visible_relaunch(installer, destination, evidence, env)})
        assert_sentinels(sentinels)
        uninstall("upgrade-uninstall")
        steps.append({"name": "upgrade-uninstall-preserves-user-data", "passed": True})
        report["preserved_user_data"] = [str(path.relative_to(user_root)) for path in sentinels]
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
    finally:
        for log in user_root.rglob("*.log"):
            shutil.copy2(log, evidence / f"user-{log.name}")
        (evidence / "installed-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
