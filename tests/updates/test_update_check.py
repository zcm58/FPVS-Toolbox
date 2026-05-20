"""Update-checking backend tests."""

from __future__ import annotations

import pytest

from Main_App.updates.github_releases import (
    parse_release_version,
    select_update_from_releases,
    summarize_release_notes,
)
from Main_App.updates.models import UpdateError


def _release(
    tag: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    asset_name: str | None = None,
    body: str = "Fixed bugs\n\nAdded update checker",
) -> dict[str, object]:
    asset = asset_name or f"FPVSToolbox-{tag.lstrip('v')}-setup.exe"
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/zcm58/FPVS-Toolbox-Repo/releases/tag/{tag}",
        "body": body,
        "assets": [
            {
                "name": asset,
                "browser_download_url": f"https://github.com/downloads/{asset}",
                "size": 123,
            }
        ],
    }


def test_parse_release_version_accepts_beta_tag_aliases() -> None:
    assert str(parse_release_version("v0.9.0b2")) == "0.9.0b2"
    assert str(parse_release_version("v0.9.0-beta.2")) == "0.9.0b2"
    assert str(parse_release_version("0.9.0-beta")) == "0.9.0b0"


def test_stable_versions_ignore_prereleases_by_default() -> None:
    result = select_update_from_releases(
        [
            _release("v1.1.0b1", prerelease=True),
            _release("v1.0.1"),
        ],
        current_version="1.0.0",
    )

    assert result.update_available is True
    assert result.latest_version == "1.0.1"
    assert result.installer_asset_name == "FPVSToolbox-1.0.1-setup.exe"


def test_beta_versions_can_see_prerelease_updates() -> None:
    result = select_update_from_releases(
        [_release("v0.9.0b2", prerelease=True), _release("v0.8.0")],
        current_version="0.9.0b1",
    )

    assert result.update_available is True
    assert result.latest_version == "0.9.0b2"
    assert result.is_prerelease is True


def test_drafts_are_ignored() -> None:
    result = select_update_from_releases(
        [_release("v9.9.9", draft=True), _release("v1.0.1")],
        current_version="1.0.0",
    )

    assert result.latest_version == "1.0.1"


def test_current_version_reports_no_update_without_installer_asset() -> None:
    result = select_update_from_releases([_release("v1.0.0")], current_version="1.0.0")

    assert result.update_available is False
    assert result.latest_version == "1.0.0"
    assert result.installer_asset is None


def test_missing_installer_asset_reports_incomplete_update_metadata() -> None:
    release = _release("v1.0.1")
    release["assets"] = []

    result = select_update_from_releases([release], current_version="1.0.0")

    assert result.update_available is True
    assert result.installer_asset is None
    assert result.metadata_incomplete is True


def test_ambiguous_installer_assets_fail_closed() -> None:
    release = _release("v1.0.0")
    release["assets"] = [
        {
            "name": "FPVSToolbox-custom-setup.exe",
            "browser_download_url": "https://github.com/downloads/custom.exe",
            "size": 1,
        },
        {
            "name": "FPVSToolbox-other-setup.exe",
            "browser_download_url": "https://github.com/downloads/other.exe",
            "size": 1,
        },
    ]

    with pytest.raises(UpdateError, match="multiple matching installer assets"):
        select_update_from_releases([release], current_version="0.9.0")


def test_invalid_installed_version_raises_update_error() -> None:
    with pytest.raises(UpdateError, match="Installed version"):
        select_update_from_releases([_release("v1.0.0")], current_version="not-a-version")


def test_release_notes_summary_is_compact() -> None:
    body = "\n".join([""] + [f"Change {index}" for index in range(100)])

    summary = summarize_release_notes(body)

    assert summary.startswith("Change 0")
    assert len(summary) <= 600
    assert summary.endswith("...")
