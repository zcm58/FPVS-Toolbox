"""Verify and install portable public datasets through project-owned I/O."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tempfile
from threading import Event
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from Main_App.io.atomic_write import rename_with_retry
from Main_App.io.safe_file import regular_file_info
from Main_App.projects.grouping import GroupConfigurationError, validate_group_folder_name
from Main_App.projects.manifest_store import project_manifest_transaction
from Main_App.projects.public_datasets import (
    CHUNK_SIZE,
    DEFAULT_ORIGIN,
    DOWNLOAD_TIMEOUT_SECONDS,
    LibraryCancelled as LibraryCancelled,
    LibraryError,
    PublicDataset,
    check_cancel,
    list_public_datasets as list_public_datasets,
    public_response,
    response_chunks,
    service_url,
)

_MANIFEST = "dataset-manifest.json"
_RECEIPT = ".openfpvs-dataset.json"
_JSON_LIMIT = 2 * 1024 * 1024
_DATA_SUFFIXES = {".bdf", ".json", ".csv", ".tsv", ".md", ".txt", ".png", ".pdf", ".xlsx", ".cff"}
_RELEASE_IDENTITY = (
    "item_id", "version", "filename", "size_bytes", "uncompressed_size_bytes", "file_count",
    "sha256", "project_format", "participant_count", "condition_count", "sample_rate_hz",
)
ProgressCallback = Callable[[int, int], None]
PhaseCallback = Callable[[str], None]


@dataclass(frozen=True)
class DatasetFile:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class DatasetManifest:
    project_file: str
    files: tuple[DatasetFile, ...]


def _portable_path(value: object, *, allow_root: bool = False) -> str:
    if allow_root and value == ".":
        return "."
    if not isinstance(value, str) or not value or len(value) > 220:
        raise LibraryError("The dataset contains an invalid portable path.")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if path.is_absolute() or windows.drive or windows.root or "\\" in value:
        raise LibraryError("The dataset contains an absolute or non-portable path.")
    try:
        for part in value.split("/"):
            if validate_group_folder_name(part) != part:
                raise LibraryError("The dataset contains an unsafe portable path.")
    except GroupConfigurationError as error:
        raise LibraryError("The dataset contains an unsafe portable path.") from error
    return value


def _json(data: bytes, label: str) -> dict:
    if len(data) > _JSON_LIMIT:
        raise LibraryError(f"The dataset {label} exceeds its size limit.")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise LibraryError(f"The dataset {label} is unreadable.") from error
    if not isinstance(value, dict):
        raise LibraryError(f"The dataset {label} must contain a JSON object.")
    return value


def _hash_file(path: Path, cancel_event: Event | None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            check_cancel(cancel_event)
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _archive_files(archive: ZipFile, item: PublicDataset) -> dict[str, ZipInfo]:
    entries: dict[str, ZipInfo] = {}
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename[:-1] if info.is_dir() else info.filename
        _portable_path(name)
        if info.orig_filename != info.filename or name.casefold() in seen:
            raise LibraryError("The dataset contains duplicate or invalid archive paths.")
        seen.add(name.casefold())
        mode = stat.S_IFMT(info.external_attr >> 16)
        if (mode not in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG) or info.external_attr & 0x400
                or info.flag_bits & 1 or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)):
            raise LibraryError("The dataset contains linked, encrypted, or unsupported files.")
        if not info.is_dir():
            if ((Path(name).suffix.lower() not in _DATA_SUFFIXES and name != "LICENSE") or name == _RECEIPT):
                raise LibraryError("The dataset contains a file outside the supported data-only formats.")
            entries[name] = info
    if (len(entries) != item.file_count
            or sum(info.file_size for info in entries.values()) != item.uncompressed_size_bytes):
        raise LibraryError("The dataset's extracted size or file count differs from its public record.")
    folded_files = {name.casefold() for name in entries}
    for name in entries:
        if any(str(parent).casefold() in folded_files for parent in PurePosixPath(name).parents):
            raise LibraryError("The dataset contains conflicting file and directory paths.")
    return entries


def _validate_project_paths(document: dict, files: Mapping[str, ZipInfo], item: PublicDataset) -> None:
    if document.get("schema_version") != "2.1.0":
        raise LibraryError("The dataset contains an unsupported Toolbox project schema.")
    for key in ("input_folder", "results_folder"):
        if key in document:
            _portable_path(document[key], allow_root=True)
    for path in document.get("subfolders", {}).values():
        _portable_path(path)
    groups = document.get("groups", {})
    participants = document.get("participants", {})
    if not isinstance(groups, dict) or not isinstance(participants, dict):
        raise LibraryError("The dataset's project participant or group metadata is invalid.")
    event_map = document.get("event_map")
    if (len(participants) != item.participant_count or not isinstance(event_map, dict)
            or len(event_map) != item.condition_count):
        raise LibraryError("The dataset's participant or condition count differs from its public record.")
    for group in groups.values():
        if not isinstance(group, dict):
            raise LibraryError("The dataset contains invalid project group metadata.")
        _portable_path(group.get("raw_input_folder"))
    for participant in participants.values():
        if not isinstance(participant, dict):
            raise LibraryError("The dataset contains invalid project participant metadata.")
        raw_file = _portable_path(participant.get("raw_file"))
        if raw_file not in files or Path(raw_file).suffix.lower() != ".bdf":
            raise LibraryError("A dataset participant references a missing BDF recording.")


def validate_dataset_archive(
    archive: Path,
    item: PublicDataset,
    *,
    cancel_event: Event | None = None,
) -> DatasetManifest:
    """Read-only validation shared by native installation and release signing."""
    check_cancel(cancel_event)
    item = PublicDataset.from_dict(item.to_dict())
    archive = Path(archive)
    info = regular_file_info(archive)
    if info is None or info.st_size != item.size_bytes:
        raise LibraryError("The dataset archive size differs from its public record.")
    if _hash_file(archive, cancel_event) != (item.size_bytes, item.sha256):
        raise LibraryError("The dataset archive checksum differs from its public record.")
    try:
        with ZipFile(archive) as zipped:
            files = _archive_files(zipped, item)
            if _MANIFEST not in files or files[_MANIFEST].file_size > _JSON_LIMIT:
                raise LibraryError("The dataset is missing its bounded file manifest.")
            manifest_bytes = zipped.read(_MANIFEST)
            document = _json(manifest_bytes, "file manifest")
            if (set(document) != {"schema_version", "item_id", "version", "project_file", "files"}
                    or document["schema_version"] != "1.0" or document["item_id"] != item.item_id
                    or document["version"] != item.version or document["project_file"] != "project.json"
                    or not isinstance(document["files"], list)):
                raise LibraryError("The dataset file manifest does not match the selected release.")
            expected: dict[str, DatasetFile] = {}
            for row in document["files"]:
                if not isinstance(row, dict) or set(row) != {"path", "size_bytes", "sha256"}:
                    raise LibraryError("The dataset file manifest contains an invalid entry.")
                name = _portable_path(row["path"])
                if name == _MANIFEST or name in expected or name not in files:
                    raise LibraryError("The dataset file manifest contains duplicate or missing files.")
                if type(row["size_bytes"]) is not int or row["size_bytes"] != files[name].file_size:
                    raise LibraryError("A dataset file size differs from its file manifest.")
                checksum = row["sha256"]
                if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
                    raise LibraryError("The dataset file manifest contains an invalid checksum.")
                digest = hashlib.sha256()
                with zipped.open(name) as source:
                    while chunk := source.read(CHUNK_SIZE):
                        check_cancel(cancel_event)
                        digest.update(chunk)
                if digest.hexdigest() != checksum:
                    raise LibraryError(f"Dataset file verification failed for {name}.")
                expected[name] = DatasetFile(name, row["size_bytes"], checksum)
            if set(expected) != set(files) - {_MANIFEST} or "project.json" not in expected:
                raise LibraryError("The dataset file manifest does not cover the complete archive.")
            if files["project.json"].file_size > _JSON_LIMIT:
                raise LibraryError("The dataset project manifest exceeds its size limit.")
            _validate_project_paths(_json(zipped.read("project.json"), "project manifest"), files, item)
            expected[_MANIFEST] = DatasetFile(_MANIFEST, len(manifest_bytes), hashlib.sha256(manifest_bytes).hexdigest())
            check_cancel(cancel_event)
            return DatasetManifest("project.json", tuple(expected.values()))
    except (BadZipFile, NotImplementedError, KeyError, TypeError, AttributeError) as error:
        raise LibraryError("The dataset archive or its manifests are invalid.") from error


def _installation_root(item: PublicDataset, projects_root: Path) -> Path:
    return Path(projects_root).resolve() / f"{item.item_id}-{item.version}"


def installed_dataset_path(item: PublicDataset, projects_root: Path) -> Path | None:
    """Resolve a completed installation without rehashing editable project files."""
    item = PublicDataset.from_dict(item.to_dict())
    target = _installation_root(item, projects_root)
    if not target.exists() and not target.is_symlink():
        return None
    info = target.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise LibraryError("The existing dataset project folder is linked or invalid.")
    receipt = target / _RECEIPT
    if regular_file_info(receipt) is None or receipt.stat().st_size > _JSON_LIMIT:
        raise LibraryError(f"The existing project folder {target.name} is not a completed Library installation.")
    saved = _json(receipt.read_bytes(), "installation receipt")
    saved_item = PublicDataset.from_dict(saved.get("dataset"))
    if (saved.get("schema_version") != "1.0"
            or any(getattr(saved_item, key) != getattr(item, key) for key in _RELEASE_IDENTITY)
            or regular_file_info(target / "project.json") is None):
        raise LibraryError("The existing dataset installation does not match this public release.")
    _json((target / "project.json").read_bytes(), "project manifest")
    return target


def list_installed_datasets(projects_root: Path) -> tuple[PublicDataset, ...]:
    """Discover completed local releases independently of online availability."""
    root = Path(projects_root).resolve()
    if not root.is_dir():
        return ()
    items: list[PublicDataset] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        info = child.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            continue
        receipt = child / _RECEIPT
        if regular_file_info(receipt) is None:
            continue
        if receipt.stat().st_size > _JSON_LIMIT:
            raise LibraryError(f"The Library receipt in {child.name} exceeds its size limit.")
        item = PublicDataset.from_dict(_json(receipt.read_bytes(), "installation receipt").get("dataset"))
        if installed_dataset_path(item, root) != child:
            raise LibraryError(f"The Library project in {child.name} has an unexpected folder name.")
        items.append(item)
    return tuple(items)


def _download(item: PublicDataset, archive: Path, origin: str, progress_callback: ProgressCallback | None, cancel_event: Event | None) -> None:
    check_cancel(cancel_event)
    url = service_url(origin, f"/public-library/v1/datasets/{item.item_id}/versions/{item.version}/download")
    with public_response(url, accept="application/zip") as response, archive.open("xb") as target:
        length = response.headers.get("Content-Length")
        if length is not None and length != str(item.size_bytes):
            raise LibraryError("The dataset transfer size differs from its public record.")
        total = 0
        for chunk in response_chunks(response, cancel_event=cancel_event, timeout=DOWNLOAD_TIMEOUT_SECONDS):
            total += len(chunk)
            if total > item.size_bytes:
                raise LibraryError("The dataset transfer exceeded its public download size.")
            if target.write(chunk) != len(chunk):
                raise OSError("The dataset download could not be written completely.")
            if progress_callback:
                progress_callback(total, item.size_bytes)
        if total != item.size_bytes:
            raise LibraryError("The dataset download ended before all files arrived. Retry the download.")


def _extract(archive: Path, manifest: DatasetManifest, target: Path, cancel_event: Event | None) -> None:
    with ZipFile(archive) as zipped:
        for entry in manifest.files:
            check_cancel(cancel_event)
            destination = target / entry.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with zipped.open(entry.path) as source, destination.open("xb") as output:
                while chunk := source.read(CHUNK_SIZE):
                    check_cancel(cancel_event)
                    size += len(chunk)
                    if size > entry.size_bytes or output.write(chunk) != len(chunk):
                        raise LibraryError("A dataset file changed during project setup.")
                    digest.update(chunk)
            if size != entry.size_bytes or digest.hexdigest() != entry.sha256:
                raise LibraryError("A dataset file changed during project setup.")


def install_public_dataset(
    item: PublicDataset,
    projects_root: Path,
    *,
    origin: str = DEFAULT_ORIGIN,
    progress_callback: ProgressCallback | None = None,
    phase_callback: PhaseCallback | None = None,
    cancel_event: Event | None = None,
) -> Path:
    """Download, validate and atomically publish a normal portable Toolbox project."""
    item = PublicDataset.from_dict(item.to_dict())
    item.require_compatible()
    check_cancel(cancel_event)
    root = Path(projects_root).resolve()
    if not root.is_dir():
        raise LibraryError("Choose an existing Toolbox Projects Root before downloading a dataset.")
    target = _installation_root(item, root)
    with project_manifest_transaction(root / f".{target.name}.installation"):
        check_cancel(cancel_event)
        existing = installed_dataset_path(item, root)
        if existing is not None:
            return existing
        with tempfile.TemporaryDirectory(prefix=f".{item.item_id}-", dir=root) as staging:
            stage = Path(staging)
            archive = stage / "download.zip"
            if phase_callback:
                phase_callback("download")
            _download(item, archive, origin, progress_callback, cancel_event)
            check_cancel(cancel_event)
            if phase_callback:
                phase_callback("verify")
            manifest = validate_dataset_archive(archive, item, cancel_event=cancel_event)
            if phase_callback:
                phase_callback("setup")
            content = stage / "project"
            content.mkdir()
            _extract(archive, manifest, content, cancel_event)
            # Load through the canonical model before publication. Its generated
            # project-relative result directories move with the staged project.
            from Main_App.projects import Project

            Project.load(content)
            receipt = {"schema_version": "1.0", "dataset": item.to_dict(), "origin": origin}
            (content / _RECEIPT).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            check_cancel(cancel_event)
            if target.exists() or target.is_symlink():
                raise LibraryError("The dataset destination appeared during setup. Reopen the Library and retry.")
            rename_with_retry(content, target)
            return target
