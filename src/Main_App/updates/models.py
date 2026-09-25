"""Typed contracts for the FPVS Toolbox update workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version


class UpdateError(RuntimeError):
    """Raised when release metadata, downloads, or installer launch cannot proceed."""


class UpdateCancelled(UpdateError):
    """Updater work was canceled before committing an installer launch."""


class UpdateCacheBusy(UpdateError):
    """Another process owns the update cache; it is unsafe to change its files."""


class UpdateIntegrityError(UpdateError):
    """An installer or its cache receipt does not match the selected release asset."""


def normalize_sha256(value: object) -> str | None:
    """Accept GitHub's digest format or a canonical SHA-256, never another algorithm."""

    if not isinstance(value, str):
        return None
    digest = value.removeprefix("sha256:").lower()
    return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None


@dataclass(frozen=True)
class InstallerAsset:
    """GitHub Release asset selected as the Windows installer."""

    name: str
    download_url: str
    size_bytes: int | None
    sha256: str | None = None
    version: str | None = None
    asset_id: int | None = None
    kind: str = "full"
    from_version: str | None = None
    source_inventory_sha256: str | None = None

    def __post_init__(self) -> None:
        # Keep an unverifiable release visible to the GUI, but disable its download.
        object.__setattr__(self, "sha256", normalize_sha256(self.sha256))


@dataclass(frozen=True)
class UpdateCheckResult:
    """Result shown by the GUI update dialog."""

    current_version: str
    latest_version: str
    update_available: bool
    release_url: str | None
    release_notes_summary: str
    installer_asset: InstallerAsset | None
    is_prerelease: bool
    selection_reason: str = ""
    metadata_incomplete: bool = False

    @property
    def download_kind(self) -> str:
        return "full" if self.installer_asset is None else self.installer_asset.kind

    @property
    def installer_asset_name(self) -> str | None:
        return None if self.installer_asset is None else self.installer_asset.name

    @property
    def installer_download_url(self) -> str | None:
        return None if self.installer_asset is None else self.installer_asset.download_url

    @property
    def installer_size_bytes(self) -> int | None:
        return None if self.installer_asset is None else self.installer_asset.size_bytes


@dataclass(frozen=True)
class UpdatePhase:
    """Worker status, optionally carrying discovered release details before hashing."""

    text: str
    result: UpdateCheckResult | None = None
    install_committed: bool = False
    target_version: str | None = None


@dataclass(frozen=True)
class CandidateRelease:
    """Normalized GitHub Release metadata used during selection."""

    version: Version
    tag_name: str
    release_url: str | None
    body: str
    installer_asset: InstallerAsset | None
    is_prerelease: bool
    assets: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class DownloadedInstaller:
    """Local installer file ready for explicit user-approved execution."""

    path: Path
    size_bytes: int
    sha256: str
    asset: InstallerAsset


@dataclass(frozen=True)
class CacheCleanupResult:
    """Best-effort startup housekeeping; warnings must never prevent app startup."""

    kept_installer: Path | None = None
    removed_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    busy: bool = False
