"""Bounded JSON-lines messages between Toolbox and its independent updater.

Pipes are private child-process handles. They carry release identities and status,
never commands, arbitrary download URLs, or authority to skip package validation.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import IO, Any

from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCheckResult,
    UpdateError,
    UpdatePhase,
)
from Main_App.updates.validation import parse_release_version, validate_asset_identity

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024


def encode_message(kind: str, **payload: Any) -> bytes:
    raw = (
        json.dumps(
            {"protocol": PROTOCOL_VERSION, "kind": kind, **payload},
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if len(raw) > MAX_MESSAGE_BYTES:
        raise UpdateError("The updater message exceeded its size limit.")
    return raw


def _unique_fields(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate updater message field")
        result[key] = value
    return result


def read_message(stream: IO[bytes]) -> dict[str, Any]:
    raw = stream.readline(MAX_MESSAGE_BYTES + 1)
    if not raw:
        raise EOFError("The updater connection closed.")
    if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
        raise UpdateError("The updater returned an oversized or incomplete message.")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeError, ValueError) as error:
        raise UpdateError("The updater returned an unreadable message.") from error
    if (
        not isinstance(value, dict)
        or type(value.get("protocol")) is not int
        or value["protocol"] != PROTOCOL_VERSION
        or not isinstance(value.get("kind"), str)
    ):
        raise UpdateError("The updater uses an unsupported message protocol.")
    return value


def write_message(stream: IO[bytes], kind: str, **payload: Any) -> None:
    raw = encode_message(kind, **payload)
    if stream.write(raw) != len(raw):
        raise UpdateError("The updater connection could not write a complete message.")
    stream.flush()


def asset_to_dict(asset: InstallerAsset) -> dict[str, Any]:
    return asdict(asset)


def asset_from_dict(value: Any) -> InstallerAsset:
    fields = set(InstallerAsset.__dataclass_fields__)
    if not isinstance(value, dict) or set(value) != fields:
        raise UpdateError("The updater asset has an invalid schema.")
    if (
        not isinstance(value["name"], str)
        or not isinstance(value["download_url"], str)
        or value["kind"] not in {"full", "patch"}
        or any(
            value[field] is not None and not isinstance(value[field], str)
            for field in ("sha256", "version", "from_version", "source_inventory_sha256")
        )
        or any(value[field] is not None and type(value[field]) is not int for field in ("size_bytes", "asset_id"))
    ):
        raise UpdateError("The updater asset contains invalid values.")
    asset = InstallerAsset(**value)
    validate_asset_identity(asset, require_digest=False)
    return asset


def result_to_dict(result: UpdateCheckResult) -> dict[str, Any]:
    return asdict(result)


def result_from_dict(value: Any) -> UpdateCheckResult:
    if not isinstance(value, dict) or set(value) != set(UpdateCheckResult.__dataclass_fields__):
        raise UpdateError("The updater result has an invalid schema.")
    for field in ("current_version", "latest_version", "release_notes_summary", "selection_reason"):
        if not isinstance(value[field], str):
            raise UpdateError("The updater result contains invalid text.")
    for field in ("update_available", "is_prerelease"):
        if type(value[field]) is not bool:
            raise UpdateError("The updater result contains an invalid state.")
    if value["release_url"] is not None and not isinstance(value["release_url"], str):
        raise UpdateError("The updater release link is invalid.")
    parse_release_version(value["current_version"])
    parse_release_version(value["latest_version"])
    return UpdateCheckResult(
        **{
            **value,
            "installer_asset": asset_from_dict(value["installer_asset"])
            if value["installer_asset"] is not None
            else None,
        }
    )


def download_to_dict(downloaded: DownloadedInstaller) -> dict[str, Any]:
    return {
        "path": str(downloaded.path),
        "size_bytes": downloaded.size_bytes,
        "sha256": downloaded.sha256,
        "asset": asset_to_dict(downloaded.asset),
    }


def download_from_dict(value: Any) -> DownloadedInstaller:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "size_bytes", "sha256", "asset"}
        or not isinstance(value["path"], str)
        or type(value["size_bytes"]) is not int
        or not isinstance(value["sha256"], str)
    ):
        raise UpdateError("The updater download has an invalid schema.")
    asset = asset_from_dict(value["asset"])
    validate_asset_identity(asset)
    if value["size_bytes"] != asset.size_bytes or value["sha256"] != asset.sha256:
        raise UpdateError("The updater download differs from its release identity.")
    path = Path(value["path"])
    if not path.is_absolute() or path.name != asset.name:
        raise UpdateError("The updater download path does not match its asset.")
    return DownloadedInstaller(path, value["size_bytes"], value["sha256"], asset)


def phase_from_message(message: dict[str, Any]) -> UpdatePhase:
    if not isinstance(message.get("text"), str) or type(message.get("install_committed", False)) is not bool:
        raise UpdateError("The updater returned an invalid status.")
    return UpdatePhase(
        message["text"],
        result_from_dict(message["result"]) if message.get("result") is not None else None,
        install_committed=message.get("install_committed", False),
    )
