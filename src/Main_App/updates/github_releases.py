"""GitHub Releases update-checking backend."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from Main_App.updates.application import APP_VERSION as __version__
from Main_App.updates.cache_io import check_cancel
from Main_App.updates.models import (
    CandidateRelease,
    InstallerAsset,
    UpdateCheckResult,
    UpdateError,
    UpdatePhase,
)
from Main_App.updates.patches import select_patch_candidate, select_patch_update
from Main_App.updates.validation import (
    MAX_INSTALLER_SIZE_BYTES,
    installer_matches_version,
    managed_response,
    parse_release_version,
    validate_asset_identity,
    validate_response_url,
)

DEFAULT_RELEASES_API_URL = "https://api.github.com/repos/zcm58/FPVS-Toolbox-Repo/releases"
_SUMMARY_LIMIT = 600
_MAX_METADATA_BYTES = 2 * 1024 * 1024
METADATA_TIMEOUT_SECONDS = 5
MAX_METADATA_SECONDS = 30


def check_for_updates(
    *,
    current_version: str = __version__,
    releases_api_url: str = DEFAULT_RELEASES_API_URL,
    include_prereleases: bool | None = None,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
) -> UpdateCheckResult:
    """Fetch GitHub Releases and return the newest eligible update state."""

    return select_update_from_releases(
        fetch_release_metadata(releases_api_url, cancel_event=cancel_event),
        current_version=current_version,
        include_prereleases=include_prereleases,
        resolve_patches=True,
        cancel_event=cancel_event,
        phase_callback=phase_callback,
    )


def fetch_release_metadata(releases_api_url: str, *, cancel_event: Event | None = None) -> list[dict[str, Any]]:
    """Fetch raw release metadata from GitHub's Releases API."""

    check_cancel(cancel_event)
    parsed_url = urlparse(releases_api_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc.lower() != "api.github.com"
        or parsed_url.path != "/repos/zcm58/FPVS-Toolbox-Repo/releases"
        or parsed_url.fragment
    ):
        raise UpdateError("Update checks require an HTTPS GitHub Releases URL.")
    request = Request(
        releases_api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FPVS-Toolbox/{__version__}",
        },
    )
    try:
        started = time.monotonic()
        with managed_response(urlopen(request, timeout=METADATA_TIMEOUT_SECONDS)) as response:
            validate_response_url(response)
            payload = bytearray()
            read = getattr(response, "read1", response.read)
            while True:
                check_cancel(cancel_event)
                if time.monotonic() - started > MAX_METADATA_SECONDS:
                    raise UpdateError("GitHub update check exceeded its time limit.")
                chunk = read(64 * 1024)
                check_cancel(cancel_event)
                if time.monotonic() - started > MAX_METADATA_SECONDS:
                    raise UpdateError("GitHub update check exceeded its time limit.")
                if not chunk:
                    break
                if len(payload) + len(chunk) > _MAX_METADATA_BYTES:
                    raise UpdateError("GitHub release metadata exceeded its size limit.")
                payload.extend(chunk)
    except HTTPError as error:
        raise UpdateError(f"GitHub update check failed with HTTP {error.code}.") from error
    except URLError as error:
        raise UpdateError(f"Could not reach GitHub Releases: {error.reason}") from error
    except TimeoutError as error:
        raise UpdateError("GitHub update check timed out.") from error
    except OSError as error:
        raise UpdateError(f"Could not read GitHub release metadata: {error}") from error

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("GitHub returned unreadable release metadata.") from error
    if not isinstance(decoded, list):
        raise UpdateError("GitHub returned release metadata in an unexpected format.")
    return [item for item in decoded if isinstance(item, dict)]


def check_update_candidate(
    *,
    current_version: str,
    install_root: Path | None,
    repair: bool = False,
    force_full: bool = False,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
) -> UpdateCheckResult:
    """Independent helper discovery without scanning application payload files."""
    releases = fetch_release_metadata(DEFAULT_RELEASES_API_URL, cancel_event=cancel_event)
    current = _parse_version(current_version)
    result = select_update_from_releases(releases, current_version=current_version)
    if repair:
        latest = select_update_from_releases(
            releases, current_version="0.0.0", include_prereleases=current.is_prerelease
        )
        if _parse_version(latest.latest_version) < current:
            raise UpdateError("No current or newer published installer is available for repair.")
        result = replace(
            latest,
            current_version=current_version,
            selection_reason="Full installer selected for repair or reinstallation.",
        )
    if not result.update_available or repair or force_full:
        return result
    if phase_callback is not None:
        phase_callback(UpdatePhase("Update found. Checking available packages...", result))
    latest_release = next(
        (
            candidate
            for candidate in _iter_candidate_releases(releases, include_prereleases=current.is_prerelease)
            if str(candidate.version) == result.latest_version
        ),
        None,
    )
    if latest_release is None:
        return result
    return select_patch_candidate(
        result,
        latest_release.assets,
        install_root=install_root,
        cancel_event=cancel_event,
        phase_callback=phase_callback,
    )


def select_update_from_releases(
    releases: Sequence[dict[str, Any]],
    *,
    current_version: str,
    include_prereleases: bool | None = None,
    resolve_patches: bool = False,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
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
    result = UpdateCheckResult(
        current_version=current_version,
        latest_version=str(latest.version),
        update_available=latest.version > current,
        release_url=latest.release_url,
        release_notes_summary=summarize_release_notes(latest.body),
        installer_asset=latest.installer_asset if latest.version > current else None,
        is_prerelease=latest.is_prerelease,
        metadata_incomplete=latest.version > current and latest.installer_asset is None,
    )
    if resolve_patches and result.update_available:
        if phase_callback is not None:
            phase_callback(UpdatePhase("Update found. Checking patch availability...", result))
        return select_patch_update(result, latest.assets, cancel_event=cancel_event, phase_callback=phase_callback)
    return result


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
        asset = _select_installer_asset(
            release.get("assets"),
            normalized_version=str(version),
            tag_name=tag_name,
        )
        release_url = release.get("html_url")
        body = release.get("body", "")
        yield CandidateRelease(
            version=version,
            tag_name=tag_name,
            release_url=release_url if isinstance(release_url, str) else None,
            body=body if isinstance(body, str) else "",
            installer_asset=asset,
            is_prerelease=is_prerelease,
            assets=tuple(item for item in release.get("assets", []) if isinstance(item, dict))
            if isinstance(release.get("assets"), list)
            else (),
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
        and asset["name"].lower().startswith("fpvstoolbox-")
        and asset["name"].lower().endswith("-setup.exe")
        and isinstance(asset.get("browser_download_url"), str)
    ]
    if not installer_assets:
        return None
    version = parse_release_version(normalized_version)
    version_matches = [asset for asset in installer_assets if installer_matches_version(asset["name"], version)]
    if len(version_matches) > 1 or (not version_matches and len(installer_assets) > 1):
        raise UpdateError(f"Release '{tag_name}' has multiple matching installer assets.")
    if not version_matches:
        return None

    selected = version_matches[0]
    size = selected.get("size")
    asset_id = selected.get("id")
    digest = selected.get("digest")
    asset = InstallerAsset(
        name=selected["name"],
        download_url=selected["browser_download_url"],
        size_bytes=size if type(size) is int and 0 < size <= MAX_INSTALLER_SIZE_BYTES else None,
        sha256=digest if isinstance(digest, str) and digest.startswith("sha256:") else None,
        version=str(version),
        asset_id=asset_id if type(asset_id) is int and asset_id > 0 else None,
    )
    try:
        validate_asset_identity(asset, require_digest=False)
    except UpdateError:
        return None
    return asset


def _parse_version(version: str) -> Version:
    try:
        return Version(version)
    except InvalidVersion as error:
        raise UpdateError(f"Installed version '{version}' is not a supported version.") from error
