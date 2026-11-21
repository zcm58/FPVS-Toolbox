"""Toolbox automatic error reporting lifecycle. This module does not import Qt."""

from __future__ import annotations

import faulthandler
import logging
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import CancelledError
from pathlib import Path
from types import TracebackType

from Main_App.diagnostics.crash_delivery import CrashClient
from Main_App.diagnostics.crash_inventory import collect_inventory, os_identity, safe_name
from Main_App.diagnostics.crash_store import CrashStore, exception_stack
from Main_App.settings.settings_paths import SettingsPathError, app_config_home

DISCLOSURE = (
    "FPVS Toolbox can automatically send error and crash reports to the OpenFPVS feedback service. "
    "Reports include Toolbox and operating system versions, available hardware model, CPU and graphics models, "
    "memory, relevant software versions, the time and kind of failure, and a short list of code locations. "
    "Reports exclude project and EEG data, filenames and paths, full logs, and personal and device identifiers. "
    "You can turn reporting off at any time in Settings > Diagnostics. Turning it off deletes pending reports."
)
_LOGGER = logging.getLogger(__name__)
_STORAGE_ERRORS = (OSError, sqlite3.Error, ValueError, SettingsPathError)
_EXPECTED_ERRORS = (OSError, ValueError, CancelledError, KeyboardInterrupt, SystemExit)
_OPERATIONS = {"startup", "application", "project", "processing", "export", "unknown"}
_REPORT_REFERENCE = "_fpvs_toolbox_report_reference"
_active: CrashReporter | None = None


class CrashReporter:
    def __init__(self, store: CrashStore, version: str, client: CrashClient | None = None) -> None:
        self.store = store
        self.version = safe_name(version) or "Unknown"
        self._client = client
        self._session: tuple[str, str] | None = None
        self._version_identity: tuple[str, str, str | None] | None = None
        self._native_stream = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._operation = "startup"
        self._prior_hook = sys.excepthook
        self._prior_thread_hook = threading.excepthook

    def install(self) -> None:
        """Install delegating hooks and begin capture only for already disclosed consent."""
        sys.excepthook = self._python_exception
        threading.excepthook = self._thread_exception
        self._sync_session()
        self._thread = threading.Thread(target=self._run, name="Automatic crash reporting", daemon=True)
        self._thread.start()

    def preference(self) -> bool | None:
        return self.store.preference()

    def set_preference(self, enabled: bool) -> None:
        with self._lock:
            self.store.set_preference(enabled)
            self._sync_session()
        self._wake.set()

    def _sync_session(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            generation = self.store.generation()
            if self._session and self._session[1] == generation:
                return
            previous = self._session
            self._close_native()
            if previous:
                self.store.native_path(previous[0]).unlink(missing_ok=True)
            if generation is None:
                return
            self._version_identity = os_identity()
            family, version, build = self._version_identity
            self._session = self.store.begin(self.version, family, version, {"os_build": build} if build else {})
            if self._session:
                session, _ = self._session
                if self._operation != "startup":
                    self.store.update_session(session, operation=self._operation)
                self._open_native(session)

    def _open_native(self, session: str) -> None:
        if faulthandler.is_enabled():
            return  # Leave other enabled fault handlers under their existing owner.
        try:
            descriptor = os.open(self.store.native_path(session), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            stream = os.fdopen(descriptor, "wb", buffering=0)
            try:
                faulthandler.enable(stream, all_threads=False)
            except (OSError, RuntimeError):
                stream.close()
                raise
            self._native_stream = stream
        except (OSError, RuntimeError):
            _LOGGER.warning("automatic_crash_native_capture_unavailable")

    def _close_native(self) -> None:
        if self._native_stream is not None:
            faulthandler.disable()
            self._native_stream.close()
            self._native_stream = None
        self._session = None

    def set_operation(self, operation: str) -> None:
        with self._lock:
            self._operation = operation
            if self._session:
                self.store.update_session(self._session[0], operation=operation)

    def capture(
        self, error: BaseException, operation: str, *, fatal: bool = False, unhandled: bool = False,
        trace: TracebackType | None = None,
    ) -> None:
        if isinstance(error, _EXPECTED_ERRORS):
            return
        try:
            with self._lock:
                if self._stop.is_set() or not self._session:
                    return
                session, _ = self._session
                reference = vars(error).get(_REPORT_REFERENCE)
                previous = reference[1] if isinstance(reference, tuple) and reference[0] == session else None
                if previous and not fatal:
                    return
                report = self.store.capture(
                    session, "python_exception" if unhandled else "internal_error",
                    operation if operation in _OPERATIONS else "unknown",
                    exception_stack(trace or error.__traceback__), fatal=fatal, previous=previous,
                )
                if report:
                    vars(error)[_REPORT_REFERENCE] = (session, report)
        except _STORAGE_ERRORS:
            _LOGGER.warning("automatic_crash_capture_unavailable")
        self._wake.set()

    def _python_exception(self, kind, error, trace) -> None:
        try:
            self.capture(error, self._operation, unhandled=True, trace=trace)
        finally:
            self._prior_hook(kind, error, trace)

    def _thread_exception(self, args) -> None:
        try:
            if args.thread is not self._thread:
                self.capture(args.exc_value, self._operation, unhandled=True, trace=args.exc_traceback)
        finally:
            self._prior_thread_hook(args)

    def shutdown(self, *, clean: bool) -> None:
        global _active
        if _active is self:
            _active = None
        self._stop.set()
        self._wake.set()
        with self._lock:
            session = self._session
            self._close_native()
            if session and clean:
                try:
                    self.store.end(session[0])
                except _STORAGE_ERRORS:
                    _LOGGER.warning("automatic_crash_session_cleanup_failed")
        if sys.excepthook == self._python_exception:
            sys.excepthook = self._prior_hook
        if threading.excepthook == self._thread_exception:
            threading.excepthook = self._prior_thread_hook

    def _run(self) -> None:
        last_inventory = None
        while not self._stop.is_set():
            try:
                self._sync_session()
                with self._lock:
                    session, os_info = self._session, self._version_identity
                if session and os_info and session != last_inventory and self.store.generation() == session[1]:
                    inventory = collect_inventory(os_info[0], os_info[2])
                    self.store.update_session(session[0], context=inventory)
                    last_inventory = session
                self.store.recover()
                self.deliver()
            except _STORAGE_ERRORS:
                _LOGGER.warning("automatic_crash_background_work_unavailable")
            self._wake.wait(20)
            self._wake.clear()

    def deliver(self) -> None:
        """Claim at most three items. Consent is rechecked around network operations."""
        for _ in range(3):
            if self._stop.is_set():
                return
            revoke = self.store.claim(revocation=True)
            if revoke is not None:
                if self._transport().revoke(revoke["installation"], revoke["token"]):
                    self.store.finish(revoke["installation"], revocation=True)
                continue
            request = self.store.claim(revocation=False)
            if request is None:
                return
            report, installation = request
            self._deliver_report(report, installation)

    def _deliver_report(self, report, installation: str) -> None:
        if installation != self.store.generation() or self._stop.is_set():
            return
        client = self._transport()
        report_id, receipt = report["id"], report["receipt"]
        if report["attempts"] and client.accepted(report_id, receipt):
            self.store.finish(report_id)
            return
        grant = self.store.grant(installation)
        if grant is None or self._stop.is_set():
            return
        token = grant["token"]
        if grant["expires"] <= time.time():
            expires = client.register(installation, token)
            if expires <= time.time():
                return
            self.store.grant_issued(installation, expires)
        if installation == self.store.generation() and not self._stop.is_set():
            if client.send(installation, token, report["payload"], receipt, report_id):
                self.store.finish(report_id)

    def _transport(self) -> CrashClient:
        if self._client is None:
            self._client = CrashClient()
        return self._client


def start_reporting(version: str, *, root: Path | None = None) -> CrashReporter | None:
    global _active
    reporter = None
    try:
        reporter = CrashReporter(CrashStore(root or (app_config_home() / "support" / "automatic-crashes")), version)
        reporter.install()
    except _STORAGE_ERRORS:
        if reporter is not None:
            reporter.shutdown(clean=True)
        _LOGGER.warning("automatic_crash_reporting_unavailable")
        return None
    _active = reporter
    return reporter


def current_reporter() -> CrashReporter | None:
    return _active


def report_failure(error: BaseException, operation: str) -> None:
    if _active is not None:
        _active.capture(error, operation)


def set_operation(operation: str) -> None:
    if _active is not None:
        try:
            _active.set_operation(operation)
        except _STORAGE_ERRORS:
            _LOGGER.warning("automatic_crash_operation_update_failed")
