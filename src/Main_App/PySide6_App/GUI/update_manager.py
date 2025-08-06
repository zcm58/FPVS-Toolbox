"""Check for application updates via GitHub releases."""

from __future__ import annotations

import os
import sys
import threading

import requests
from packaging import version
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from config import FPVS_TOOLBOX_VERSION, FPVS_TOOLBOX_UPDATE_API


def cleanup_old_executable() -> None:
    """Remove leftover backup executable after updating."""
    backup = sys.executable + ".old"
    try:
        if os.path.exists(backup):
            os.remove(backup)
    except Exception:
        pass


def _is_newer(latest: str, current: str) -> bool:
    """Return True if ``latest`` represents a newer version than ``current``."""
    return version.parse(latest.lstrip("v")) > version.parse(current.lstrip("v"))


def check_for_updates_async(app, silent: bool = True, notify_if_no_update: bool = True) -> None:
    """Check for updates in a background thread."""
    threading.Thread(
        target=_check_for_updates,
        args=(app, silent, notify_if_no_update),
        daemon=True,
    ).start()


def _check_for_updates(app, silent: bool, notify_if_no_update: bool) -> None:
    """Fetch release info and schedule any UI dialogs on the main thread."""
    app.log("Checking for updates...")
    try:
        resp = requests.get(FPVS_TOOLBOX_UPDATE_API, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        latest = data["tag_name"]
        url = data["html_url"]
    except Exception as e:  # pragma: no cover - network failure
        app.log(f"Update check failed: {e}")
        if not silent:
            app.after(0, lambda: QMessageBox.warning(app, "Update Error", "Could not check for updates."))
        return

    current = f"v{FPVS_TOOLBOX_VERSION}"
    if _is_newer(latest, current):
        if silent:
            app.log(f"Update {latest} available at {url}")
            return

        def prompt() -> None:
            msg = QMessageBox.question(
                app,
                "Update Available",
                f"A newer version ({latest}) is available.\nVisit the release page?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if msg == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(url))

        app.after(0, prompt)
    else:
        app.log("No update available.")
        if not silent and notify_if_no_update:
            app.after(
                0,
                lambda: QMessageBox.information(
                    app,
                    "Up to Date",
                    f"You are running the latest version ({current}).",
                ),
            )
