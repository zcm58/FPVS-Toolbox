"""GitHub Releases update-checking backend for FPVS Toolbox."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from config import FPVS_TOOLBOX_UPDATE_API, FPVS_TOOLBOX_VERSION
from Main_App.updates.models import (
    CandidateRelease,
    InstallerAsset,
    UpdateCheckResult,
    UpdateError,
)

DEFAULT_RELEASES_API_URL = FPVS_TOOLBOX_UPDATE_API
INSTALLER_ASSET_PATTERN = re.compile(r"^FPVSToolbox-.+-setup\.exe$", re.IGNORECASE)
_SUMMARY_LIMIT = 600
_REQUEST_TIMEOUT_S = 15


def check_for_updates(
    *,
    current_version: str = FPVS_TOOLBOX_VERSION,
    releases_api_url: str = DEFAULT_RELEASES_API_URL,
    include_prereleases: bool | None = None,
) -> UpdateCheckResult:
    """Fetch GitHub Releases and return the newest eligible update state."""

    return select_update_from_releases(
        fetch_release_metadata(releases_api_url),
        current_version=current_version,
        include_prereleases=include_prereleases,
    )


def fetch_release_metadata(releases_api_url: str) -> list[dict[str, Any]]:
    """Fetch raw release metadata from GitHub's Releases API."""

    if not releases_api_url.startswith("https://"):
        raise UpdateError("Update checks require an HTTPS GitHub Releases URL.")
    request = Request(
        releases_api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FPVS-Toolbox/{FPVS_TOOLBOX_VERSION}",
        },
    )
    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            payload = response.read()
    except HTTPError as error:
        raise UpdateError(f"GitHub update check failed with HTTP {error.code}.") from error
    except URLError as error:
        raise UpdateError(f"Could not reach GitHub Releases: {error.reason}") from error
    except TimeoutError as error:
        raise UpdateError("GitHub update check timed out.") from error

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("GitHub returned unreadable release metadata.") from error
    if not isinstance(decoded, list):
        raise UpdateError("GitHub returned release metadata in an unexpected format.")
    return [item for item in decoded if isinstance(item, dict)]


def select_update_from_releases(
    releases: Sequence[dict[str, Any]],
    *,
    current_version: str,
    include_prereleases: bool | None = None,
) -> UpdateCheckResult:
    """Select the newest eligible release and compare it with the installed version."""

    current = _parse_version(current_version)
    include_beta = current.is_prerelease if include_prereleases is None else include_prereleases
    candidates = sorted(
        _iter_candidate_releases(releases, include_prereleases=include_beta),
        key=lambda release: release.version,
        reverse=True,
    )

    if not candidates:
        return UpdateCheckResult(
            current_version=current_version,
            latest_version=current_version,
            update_available=False,
            release_url=None,
            release_notes_summary="",
            installer_asset=None,
            is_prerelease=current.is_prerelease,
        )

    latest = candidates[0]
    has_update = latest.version > current
    installer_asset = latest.installer_asset if has_update else None
    return UpdateCheckResult(
        current_version=current_version,
        latest_version=str(latest.version),
        update_available=has_update,
        release_url=latest.release_url,
        release_notes_summary=summarize_release_notes(latest.body),
        installer_asset=installer_asset,
        is_prerelease=latest.is_prerelease,
        metadata_incomplete=has_update and installer_asset is None,
    )


def parse_release_version(tag_name: str) -> Version:
    """Parse a GitHub release tag into a PEP 440 version."""

    normalized = tag_name.strip()
    if normalized.startswith(("v", "V")):
        normalized = normalized[1:]
    normalized = normalized.strip()
    normalized = re.sub(r"[-_]?beta[.-]?(\d+)$", r"b\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?beta$", "b0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?alpha[.-]?(\d+)$", r"a\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?alpha$", "a0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[-_]?rc[.-]?(\d+)$", r"rc\1", normalized, flags=re.IGNORECASE)
    try:
        return Version(normalized)
    except InvalidVersion as error:
        raise UpdateError(f"Release tag '{tag_name}' is not a supported version.") from error


def summarize_release_notes(body: str) -> str:
    """Return a compact user-facing release-notes preview."""

    clean_lines = [line.strip() for line in body.splitlines() if line.strip()]
    summary = "\n".join(clean_lines)
    if len(summary) <= _SUMMARY_LIMIT:
        return summary
    return f"{summary[: _SUMMARY_LIMIT - 3].rstrip()}..."


def _iter_candidate_releases(
    releases: Iterable[dict[str, Any]],
    *,
    include_prereleases: bool,
) -> Iterable[CandidateRelease]:
    for release in releases:
        if release.get("draft") is True:
            continue
        tag_name = release.get("tag_name")
        if not isinstance(tag_name, str) or not tag_name.strip():
            continue
        try:
            version = parse_release_version(tag_name)
        except UpdateError:
            continue
        is_prerelease = release.get("prerelease") is True or version.is_prerelease
        if is_prerelease and not include_prereleases:
            continue
        release_url = release.get("html_url")
        body = release.get("body", "")
        yield CandidateRelease(
            version=version,
            tag_name=tag_name,
            release_url=release_url if isinstance(release_url, str) else None,
            body=body if isinstance(body, str) else "",
            installer_asset=_select_installer_asset(
                release.get("assets"),
                normalized_version=str(version),
                tag_name=tag_name,
            ),
            is_prerelease=is_prerelease,
        )


def _select_installer_asset(
    assets: object,
    *,
    normalized_version: str,
    tag_name: str,
) -> InstallerAsset | None:
    if not isinstance(assets, list):
        return None
    installer_assets = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and INSTALLER_ASSET_PATTERN.match(asset["name"])
        and isinstance(asset.get("browser_download_url"), str)
        and asset["browser_download_url"].startswith("https://")
    ]
    if not installer_assets:
        return None
    if len(installer_assets) > 1:
        version_matches = [
            asset
            for asset in installer_assets
            if normalized_version in asset["name"] or tag_name.lstrip("vV") in asset["name"]
        ]
        if len(version_matches) == 1:
            installer_assets = version_matches
        else:
            raise UpdateError(f"Release '{tag_name}' has multiple matching installer assets.")

    selected = installer_assets[0]
    size = selected.get("size")
    return InstallerAsset(
        name=selected["name"],
        download_url=selected["browser_download_url"],
        size_bytes=size if isinstance(size, int) and size >= 0 else None,
    )


def _parse_version(version: str) -> Version:
    try:
        return Version(version)
    except InvalidVersion as error:
        raise UpdateError(f"Installed version '{version}' is not a supported version.") from error
