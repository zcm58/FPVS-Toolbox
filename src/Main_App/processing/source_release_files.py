"""Recheck the files attested by an already validated native QC-20 release."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from Main_App.io.result_manifest import RESULT_MANIFEST_VERSION, is_result_manifest, read_result_manifest
from Main_App.processing.recording_condition_outcomes import (
    CELL_EXCLUDED, CELL_PARTIALLY_RETAINED, CELL_READY, CELL_UNAVAILABLE, RecordingConditionOutcomeLedger,
)


def _regular_stat(path: Path) -> os.stat_result:
    if str(path.resolve(strict=True)) != str(path):
        raise ValueError("Release input has an indirect path.")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Release input must be a regular file.")
    return info


@dataclass(frozen=True, slots=True)
class _ReleasedFile:
    path: Path
    size: int
    sha256: str
    mtime_ns: int | None
    physical_id: tuple[int, int]

    @classmethod
    def from_receipt(cls, path: Path, size: int, sha256: str, mtime_ns: int | None = None) -> _ReleasedFile:
        if type(size) is not int or size <= 0 or not isinstance(sha256, str) or not re.fullmatch("[0-9a-f]{64}", sha256):
            raise ValueError("Invalid release file receipt.")
        info = _regular_stat(path)
        if not info.st_ino or info.st_size != size or (mtime_ns is not None and info.st_mtime_ns != mtime_ns):
            raise ValueError("Release file does not match its receipt.")
        return cls(path, size, sha256, mtime_ns, (info.st_dev, info.st_ino))

    def current(self) -> bool:
        try:
            before = _regular_stat(self.path)
            if ((before.st_dev, before.st_ino) != self.physical_id or before.st_size != self.size
                    or (self.mtime_ns is not None and before.st_mtime_ns != self.mtime_ns)):
                return False
            with self.path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if not os.path.samestat(before, opened) or opened.st_size != self.size:
                    return False
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                finished = os.fstat(stream.fileno())
            after = _regular_stat(self.path)
            return (
                digest == self.sha256 and os.path.samestat(before, after)
                and before.st_size == after.st_size == finished.st_size
                and before.st_mtime_ns == opened.st_mtime_ns == finished.st_mtime_ns == after.st_mtime_ns
                # Compare like stat sources. Windows lstat and fstat may report different ctime semantics.
                and opened.st_ctime_ns == finished.st_ctime_ns and before.st_ctime_ns == after.st_ctime_ns
            )
        except (OSError, ValueError, RuntimeError):
            return False


@dataclass(frozen=True, slots=True)
class NativeReleaseFiles:
    _anchors: tuple[_ReleasedFile, ...]
    _companions: tuple[_ReleasedFile, ...]

    @property
    def anchors(self) -> frozenset[Path]:
        return frozenset(file.path for file in self._anchors)

    @property
    def companion_paths(self) -> tuple[Path, ...]:
        return tuple(file.path for file in self._companions)

    @classmethod
    def from_outcomes(
        cls, outcomes: RecordingConditionOutcomeLedger, *, project_root: Path,
    ) -> NativeReleaseFiles | None:
        """Build from the release receipts. Unsupported layouts take the ordinary validation path."""
        anchors: list[_ReleasedFile] = []
        companions: list[_ReleasedFile] = []
        try:
            root = Path(project_root).resolve(strict=True)
            for cell in outcomes.cells:
                if cell.status in (CELL_EXCLUDED, CELL_UNAVAILABLE):
                    continue
                if cell.status not in (CELL_READY, CELL_PARTIALLY_RETAINED):
                    return None
                export = cell.export_receipt
                if not isinstance(export, Mapping):
                    return None
                written = export["workbook_write"]
                if written["version"] != "workbook_write_receipt_v1" or written["status"] != "written":
                    return None
                schema = written["schema_validation"]
                if schema["status"] != "passed" or schema["format"] != RESULT_MANIFEST_VERSION:
                    return None
                artifact = written["artifact"]
                anchor = Path(export["path"])
                if (not is_result_manifest(anchor) or not anchor.is_absolute() or not anchor.is_relative_to(root)
                        or str(anchor) != export["path"] or ":" in anchor.name
                        or export["path"] != written["path"] or export["path"] != artifact["path"]
                        or type(artifact["mtime_ns"]) is not int):
                    return None
                anchors.append(_ReleasedFile.from_receipt(
                    anchor, artifact["size"], artifact["sha256"], artifact["mtime_ns"],
                ))
                # The native reader validates versions, allowed sheets and safe sibling basenames.
                declaration = read_result_manifest(anchor)
                if declaration["sheet_names"] != schema["sheet_names"]:
                    return None
                for key in ("spectral_companion", "condition_companion"):
                    descriptor = declaration[key]
                    if descriptor is None or descriptor != written[key]:
                        return None
                    companions.append(_ReleasedFile.from_receipt(
                        anchor.parent / descriptor["path"], descriptor["size_bytes"], descriptor["sha256"],
                    ))
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            return None
        files = (*anchors, *companions)
        if not anchors or len({file.physical_id for file in files}) != len(files):
            return None
        return cls(tuple(anchors), tuple(companions))

    def current(self, max_workers: int) -> bool:
        """Verify exact receipt bytes using the caller's RAM-tier worker ceiling."""
        files = (*self._anchors, *self._companions)
        if not files:
            return False
        workers = min(max(1, max_workers), len(files))
        if workers <= 1:
            return all(file.current() for file in files)
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                return all(pool.map(_ReleasedFile.current, files))
        except (OSError, RuntimeError):
            # A thread-limited host can still perform the same byte checks.
            return all(file.current() for file in files)
