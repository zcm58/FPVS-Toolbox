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
                                "No installer asset found in release.",
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
    """Return the download URL of the installer executable.

    The release assets uploaded to GitHub include an installer built with
    Inno Setup.  The filename convention used for the installer ends with
    ``-Setup.exe``.  This helper searches the ``assets`` list of the GitHub
    release response for such a file and returns its ``browser_download_url``.
    """

    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith("-setup.exe"):
            return asset.get("browser_download_url")
    return None


def _perform_update(url, version, changelog, app):
    """Download the installer and run it silently."""
    try:
        app.log(f"Downloading update from {url}")
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as tmp:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        tmp.write(chunk)
                tmp_path = tmp.name

        app.log(f"Launching installer {tmp_path}")
        subprocess.Popen([
            tmp_path,
            "/VERYSILENT",
            "/NORESTART",
        ], close_fds=True)

        messagebox.showinfo(
            "Update Started",
            "The application will close and the installer will run to "
            "update FPVS Toolbox.",
        )
        app.destroy()
    except Exception as e:
        app.log(f"Update failed: {e}")
        messagebox.showerror("Update Failed", str(e))
