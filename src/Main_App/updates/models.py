"""Typed contracts for the FPVS Toolbox installer update workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version


class UpdateError(RuntimeError):
    """Raised when release metadata, downloads, or installer launch cannot proceed."""


@dataclass(frozen=True)
class InstallerAsset:
    """GitHub Release asset selected as the Windows installer."""

    name: str
    download_url: str
    size_bytes: int | None


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
    metadata_incomplete: bool = False

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
class CandidateRelease:
    """Normalized GitHub Release metadata used during selection."""

    version: Version
    tag_name: str
    release_url: str | None
    body: str
    installer_asset: InstallerAsset | None
    is_prerelease: bool


@dataclass(frozen=True)
class DownloadedInstaller:
    """Local installer file ready for explicit user-approved execution."""

    path: Path
    size_bytes: int
