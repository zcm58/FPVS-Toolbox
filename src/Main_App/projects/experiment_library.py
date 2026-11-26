"""Verify and install portable public datasets through project-owned I/O."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tempfile
from threading import Event
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from Main_App.io.atomic_write import atomic_write, rename_with_retry, replace_with_retry
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
_RECORDING_PATH_VALIDATION = "packaged_bdf_v1"
_JSON_LIMIT = 2 * 1024 * 1024
_DATA_SUFFIXES = {".bdf", ".json", ".csv", ".tsv", ".md", ".txt", ".png", ".pdf", ".xlsx", ".cff"}
_RELEASE_IDENTITY = (
    "item_id", "version", "filename", "size_bytes", "uncompressed_size_bytes", "file_count",
    "sha256", "project_format", "participant_count", "condition_count", "sample_rate_hz",
)
ProgressCallback = Callable[[int, int], None]
PhaseCallback = Callable[[str], None]
logger = logging.getLogger(__name__)


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
    except (ValueError, UnicodeError, RecursionError) as error:
        raise LibraryError(f"The dataset {label} is unreadable.") from error
    if not isinstance(value, dict):
        raise LibraryError(f"The dataset {label} must contain a JSON object.")
    return value


def _read_local_json(path: Path, label: str, expected: os.stat_result) -> dict:
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not os.path.samestat(opened, expected):
            raise LibraryError(f"The dataset {label} changed while opening.")
        if opened.st_size > _JSON_LIMIT:
            raise LibraryError(f"The dataset {label} exceeds its size limit.")
        data = stream.read(opened.st_size + 1)
        if len(data) != opened.st_size:
            raise LibraryError(f"The dataset {label} changed while reading.")
        return _json(data, label)


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
    _validate_recording_paths(document, files)


def _validate_recording_paths(document: Mapping, files: Collection[str], *, installed_root: Path | None = None) -> None:
    def recording_path(value, *, allow_root=False):
        if installed_root is None:
            return _portable_path(value, allow_root=allow_root)
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise LibraryError("The installed recording path is invalid.")
        # A local save uses native separators and may contain an absolute path.
        # Reject an outside path lexically before resolving any links.
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(installed_root)
            except ValueError as error:
                raise LibraryError("A recording path leaves the installed dataset.") from error
        name = _portable_path(path.as_posix(), allow_root=allow_root)
        if name.startswith("~") or not (installed_root / path).resolve().is_relative_to(installed_root):
            raise LibraryError("A recording path leaves the installed dataset.")
        return name

    sources = document.get("recording_sources", {})
    recordings = document.get("recordings", {})
    if sources is None:
        sources = {}
    if recordings is None:
        recordings = {}
    if not isinstance(sources, dict) or not isinstance(recordings, dict):
        raise LibraryError("The dataset's recording sources or recording metadata are invalid.")
    if sources:
        bdf_directories = {
            str(parent) for name in files if name.lower().endswith(".bdf")
            for parent in PurePosixPath(name).parents
        }
        for source in sources.values():
            if not isinstance(source, dict):
                raise LibraryError("The dataset contains invalid recording source metadata.")
            folder = recording_path(source.get("raw_input_folder"), allow_root=True)
            if folder.startswith("~") or folder not in bdf_directories:
                raise LibraryError("A dataset recording source must refer to a folder of packaged BDF files.")
    for recording in recordings.values():
        if not isinstance(recording, dict):
            raise LibraryError("The dataset contains invalid recording metadata.")
        raw_file = recording_path(recording.get("raw_file"))
        if raw_file.startswith("~") or raw_file not in files or not raw_file.lower().endswith(".bdf"):
            raise LibraryError("A dataset recording must refer to a packaged BDF file.")


def _file_inventory(document: dict, item: PublicDataset, manifest_size: int) -> dict[str, DatasetFile]:
    if (set(document) != {"schema_version", "item_id", "version", "project_file", "files"}
            or document["schema_version"] != "1.0" or document["item_id"] != item.item_id
            or document["version"] != item.version or document["project_file"] != "project.json"
            or not isinstance(document["files"], list) or len(document["files"]) != item.file_count - 1):
        raise LibraryError("The dataset file manifest does not match the selected release.")
    expected: dict[str, DatasetFile] = {}
    seen = {_MANIFEST.casefold(), _RECEIPT.casefold()}
    for row in document["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "size_bytes", "sha256"}:
            raise LibraryError("The dataset file manifest contains an invalid entry.")
        name = _portable_path(row["path"])
        if name.casefold() in seen:
            raise LibraryError("The dataset file manifest contains duplicate or reserved paths.")
        seen.add(name.casefold())
        if type(row["size_bytes"]) is not int or row["size_bytes"] < 0:
            raise LibraryError("The dataset file manifest contains an invalid file size.")
        checksum = row["sha256"]
        if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise LibraryError("The dataset file manifest contains an invalid checksum.")
        expected[name] = DatasetFile(name, row["size_bytes"], checksum)
    if "project.json" not in expected or sum(row.size_bytes for row in expected.values()) + manifest_size != item.uncompressed_size_bytes:
        raise LibraryError("The dataset file manifest does not cover the complete archive.")
    return expected


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
            expected = _file_inventory(_json(manifest_bytes, "file manifest"), item, len(manifest_bytes))
            if set(expected) != set(files) - {_MANIFEST}:
                raise LibraryError("The dataset file manifest does not cover the complete archive.")
            for name, row in expected.items():
                if row.size_bytes != files[name].file_size:
                    raise LibraryError("A dataset file size differs from its file manifest.")
                digest = hashlib.sha256()
                with zipped.open(name) as source:
                    while chunk := source.read(CHUNK_SIZE):
                        check_cancel(cancel_event)
                        digest.update(chunk)
                if digest.hexdigest() != row.sha256:
                    raise LibraryError(f"Dataset file verification failed for {name}.")
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


def _installed_document(path: Path, label: str) -> dict:
    info = regular_file_info(path)
    if info is None:
        raise LibraryError(f"The existing dataset installation is missing its {label}.")
    return _read_local_json(path, label, info)


def _receipt_release(saved: dict) -> PublicDataset:
    item = PublicDataset.from_dict(saved.get("dataset"))
    if saved.get("schema_version") != "1.0":
        raise LibraryError("The Library installation receipt uses an unsupported format.")
    return item


def _check_legacy_recordings(
    target: Path, saved: dict, manifest_path: Path, manifest: Mapping | None,
) -> Mapping | None:
    if saved.get("recording_path_validation") == _RECORDING_PATH_VALIDATION:
        return manifest
    # Protect the current on-disk manifest even when the caller also supplied
    # a draft or alternate manifest. Only the receipt is modified.
    project = target / "project.json"
    receipt = target / _RECEIPT
    with project_manifest_transaction(project):
        saved = _installed_document(receipt, "installation receipt")
        item = _receipt_release(saved)
        if saved.get("recording_path_validation") == _RECORDING_PATH_VALIDATION:
            return manifest
        inventory = target / _MANIFEST
        info = regular_file_info(inventory)
        if info is None:
            raise LibraryError("The old Library project requires its original dataset-manifest.json to reopen.")
        files = _file_inventory(_read_local_json(inventory, "file manifest", info), item, info.st_size)
        current = _installed_document(project, "project manifest")
        try:
            _validate_recording_paths(current, files, installed_root=target)
            if manifest is None and manifest_path != project:
                manifest = _installed_document(manifest_path, "project manifest")
            if manifest is not None:
                if not isinstance(manifest, Mapping):
                    raise LibraryError("The project manifest must contain a JSON object.")
                _validate_recording_paths(manifest, files, installed_root=target)
        except LibraryError as error:
            raise LibraryError(
                f"{error} Keep a backup of this project. In project.json, use the BDF paths listed "
                "in dataset-manifest.json and their folders. Reopen the project, then register any "
                "trusted external recordings again."
            ) from error
        saved["recording_path_validation"] = _RECORDING_PATH_VALIDATION
        with atomic_write(receipt, replace=replace_with_retry) as stream:
            json.dump(saved, stream, indent=2)
        return current if manifest is None else manifest


def checked_library_project_manifest(target: Path, manifest_path: Path, manifest: Mapping | None) -> Mapping | None:
    """Admit an older public installation before the project model resolves external paths."""
    saved = _installed_document(target / _RECEIPT, "installation receipt")
    _receipt_release(saved)
    return _check_legacy_recordings(target, saved, manifest_path, manifest)


def _installed_release(target: Path) -> PublicDataset | None:
    receipt = target / _RECEIPT
    info = regular_file_info(receipt)
    if info is None:
        return None
    saved = _read_local_json(receipt, "installation receipt", info)
    item = _receipt_release(saved)
    if target.with_name(f"{item.item_id}-{item.version}") != target:
        raise LibraryError("The folder name differs from the installed dataset identity.")
    project = target / "project.json"
    if _check_legacy_recordings(target, saved, project, None) is None:
        _installed_document(project, "project manifest")
    return item


def installed_dataset_path(item: PublicDataset, projects_root: Path) -> Path | None:
    """Resolve a completed installation without rehashing editable project files."""
    item = PublicDataset.from_dict(item.to_dict())
    target = _installation_root(item, projects_root)
    if not target.exists() and not target.is_symlink():
        return None
    info = target.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise LibraryError("The existing dataset project folder is linked or invalid.")
    saved_item = _installed_release(target)
    if saved_item is None:
        raise LibraryError(f"The existing project folder {target.name} is not a completed Library installation.")
    if any(getattr(saved_item, key) != getattr(item, key) for key in _RELEASE_IDENTITY):
        raise LibraryError("The existing dataset installation does not match this public release.")
    return target


def list_installed_datasets(
    projects_root: Path, *, on_notice: Callable[[str], None] | None = None,
) -> tuple[PublicDataset, ...]:
    """Discover completed local releases independently of online availability."""
    root = Path(projects_root).resolve()
    if not root.is_dir():
        return ()
    items: list[PublicDataset] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        try:
            info = child.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                continue
            item = _installed_release(child)
            if item is not None:
                items.append(item)
        except (LibraryError, OSError) as error:
            logger.warning("library_installation_unreadable", extra={"folder": child.name, "reason": str(error)})
            if on_notice is not None:
                on_notice(f"Cannot reopen {child.name}. {error}")
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
            receipt = {
                "schema_version": "1.0", "dataset": item.to_dict(), "origin": origin,
                "recording_path_validation": _RECORDING_PATH_VALIDATION,
            }
            (content / _RECEIPT).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            check_cancel(cancel_event)
            if target.exists() or target.is_symlink():
                raise LibraryError("The dataset destination appeared during setup. Reopen the Library and retry.")
            rename_with_retry(content, target)
            return target
