"""Anonymous, bounded OpenFPVS dataset catalog and transport contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import re
from threading import Event
import time
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from packaging.version import InvalidVersion, Version

from Main_App.updates.application import APP_VERSION

DEFAULT_ORIGIN = "https://openfpvs.com"
PROJECT_FORMAT = "fpvs-toolbox-project-v1"
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_EXTRACTED_BYTES = 4 * 1024**3
MAX_FILE_COUNT = 4096
CHUNK_SIZE = 1024 * 1024
SOCKET_TIMEOUT_SECONDS = 8
DOWNLOAD_TIMEOUT_SECONDS = 30 * 60
_CATALOG_MAX_BYTES = 1024 * 1024
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class LibraryError(RuntimeError):
    """A public dataset could not be listed, verified, or installed."""


class LibraryCancelled(LibraryError):
    """The current operation was canceled before publication."""


def check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise LibraryCancelled("The dataset download was canceled.")


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LibraryError(f"OpenFPVS returned an invalid dataset {name}.")
    if any(ord(character) < 32 for character in value):
        raise LibraryError(f"OpenFPVS returned an invalid dataset {name}.")
    return value


def _integer(value: object, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise LibraryError(f"OpenFPVS returned an invalid dataset {name}.")
    return value


@dataclass(frozen=True)
class PublicDataset:
    item_id: str
    version: str
    title: str
    description: str
    filename: str
    size_bytes: int
    uncompressed_size_bytes: int
    file_count: int
    sha256: str
    min_toolbox_version: str
    project_format: str
    participant_count: int
    condition_count: int
    sample_rate_hz: int
    kind: str = "dataset"

    @classmethod
    def from_dict(cls, data: object) -> PublicDataset:
        if not isinstance(data, Mapping) or set(data) != set(cls.__dataclass_fields__):
            raise LibraryError("OpenFPVS returned an invalid public dataset record.")
        item_id = _text(data["item_id"], "ID", 80)
        version = _text(data["version"], "version", 64)
        digest = _text(data["sha256"], "checksum", 64)
        filename = _text(data["filename"], "filename", 160)
        minimum = _text(data["min_toolbox_version"], "minimum version", 64)
        if not _ID.fullmatch(item_id) or not _VERSION.fullmatch(version) or not _DIGEST.fullmatch(digest):
            raise LibraryError("OpenFPVS returned an invalid dataset identity or checksum.")
        if filename != f"{item_id}-{version}.zip":
            raise LibraryError("OpenFPVS returned a filename that does not match the dataset version.")
        if data["kind"] != "dataset" or data["project_format"] != PROJECT_FORMAT:
            raise LibraryError("This dataset uses an unsupported Toolbox project format.")
        try:
            Version(minimum)
        except InvalidVersion as error:
            raise LibraryError("OpenFPVS returned an invalid minimum Toolbox version.") from error
        return cls(
            item_id=item_id, version=version,
            title=_text(data["title"], "title", 200),
            description=_text(data["description"], "description", 1000),
            filename=filename,
            size_bytes=_integer(data["size_bytes"], "download size", MAX_ARCHIVE_BYTES),
            uncompressed_size_bytes=_integer(data["uncompressed_size_bytes"], "disk size", MAX_EXTRACTED_BYTES),
            file_count=_integer(data["file_count"], "file count", MAX_FILE_COUNT),
            sha256=digest, min_toolbox_version=minimum, project_format=PROJECT_FORMAT,
            participant_count=_integer(data["participant_count"], "participant count", 10000),
            condition_count=_integer(data["condition_count"], "condition count", 1000),
            sample_rate_hz=_integer(data["sample_rate_hz"], "sample rate", 100000),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def require_compatible(self) -> None:
        if Version(APP_VERSION) < Version(self.min_toolbox_version):
            raise LibraryError(f"This dataset requires FPVS Toolbox {self.min_toolbox_version} or later.")


def service_url(origin: str, path: str) -> str:
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise LibraryError("The public Library requires an HTTPS OpenFPVS origin.")
    return origin.rstrip("/") + path


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LibraryError("OpenFPVS redirected the public dataset request. Try again later.")


@contextmanager
def public_response(url: str, *, accept: str) -> Iterator[BinaryIO]:
    request = Request(url, headers={
        "User-Agent": f"FPVS-Toolbox/{APP_VERSION}", "Accept": accept, "Accept-Encoding": "identity",
    })
    try:
        response = build_opener(_NoRedirects()).open(request, timeout=SOCKET_TIMEOUT_SECONDS)
    except HTTPError as error:
        raise LibraryError(f"OpenFPVS could not provide this dataset (HTTP {error.code}).") from error
    except (URLError, TimeoutError, OSError) as error:
        raise LibraryError("Could not reach the public OpenFPVS Library. Check your connection and retry.") from error
    with response:
        if response.geturl() != url:
            raise LibraryError("The public dataset response came from an unexpected address.")
        encoding = response.headers.get("Content-Encoding", "identity")
        if encoding.lower() != "identity":
            raise LibraryError("OpenFPVS returned an unsupported dataset transfer encoding.")
        yield response


def response_chunks(response: BinaryIO, *, cancel_event: Event | None, timeout: int) -> Iterator[bytes]:
    started = time.monotonic()
    read = getattr(response, "read1", response.read)
    while True:
        check_cancel(cancel_event)
        if time.monotonic() - started > timeout:
            raise LibraryError("The public Library operation exceeded its time limit. Retry the download.")
        try:
            chunk = read(CHUNK_SIZE)
        except (OSError, TimeoutError) as error:
            raise LibraryError("The public Library transfer was interrupted. Retry the download.") from error
        check_cancel(cancel_event)
        if not chunk:
            break
        yield chunk


def list_public_datasets(*, origin: str = DEFAULT_ORIGIN, cancel_event: Event | None = None) -> tuple[PublicDataset, ...]:
    """Read the public-only catalog without account, lab, or device credentials."""
    check_cancel(cancel_event)
    url = service_url(origin, "/public-library/v1/catalog?kind=dataset")
    payload = bytearray()
    with public_response(url, accept="application/json") as response:
        for chunk in response_chunks(response, cancel_event=cancel_event, timeout=30):
            if len(payload) + len(chunk) > _CATALOG_MAX_BYTES:
                raise LibraryError("The public dataset catalog exceeds its size limit.")
            payload.extend(chunk)
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError) as error:
        raise LibraryError("OpenFPVS returned an unreadable dataset catalog.") from error
    if (not isinstance(data, dict) or set(data) != {"schema_version", "library_name", "items", "access_level"}
            or data["schema_version"] != "1.0" or data["access_level"] != "download"
            or not isinstance(data["items"], list) or len(data["items"]) > 100):
        raise LibraryError("OpenFPVS returned an unsupported public dataset catalog.")
    _text(data["library_name"], "Library name", 200)
    items = tuple(PublicDataset.from_dict(item) for item in data["items"])
    if len({(item.item_id, item.version) for item in items}) != len(items):
        raise LibraryError("OpenFPVS returned duplicate public dataset versions.")
    return items
