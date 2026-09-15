"""Shared release identity rules for downloads, offline receipts, and launch."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlparse

from packaging.version import InvalidVersion, Version

from Main_App.updates.models import InstallerAsset, UpdateError, normalize_sha256
from Main_App.updates.application import RELEASE_REPOSITORY

INSTALLER_ASSET_PATTERN = re.compile(
    r"FPVSToolbox-(?P<version>[0-9][A-Za-z0-9.+_-]*)-setup\.exe", re.IGNORECASE | re.ASCII
)
PATCH_ASSET_PATTERN = re.compile(
    r"FPVSToolbox-Patch-(?P<source>[0-9][A-Za-z0-9.+_-]*?)-to-"
    r"(?P<version>[0-9][A-Za-z0-9.+_-]*)\.exe",
    re.ASCII,
)
# Toolbox has no authenticated historical filename aliases.
_PUBLISHED_FILENAME_ALIASES: dict[Version, Version] = {}
MAX_INSTALLER_SIZE_BYTES = 4 * 1024 * 1024 * 1024
_LOG = logging.getLogger(__name__)


def parse_release_version(tag_name: str) -> Version:
    """Parse the application's published tag spellings into a comparable version."""

    if len(tag_name) > 200:
        raise UpdateError("The release version is too long.")
    normalized = tag_name.strip().removeprefix("v").removeprefix("V").strip()
    normalized = re.sub(r"[-_]?beta[.-]?(\d+)$", r"b\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?beta$", "b0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?alpha[.-]?(\d+)$", r"a\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?alpha$", "a0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?rc[.-]?(\d+)$", r"rc\1", normalized, flags=re.IGNORECASE)
    try:
        return Version(normalized)
    except InvalidVersion as error:
        raise UpdateError(f"Release tag '{tag_name}' is not a supported version.") from error


def installer_filename_version(name: str) -> Version | None:
    """Recognize only a single, versioned installer basename, not a path or stream."""

    match = INSTALLER_ASSET_PATTERN.fullmatch(name) or PATCH_ASSET_PATTERN.fullmatch(name)
    if match is None or len(name) > 200:
        return None
    try:
        if "source" in match.groupdict():
            if parse_release_version(match.group("source")) >= parse_release_version(match.group("version")):
                return None
        return parse_release_version(match.group("version"))
    except UpdateError:
        return None


def installer_matches_version(name: str, version: Version) -> bool:
    filename_version = installer_filename_version(name)
    return filename_version is not None and (
        filename_version == version
        or (
            INSTALLER_ASSET_PATTERN.fullmatch(name) is not None
            and filename_version == _PUBLISHED_FILENAME_ALIASES.get(version)
        )
    )


def validate_asset_identity(asset: InstallerAsset, *, require_digest: bool = True) -> Version:
    """Bind an asset to this repository, its exact release, size, and trusted digest."""

    filename_version = installer_filename_version(asset.name)
    if filename_version is None:
        raise UpdateError("The selected update asset has an invalid Windows installer filename.")
    version = validate_release_asset_url(asset.name, asset.download_url, asset.version)
    if not installer_matches_version(asset.name, version):
        raise UpdateError("The installer filename does not match the selected release version.")
    patch = PATCH_ASSET_PATTERN.fullmatch(asset.name)
    if asset.kind == "patch":
        if (
            patch is None
            or asset.from_version != patch.group("source")
            or asset.source_inventory_sha256 is None
            or normalize_sha256(asset.source_inventory_sha256) != asset.source_inventory_sha256
        ):
            raise UpdateError("The patch has an invalid source installation identity.")
    elif (
        asset.kind != "full"
        or patch is not None
        or asset.from_version is not None
        or asset.source_inventory_sha256 is not None
    ):
        raise UpdateError("The update asset has an invalid installer kind.")
    if (
        not isinstance(asset.size_bytes, int)
        or isinstance(asset.size_bytes, bool)
        or not 0 < asset.size_bytes <= MAX_INSTALLER_SIZE_BYTES
    ):
        raise UpdateError("The release has no supported, bounded installer size.")
    if require_digest and asset.sha256 is None:
        raise UpdateError(
            "This release has no valid GitHub SHA-256 digest. Use the release page instead of the in-app installer."
        )
    return version


def validate_release_asset_url(name: str, url: str, version: str | None) -> Version:
    """Bind a metadata or executable asset URL to the selected repository and version."""

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError("Installer downloads require an HTTPS URL.")
    if parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment or parsed.username is not None:
        raise UpdateError("The installer must be a published FPVS Toolbox GitHub release asset.")
    prefix = f"/{RELEASE_REPOSITORY}/releases/download/"
    if not parsed.path.startswith(prefix):
        raise UpdateError("The installer must be a published FPVS Toolbox GitHub release asset.")
    parts = parsed.path[len(prefix) :].split("/")
    if len(parts) != 2 or unquote(parts[1]) != name:
        raise UpdateError("The installer URL does not match the selected release asset.")
    tag_version = parse_release_version(unquote(parts[0]))
    selected_version = parse_release_version(version) if version is not None else tag_version
    if tag_version != selected_version:
        raise UpdateError("The installer filename does not match the selected release version.")
    return selected_version


def validate_response_url(response: object) -> None:
    """Reject insecure redirects; GitHub's signed release CDN is allowed."""

    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        raise UpdateError("GitHub returned a response without a verifiable HTTPS URL.")
    final_url = geturl()
    if not isinstance(final_url, str):
        raise UpdateError("GitHub returned an invalid response URL.")
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {
        "github.com",
        "api.github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }:
        raise UpdateError("GitHub redirected the update request to an untrusted or non-HTTPS URL.")


@contextmanager
def managed_response(response: Any) -> Iterator[Any]:
    """Close urllib responses on every path without hiding the original operation error."""

    try:
        yield response
    except BaseException:
        try:
            response.close()
        except Exception:  # Response cleanup must preserve the original operation error.
            _LOG.warning("update_response_close_failed", exc_info=True)
        raise
    else:
        response.close()
