"""Transactional app-local consent, session markers, and immutable crash outbox."""

from __future__ import annotations

import ctypes
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import time
from contextlib import closing, contextmanager
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from Main_App.diagnostics.crash_delivery import MAX_ENVELOPE, encode

MAX_AGE = 7 * 86400
_NATIVE_FRAME = re.compile(r'File "([^"\r\n]+)", line (\d{1,7}) in ([^\r\n]+)')
_MODULE = re.compile(r"(?:Main_App|Tools|fpvs_toolbox)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py\Z")
_FUNCTION = re.compile(r"[A-Za-z0-9_.<>-]{1,80}\Z")
_NATIVE_FILE = re.compile(r"native-[0-9a-f-]{36}\.trace\Z")
_SOURCE_ROOT = Path(__file__).resolve().parents[2].as_posix() + "/"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS preference (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    enabled INTEGER, installation TEXT, token TEXT,
    grant_started INTEGER NOT NULL DEFAULT 0, expires INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO preference (singleton) VALUES (1);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, installation TEXT NOT NULL, pid INTEGER NOT NULL, started REAL NOT NULL,
    app_version TEXT NOT NULL, os_family TEXT NOT NULL, os_version TEXT NOT NULL,
    context TEXT NOT NULL, operation TEXT NOT NULL DEFAULT 'startup', fatal_id TEXT,
    last_stack BLOB, last_error REAL
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, session TEXT NOT NULL, created REAL NOT NULL,
    payload BLOB NOT NULL, receipt TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS revocations (
    installation TEXT PRIMARY KEY, token TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0
);
"""


def _safe_frame(filename: str, function: str, line: int) -> dict:
    path = filename.replace("\\", "/")
    location = path.casefold() if os.name == "nt" else path
    root = _SOURCE_ROOT.casefold() if os.name == "nt" else _SOURCE_ROOT
    module = path[len(root):] if location.startswith(root) else path
    if len(module) > 160 or not _MODULE.fullmatch(module):
        module, function = "<external>", "<external>"
    elif not _FUNCTION.fullmatch(function):
        function = "<unknown>"
    return {"module": module, "function": function, "line": min(max(0, line), 1_000_000)}


def exception_stack(trace: TracebackType | None) -> list[dict]:
    stack = deque(maxlen=40)
    while trace is not None:
        code = trace.tb_frame.f_code
        stack.append(_safe_frame(code.co_filename, code.co_name, trace.tb_lineno))
        trace = trace.tb_next
    return list(stack)


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) can terminate a Windows process.
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        api.OpenProcess.restype = ctypes.c_void_p
        api.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is inconclusive.
        try:
            code = ctypes.c_uint32()
            return not api.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _assert_not_redirected(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise OSError("Crash reporting storage is redirected.")


class CrashStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        _assert_not_redirected(root)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            root.chmod(0o700)
        self.database = root / "crash-reports.sqlite3"
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)

    def _connect(self):
        _assert_not_redirected(self.database)
        _assert_not_redirected(self.database.with_suffix(".sqlite3-journal"))
        conn = sqlite3.connect(self.database, timeout=0.25)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA secure_delete = ON")
        return conn

    @contextmanager
    def _write(self):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def preference(self) -> bool | None:
        with closing(self._connect()) as connection:
            value = connection.execute("SELECT enabled FROM preference").fetchone()[0]
        return None if value is None else bool(value)

    def generation(self) -> str | None:
        with closing(self._connect()) as connection:
            return self._generation(connection)

    def set_preference(self, enabled: bool) -> None:
        with self._write() as connection:
            current = connection.execute("SELECT * FROM preference").fetchone()
            if current["enabled"] == enabled:
                return
            if enabled:
                connection.execute(
                    "UPDATE preference SET enabled = 1, installation = ?, token = ?, grant_started = 0, expires = 0",
                    (str(uuid4()), secrets.token_urlsafe(32)),
                )
            else:
                if current["grant_started"]:
                    connection.execute(
                        "INSERT INTO revocations (installation, token) VALUES (?, ?)",
                        (current["installation"], current["token"]),
                    )
                connection.execute(
                    "UPDATE preference SET enabled = 0, installation = NULL, token = NULL, grant_started = 0, expires = 0"
                )
                connection.execute("DELETE FROM reports")
                connection.execute("DELETE FROM sessions")

    def begin(self, version: str, os_family: str, os_version: str, context: dict) -> tuple[str, str] | None:
        with self._write() as connection:
            install = self._generation(connection)
            if not install:
                return None
            session = str(uuid4())
            connection.execute(
                "INSERT INTO sessions (id, installation, pid, started, app_version, os_family, os_version, context) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session, install, os.getpid(), time.time(), version, os_family, os_version, encode(context)),
            )
            return session, install

    @staticmethod
    def _generation(connection) -> str | None:
        row = connection.execute("SELECT installation FROM preference WHERE enabled = 1").fetchone()
        return row[0] if row else None

    def update_session(self, session: str, *, operation: str | None = None, context: dict | None = None) -> None:
        with self._write() as connection:
            if operation is not None:
                connection.execute("UPDATE sessions SET operation = ? WHERE id = ?", (operation, session))
            if context is not None:
                connection.execute("UPDATE sessions SET context = ? WHERE id = ?", (encode(context), session))

    def end(self, session: str) -> None:
        with self._write() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session,))
        self.native_path(session).unlink(missing_ok=True)

    def native_path(self, session: str) -> Path:
        return self.root / f"native-{session}.trace"

    def capture(
        self, session: str, category: str, operation: str, stack: list[dict], *, fatal: bool, previous: str | None,
    ) -> str | None:
        with self._write() as connection:
            active = self._generation(connection)
            marker = connection.execute("SELECT * FROM sessions WHERE id = ? AND installation = ?",
                                        (session, active)).fetchone()
            if not marker:
                return None
            report = previous or str(uuid4())
            if not previous:
                now = time.time()
                self._enqueue(connection, marker, report, category, operation, stack, now, "occurrence")
                connection.execute("UPDATE sessions SET last_stack = ?, last_error = ? WHERE id = ?",
                                   (encode({"stack": stack[-3:]}), now, session))
            if fatal:
                connection.execute("UPDATE sessions SET fatal_id = ? WHERE id = ?", (report, session))
            return report

    def _enqueue(self, connection, marker, report, category, operation, stack, created, time_basis) -> None:
        # Grant/receipt data is local metadata, never inside the report.
        payload = encode({
            "schema_version": "2", "kind": "crash", "product": "toolbox", "report_id": report,
            "created_at": datetime.fromtimestamp(created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "time_basis": time_basis, "crash_type": category, "operation": operation,
            "app_version": marker["app_version"], "os_family": marker["os_family"], "os_version": marker["os_version"],
            "stack": stack, "context": json.loads(marker["context"]),
        })
        if len(payload) > MAX_ENVELOPE - 110:
            raise ValueError("The automatic report exceeds its byte budget.")
        now = time.time()
        connection.execute("DELETE FROM reports WHERE created < ?", (now - MAX_AGE,))
        connection.execute(
            "INSERT OR IGNORE INTO reports (id, session, created, payload, receipt, due) "
            "SELECT ?, ?, ?, ?, ?, ? WHERE (SELECT count(*) FROM reports) < 10",
            (report, marker["id"], now, payload, secrets.token_urlsafe(32), now + 15),
        )

    def recover(self) -> None:
        now = time.time()
        with self._write() as connection:
            active = self._generation(connection)
            connection.execute("DELETE FROM reports WHERE created < ?", (now - MAX_AGE,))
            sessions = connection.execute("SELECT * FROM sessions WHERE installation = ?", (active,)).fetchall()
        for marker in sessions:
            if _process_alive(marker["pid"]):
                continue
            self._recover_session(marker, now)
        self._remove_orphans(now)

    def _recover_session(self, marker, now: float) -> None:
        session = marker["id"]
        path = self.native_path(session)
        category, time_basis, stack, occurrence = "unclean_shutdown", "recovery", [], now
        if marker["started"] >= now - MAX_AGE and not marker["fatal_id"]:
            try:
                _assert_not_redirected(path)
                with path.open("rb") as stream:
                    native = stream.read(128 * 1024).decode("utf-8", errors="replace")
                    mtime = os.fstat(stream.fileno()).st_mtime
                if native.startswith(("Fatal Python error:", "Windows fatal exception:")):
                    category = "native_fault"
                    stack = [_safe_frame(filename, function, int(line))
                             for filename, line, function in _NATIVE_FRAME.findall(native)[:40]]
                    if marker["started"] <= mtime <= now:
                        time_basis, occurrence = "occurrence", mtime
            except OSError:
                pass  # Recovery can still classify an unexplained exit.
        with self._write() as connection:
            active = self._generation(connection)
            existing = connection.execute("SELECT * FROM sessions WHERE id = ? AND installation = ?",
                                          (session, active)).fetchone()
            if existing and not existing["fatal_id"] and marker["started"] >= now - MAX_AGE:
                if not self._matches_native(existing, category, occurrence, stack):
                    self._enqueue(connection, existing, session, category, existing["operation"], stack, occurrence, time_basis)
            if existing:
                connection.execute("DELETE FROM sessions WHERE id = ?", (session,))
        path.unlink(missing_ok=True)

    @staticmethod
    def _matches_native(marker, category: str, occurrence: float, stack: list[dict]) -> bool:
        last_error = marker["last_error"]
        if category != "native_fault" or last_error is None or not 0 <= occurrence - last_error <= 30:
            return False
        native = {(frame["module"], frame["function"]) for frame in stack if frame["module"] != "<external>"}
        prior = json.loads(marker["last_stack"])["stack"]
        return any((frame["module"], frame["function"]) in native for frame in prior)

    def _remove_orphans(self, now: float) -> None:
        with closing(self._connect()) as connection:
            active = {row[0] for row in connection.execute("SELECT id FROM sessions")}
        for path in self.root.iterdir():
            if _NATIVE_FILE.fullmatch(path.name) and path.stem.removeprefix("native-") not in active:
                try:
                    if path.lstat().st_mtime <= now - 60:
                        path.unlink()
                except (FileNotFoundError, PermissionError):
                    pass

    def claim(self, *, revocation: bool):
        with self._write() as connection:
            now = time.time()
            table = "revocations" if revocation else "reports"
            key = "installation" if revocation else "id"
            if not revocation and not self._generation(connection):
                return None
            row = connection.execute(f"SELECT * FROM {table} WHERE due <= ? ORDER BY due LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            due = now + min(900 * 2 ** min(row["attempts"], 7), 86400)
            connection.execute(f"UPDATE {table} SET attempts = attempts + 1, due = ? WHERE {key} = ?",
                               (due, row[key]))
            if revocation:
                return row
            return row, self._generation(connection)

    def finish(self, key: str, *, revocation: bool = False) -> None:
        with self._write() as connection:
            if revocation:
                connection.execute("DELETE FROM revocations WHERE installation = ?", (key,))
            else:
                connection.execute("DELETE FROM reports WHERE id = ?", (key,))

    def grant(self, installation: str):
        with self._write() as connection:
            row = connection.execute("SELECT token, expires FROM preference WHERE enabled = 1 AND installation = ?",
                                     (installation,)).fetchone()
            if row:
                connection.execute("UPDATE preference SET grant_started = 1")
            return row

    def grant_issued(self, installation: str, expires: int) -> None:
        with self._write() as connection:
            connection.execute("UPDATE preference SET expires = ? WHERE enabled = 1 AND installation = ?",
                               (expires, installation))
