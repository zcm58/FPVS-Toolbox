"""Transport for the approved automatic crash reporting origin."""

from __future__ import annotations

import hashlib
import json
import ssl
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

ORIGIN = "https://reports.zack-murphy.com"
MAX_ENVELOPE = 32 * 1024


def encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CrashClient:
    def __init__(self) -> None:
        self._opener = build_opener(_RejectRedirects(), HTTPSHandler(context=ssl.create_default_context()))

    def _request(self, path: str, token: str, body: bytes | None = None, *, installation: str = "") -> dict:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "FPVS-Toolbox/1.0",
        }
        if body is not None:
            if len(body) > MAX_ENVELOPE:
                return {}
            headers["Content-Type"] = "application/json"
        if installation:
            headers["X-Installation-ID"] = installation
        try:
            with self._opener.open(Request(ORIGIN + path, data=body, headers=headers), timeout=5) as response:
                raw = response.read(16 * 1024 + 1)
                if len(raw) > 16 * 1024:
                    return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except HTTPError as error:
            error.close()
        except (URLError, OSError, HTTPException, ValueError, RecursionError):
            pass
        return {}

    def register(self, installation: str, token: str) -> int:
        result = self._request(
            "/v1/crash-installations", token,
            encode({"schema_version": "1", "installation_id": installation}),
        )
        if result.get("installation_id") != installation or result.get("state") != "registered":
            return 0
        expires = result.get("expires_at")
        return expires if type(expires) is int and 0 < expires < 2**63 else 0

    def revoke(self, installation: str, token: str) -> bool:
        result = self._request(f"/v1/crash-installations/{installation}/revoke", token, b"{}")
        return result.get("installation_id") == installation and result.get("state") == "revoked"

    def accepted(self, report_id: str, receipt: str) -> bool:
        return self._confirmed(self._request(f"/v1/reports/{report_id}/status", receipt), report_id)

    def send(self, installation: str, token: str, report: bytes, receipt: str, report_id: str) -> bool:
        # The report has already been encoded and committed locally. Reuse those exact bytes.
        digest = hashlib.sha256(receipt.encode("ascii")).hexdigest().encode("ascii")
        envelope = b'{"receipt_token_sha256":"' + digest + b'","report":' + report + b"}"
        result = self._request("/v1/crash-reports", token, envelope, installation=installation)
        return self._confirmed(result, report_id)

    @staticmethod
    def _confirmed(result: dict, report_id: str) -> bool:
        return result.get("report_id") == report_id and result.get("state") in ("received", "submitted")
