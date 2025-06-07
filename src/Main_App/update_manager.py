# Handles automatic update checking and installation for the FPVS Toolbox.
import os
import sys
import threading
import tempfile
import subprocess
import requests
from tkinter import messagebox
from packaging.version import parse as version_parse

from config import FPVS_TOOLBOX_VERSION, FPVS_TOOLBOX_UPDATE_API


def check_for_updates_async(app):
    """Check for updates in a background thread."""
    threading.Thread(target=_check_for_updates, args=(app,), daemon=True).start()


def _check_for_updates(app):
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
        else:
            app.log("No update available.")
    except Exception as e:
        app.log(f"Update check failed: {e}")


def _find_exe_asset(data):
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def _perform_update(url, version, changelog, app):
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
        backup = current_exe + ".old"
        app.log("Replacing executable...")
        try:
            if os.path.exists(backup):
                os.remove(backup)
        except Exception:
            pass
        os.replace(current_exe, backup)
        os.replace(tmp_path, current_exe)

        messagebox.showinfo(
            "Update Installed",
            f"FPVS Toolbox has been updated to {version}.\n"
            "The application will now restart.\n\n"
            f"Changelog:\n{changelog}",
        )
        subprocess.Popen([current_exe])
        app.destroy()
    except Exception as e:
        app.log(f"Update failed: {e}")
        messagebox.showerror("Update Failed", str(e))
