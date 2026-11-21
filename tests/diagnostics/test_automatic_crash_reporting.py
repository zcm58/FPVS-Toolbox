"""Automatic reporting keeps research data local and retains one durable identity."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from queue import Queue

import pytest

from Main_App.diagnostics import crash_inventory, crash_reporting, crash_store
from Main_App.diagnostics.crash_delivery import CrashClient, MAX_ENVELOPE
from Main_App.diagnostics.crash_inventory import os_identity, safe_name
from Main_App.diagnostics.crash_reporting import CrashReporter
from Main_App.diagnostics.crash_store import CrashStore


class FakeDelivery:
    def __init__(self):
        self.online = True
        self.accept_upload = True
        self.confirm_receipt = False
        self.registrations = []
        self.sends = []
        self.checks = []
        self.revocations = []

    def register(self, installation, token):
        self.registrations.append((installation, token))
        return round(time.time()) + 3600 if self.online else 0

    def revoke(self, installation, token):
        self.revocations.append((installation, token))
        return self.online

    def accepted(self, report_id, receipt):
        self.checks.append((report_id, receipt))
        return self.online and self.confirm_receipt

    def send(self, *args):
        self.sends.append(args)
        return self.online and self.accept_upload


def _execute(store, sql):
    connection = sqlite3.connect(store.database)
    try:
        with connection:
            return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _reports(store):
    return [json.loads(row[0]) for row in _execute(store, "SELECT payload FROM reports ORDER BY created")]


@pytest.fixture
def reporter(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_reporting.faulthandler, "is_enabled", lambda: True)
    result = CrashReporter(CrashStore(tmp_path / "automatic-crashes"), "3.0.0", FakeDelivery())
    result._sync_session()
    yield result
    result.shutdown(clean=True)


def _fault():
    code = compile('raise RuntimeError("C:/users/user/project/participant-P001.edf secret@email.com")',
                   "Main_App/workers/processing_worker.py", "exec")
    try:
        exec(code)
    except RuntimeError as error:
        return error


def test_disclosure_gate_and_preference_generation(reporter):
    assert reporter.preference() is None
    reporter.capture(_fault(), "processing")
    reporter.deliver()
    assert _execute(reporter.store, "SELECT id FROM sessions") == []
    assert _reports(reporter.store) == []
    assert reporter._client.registrations == []

    reporter.set_preference(True)
    generation = reporter.store.generation()
    reporter.capture(ValueError("Expected validation rejection"), "processing")
    reporter.capture(OSError("Expected ordinary I/O failure"), "processing")
    reporter.capture(_fault(), "processing")
    report, = _reports(reporter.store)
    family, version, _ = os_identity()
    assert (report["schema_version"], report["product"], report["app_version"]) == ("2", "toolbox", "3.0.0")
    assert (report["os_family"], report["os_version"]) == (family, version)
    assert report["time_basis"] == "occurrence"
    assert report["crash_type"] == "internal_error"
    assert report["operation"] == "processing"
    assert report["stack"][-1] == {"module": "Main_App/workers/processing_worker.py", "function": "<module>", "line": 1}
    serialized = json.dumps(report)
    assert all(private not in serialized for private in ("participant-P001", "secret@email.com", "C:/users", "RuntimeError"))
    assert crash_store._safe_frame("C:/research/Tools/participant.py", "private", 1)["module"] == "<external>"

    _execute(reporter.store, "UPDATE reports SET due = 0")
    reporter._client.online = False
    reporter.deliver()
    issued = reporter._client.registrations[0]
    reporter.set_preference(False)
    assert _reports(reporter.store) == []
    assert CrashStore(reporter.store.root).preference() is False
    assert reporter.store.generation() is None
    reporter._client.online = True
    reporter.deliver()
    assert reporter._client.revocations == [issued]
    reporter.set_preference(True)
    assert reporter.store.generation() != generation
    assert _reports(reporter.store) == []


def test_worker_controller_fault_keeps_existing_terminal_failure(reporter, tmp_path, monkeypatch):
    from Main_App.workers import process_runner

    reporter.set_preference(True)
    monkeypatch.setattr(crash_reporting, "_active", reporter)

    def unexpected(*args):
        raise RuntimeError("Private recording filename")

    monkeypatch.setattr(process_runner, "_run_project_parallel", unexpected)
    queue = Queue()
    params = process_runner.RunParams(tmp_path, [tmp_path / "participant.bdf"], {}, {}, tmp_path, 1)
    result = process_runner.run_project_parallel(params, queue)
    assert result["status"] == "error"
    assert queue.get_nowait() == result
    report, = _reports(reporter.store)
    assert (report["operation"], report["crash_type"]) == ("processing", "internal_error")
    assert "participant.bdf" not in json.dumps(report)
    assert "Private recording filename" not in json.dumps(report)


def test_ambiguous_upload_uses_receipt_and_exact_payload(reporter):
    reporter.set_preference(True)
    reporter.capture(_fault(), "processing")
    _execute(reporter.store, "UPDATE reports SET due = 0")
    client = reporter._client
    client.accept_upload = False
    reporter.deliver()
    first, = client.sends
    assert _execute(reporter.store, "SELECT due FROM reports")[0][0] > time.time() + 890

    # A fresh process uses the original extension and receipt rather than recapturing.
    restarted = CrashReporter(CrashStore(reporter.store.root), "3.1.0", client)
    _execute(reporter.store, "UPDATE reports SET due = 0")
    restarted.deliver()
    assert client.sends == [first, first]
    assert client.checks == [(first[-1], first[-2])]
    client.confirm_receipt = True
    _execute(reporter.store, "UPDATE reports SET due = 0")
    restarted.deliver()
    assert client.sends == [first, first]
    assert _reports(reporter.store) == []


def test_report_budget_and_fatal_promotion_does_not_mutate_pending_bytes(reporter, monkeypatch):
    reporter.set_preference(True)
    error = _fault()
    reporter.capture(error, "processing")
    original, = _reports(reporter.store)
    reporter.capture(error, "application", fatal=True, unhandled=True)
    assert _reports(reporter.store) == [original]
    monkeypatch.setattr(crash_store, "_process_alive", lambda _pid: False)
    reporter.store.recover()
    assert _reports(reporter.store) == [original]
    reporter.shutdown(clean=True)

    for _ in range(14):
        session, _ = reporter.store.begin("3.0.0", "Linux", "6.12.1", {})
        reporter.store.capture(session, "internal_error", "processing", [], fatal=False, previous=None)
        reporter.store.end(session)
    assert len(_reports(reporter.store)) == 10


def test_clean_healthy_and_unclean_exit(reporter, monkeypatch):
    store = reporter.store
    reporter.set_preference(True)
    first_session = reporter._session[0]
    store.recover()
    assert _reports(store) == []
    assert _execute(store, "SELECT id FROM sessions") == [(first_session,)]
    reporter.shutdown(clean=True)
    assert _execute(store, "SELECT id FROM sessions") == []

    store.begin("3.0.1", "Linux", "6.12.0", {"cpu_model": "Example CPU"})
    monkeypatch.setattr(crash_store, "_process_alive", lambda _pid: False)
    store.recover()
    report, = _reports(store)
    assert (report["crash_type"], report["time_basis"], report["stack"]) == ("unclean_shutdown", "recovery", [])
    assert report["app_version"] == "3.0.1"
    assert report["context"] == {"cpu_model": "Example CPU"}
    store.recover()
    assert _reports(store) == [report]


def test_native_fault_is_recovered_from_a_dead_subprocess(tmp_path):
    root = tmp_path / "crashes"
    store = CrashStore(root)
    store.set_preference(True)
    env = dict(os.environ, PYTHONPATH=str(Path(crash_reporting.__file__).resolve().parents[2]))
    code = """
import faulthandler, os, sys
from pathlib import Path
from Main_App.diagnostics.crash_reporting import CrashReporter
from Main_App.diagnostics.crash_store import CrashStore
if sys.platform == 'win32':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(2)
else:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
faulthandler.disable()
reporter = CrashReporter(CrashStore(Path(sys.argv[1])), '3.0.0')
reporter._sync_session()
os.abort()
"""
    failed = subprocess.run([sys.executable, "-c", code, str(root)], env=env, timeout=15, capture_output=True)
    assert failed.returncode != 0
    store.recover()
    recovered, = _reports(store)
    assert recovered["crash_type"] == "native_fault"
    assert recovered["time_basis"] == "occurrence"
    assert recovered["stack"]
    assert not list(root.glob("native-*.trace"))


def test_transport_uses_separate_hashed_receipt_and_bounded_envelope(monkeypatch):
    calls = []
    client = CrashClient()

    def request(path, token, body, *, installation):
        calls.append((path, token, body, installation))
        return {"report_id": "example-id", "state": "received"}

    monkeypatch.setattr(client, "_request", request)
    assert client.send("installation", "grant", b'{"report_id":"example-id"}', "receipt", "example-id")
    path, grant, envelope, installation = calls[0]
    assert path == "/v1/crash-reports"
    assert (installation, grant) == ("installation", "grant")
    assert len(envelope) <= MAX_ENVELOPE
    assert json.loads(envelope) == {
        "report": {"report_id": "example-id"},
        "receipt_token_sha256": hashlib.sha256(b"receipt").hexdigest(),
    }


@pytest.mark.parametrize("value", ["C:/User/My PC", "asset tag 999", "90:4C:E5:88:63:D7", "c8a2ce27-b98e-41e6-b56f-500eaf22c888"])
def test_inventory_rejects_potential_identifiers(value):
    assert safe_name(value) is None


def test_inventory_retains_safe_cpu_model_when_gpu_and_memory_are_unavailable(monkeypatch):
    monkeypatch.setattr(crash_inventory, "_windows_inventory", lambda: {"cpu_model": "Example™ CPU @ 4.20GHz"})
    result = crash_inventory.collect_inventory("Windows", "12345.6")
    assert result["cpu_model"] == "Example(TM) CPU 4.20GHz"
    assert result["os_build"] == "12345.6"
    assert "ram_gib" not in result
    assert "gpus" not in result
