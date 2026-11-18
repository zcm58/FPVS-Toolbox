"""Bounded HTTPS delivery to the dedicated OpenFPVS analysis namespace."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from Main_App.projects.manifest_store import project_manifest_transaction
from Main_App.reporting.credentials import CredentialStore
from Main_App.reporting.snapshots import (
    MAX_ATTEMPTS,
    MAX_REQUEST_BYTES,
    canonical_json,
    load_snapshot,
    read_state,
    record_delivery,
    save_scope,
    state_path,
)
from Main_App.updates.application import APP_VERSION

ORIGIN = "https://openfpvs.com"
MAX_RESPONSE_BYTES = 64 * 1024


class ReportingError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(route: str, payload: dict | None, token: str | None = None) -> dict:
    receipt_route = False
    if route.startswith("/analysis/v1/snapshots/") and route.endswith("/receipt"):
        try:
            identifier = str(UUID(route.removeprefix("/analysis/v1/snapshots/").removesuffix("/receipt")))
            receipt_route = route == f"/analysis/v1/snapshots/{identifier}/receipt"
        except ValueError:
            pass
    if (receipt_route and payload is not None) or (
        not receipt_route and (route not in {"/analysis/v1/enroll", "/analysis/v1/snapshots"} or payload is None)
    ):
        raise ReportingError("invalid_route")
    body = None if receipt_route else canonical_json(payload).encode("utf-8")
    if body is not None and len(body) > MAX_REQUEST_BYTES:
        raise ReportingError("snapshot_too_large")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"FPVS-Toolbox/{APP_VERSION}",
    }
    if token:
        CredentialStore._validate(token)
        headers["Authorization"] = f"Bearer {token}"
    request = Request(ORIGIN + route, data=body, headers=headers, method="GET" if receipt_route else "POST")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        code = {
            400: "invalid_snapshot",
            401: "authorization_required",
            403: "approval_required",
            409: "snapshot_parent_conflict",
            429: "capacity_or_rate_limit",
        }.get(error.code, "delivery_unavailable")
        try:
            if error.code == 409:
                try:
                    reason = json.loads(error.read(2049))
                except (ValueError, UnicodeError):
                    reason = {}
                if isinstance(reason, dict) and reason.get("error") == "roster_revision_conflict":
                    code = "roster_revision_conflict"
        finally:
            error.close()
        raise ReportingError(code) from None
    except (URLError, OSError, TimeoutError):
        raise ReportingError("delivery_unavailable") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ReportingError("invalid_response")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ReportingError("invalid_response") from None
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ReportingError("invalid_response")
    return value


def enroll(project_root: Path, scope: dict[str, str], code: str, *, store=None, transport=request_json) -> dict:
    credentials = store if store is not None else CredentialStore(project_root, scope)
    with project_manifest_transaction(state_path(project_root)):
        saved = read_state(project_root).get("scope")
        if saved and saved != scope:
            raise ValueError("This project is already connected to another study.")
        token = credentials.load()
        if not token:
            token = secrets.token_hex(32)
            credentials.save(token)
    response = transport("/analysis/v1/enroll", {**scope, "code": code, "device_token": token})
    if (
        response.get("schema_version") != "1.0"
        or response.get("study_id") != scope["study_id"]
        or response.get("approval_status") not in {"pending", "approved"}
        or not isinstance(response.get("upload_enabled"), bool)
    ):
        raise ReportingError("invalid_response")
    save_scope(project_root, scope, response)
    return response


def deliver_pending(project_root: Path, *, store=None, transport=request_json, retry=False) -> str:
    state = read_state(project_root)
    if not state["pending"]:
        return "no_pending"
    scope = state.get("scope")
    if not scope:
        return "connection_required"
    credentials = store if store is not None else CredentialStore(project_root, scope)
    token = credentials.load()
    if not token:
        return "connection_required"
    # Sequential parents and a two-request bound preserve responsiveness/offline results.
    for item in state["pending"][:2]:
        if item["attempts"] >= MAX_ATTEMPTS and not retry:
            return "retry_required"
        identifier = item["snapshot_id"]
        payload = load_snapshot(project_root, identifier)
        manifest = payload["manifest"]
        if any(manifest.get(key) != scope[key] for key in scope):
            raise ReportingError("snapshot_scope_conflict")
        try:
            response = transport("/analysis/v1/snapshots", payload, token)
            if (
                response.get("schema_version") != "1.0"
                or any(
                    response.get(key) != manifest[key]
                    for key in ("study_id", "dataset_id", "snapshot_id", "snapshot_sha256")
                )
                or response.get("status") not in {"accepted", "superseded"}
            ):
                raise ReportingError("invalid_response")
        except ReportingError as error:
            record_delivery(project_root, identifier, accepted=False, status=error.code)
            return error.code
        record_delivery(project_root, identifier, accepted=True, status="accepted")
    return "pending" if read_state(project_root)["pending"] else "delivered"
