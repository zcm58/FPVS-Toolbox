import os
import sys
import threading
import tempfile
import subprocess
import requests
from tkinter import messagebox
from packaging.version import parse as version_parse

from config import FPVS_TOOLBOX_VERSION, FPVS_TOOLBOX_UPDATE_API


def cleanup_old_executable():
    """Remove leftover backup executable after updating."""
    backup = sys.executable + ".old"
    try:
        if os.path.exists(backup):
            os.remove(backup)
    except Exception:
        pass


def check_for_updates_async(app, silent=True, notify_if_no_update=True):
    """Check for updates in a background thread.

    Args:
        app: Reference to the main application instance.
        silent: If True, suppress message boxes and only log results.
        notify_if_no_update: When ``False`` and ``silent`` is ``False``,
            suppress the "Up to Date" popup.
    """
    threading.Thread(
        target=_check_for_updates, args=(app, silent, notify_if_no_update), daemon=True
    ).start()


def _check_for_updates(app, silent=True, notify_if_no_update=True):
    """Fetch release info and schedule any UI dialogs on the main thread."""
    app.log("Checking for updates...")
    try:
        resp = requests.get(FPVS_TOOLBOX_UPDATE_API, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        latest = data.get("tag_name") or data.get("version")
        changelog = data.get("body", "")
        if not latest:
            raise ValueError("No version field in update response.")

        current = version_parse(FPVS_TOOLBOX_VERSION)
        remote = version_parse(latest.lstrip("v"))

        if remote > current:
            if silent:
                app.log(
                    f"Update {latest} available. Use 'Check for Updates' in the File menu to update."
                )
            else:
                def prompt():
                    if messagebox.askyesno(
                        "Update Available",
                        f"A new version ({latest}) is available.\n"
                        f"You have {FPVS_TOOLBOX_VERSION}.\n\n"
                        "Download and install now?",
                    ):
                        asset_url = _find_exe_asset(data)
                        if asset_url:
                            _perform_update(asset_url, latest, changelog, app)
                        else:
                            messagebox.showwarning(
                                "Update Error",
                                "No executable asset found in release.",
                            )
                app.after(0, prompt)
        else:
            if silent:
                app.log("No update available.")
            else:
                if notify_if_no_update:
                    app.after(0, lambda: messagebox.showinfo(
                        "Up to Date",
                        f"You are running the latest version ({FPVS_TOOLBOX_VERSION}).",
                    ))
    except Exception as e:
        app.log(f"Update check failed: {e}")
        if not silent:
            app.after(0, lambda: messagebox.showerror("Update Check Failed", str(e)))


def _find_exe_asset(data):
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def _perform_update(url, version, changelog, app):
    """Download the update and schedule replacement of the running executable."""
    try:
        app.log(f"Downloading update from {url}")
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as tmp:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        tmp.write(chunk)
                tmp_path = tmp.name

        current_exe = sys.executable
        pid = os.getpid()
        backup = current_exe + ".old"
        script_ext = ".bat" if os.name == "nt" else ".sh"
        script = tempfile.NamedTemporaryFile(delete=False, suffix=script_ext)
        script_path = script.name
        script.close()
        log_path = script_path + ".log"

        if os.name == "nt":
            lines = f"""@echo off
set EXE=\"{current_exe}\"
set NEW=\"{tmp_path}\"
set BACKUP=\"{backup}\"
set LOG=\"{log_path}\"
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
    timeout /T 1 >nul
    goto wait
)
echo Updating >> "%LOG%" 2>&1
move /Y "%EXE%" "%BACKUP%" >> "%LOG%" 2>&1
if errorlevel 1 goto fail
move /Y "%NEW%" "%EXE%" >> "%LOG%" 2>&1
if errorlevel 1 goto fail
start "" "%EXE%"
del "%BACKUP%" >> "%LOG%" 2>&1
del "%~f0"
exit /b
:fail
echo Failed to replace executable >> "%LOG%" 2>&1
exit /b 1
"""
        else:
            lines = f"""#!/bin/sh
EXE=\"{current_exe}\"
NEW=\"{tmp_path}\"
BACKUP=\"{backup}\"
LOG=\"{log_path}\"
while kill -0 {pid} 2>/dev/null; do
    sleep 1
done
echo Updating >> "$LOG" 2>&1
mv "$EXE" "$BACKUP" >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo Failed to backup executable >> "$LOG" 2>&1
    exit 1
fi
mv "$NEW" "$EXE" >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo Failed to replace executable >> "$LOG" 2>&1
    mv "$BACKUP" "$EXE" >> "$LOG" 2>&1
    exit 1
fi
"$EXE" &
rm -f "$BACKUP"
rm -- "$0"
"""

        with open(script_path, "w", newline="\r\n" if os.name == "nt" else "\n") as f:
            f.write(lines)
        if os.name != "nt":
            os.chmod(script_path, 0o755)

        app.log(f"Launching update script {script_path}")
        subprocess.Popen([script_path], close_fds=True)

        messagebox.showinfo(
            "Update Installed",
            f"FPVS Toolbox has been updated to {version}.\n",
            "The application will now restart.\n\n",
            f"Changelog:\n{changelog}",
        )
        app.destroy()
    except Exception as e:
        app.log(f"Update failed: {e}")
        messagebox.showerror("Update Failed", str(e))
