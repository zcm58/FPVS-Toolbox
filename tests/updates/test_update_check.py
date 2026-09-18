"""Update-checking backend tests."""

from __future__ import annotations

import io
import json
from threading import Event

import pytest

from Main_App.updates import github_releases
from Main_App.updates.github_releases import (
    check_for_updates,
    fetch_release_metadata,
    parse_release_version,
    select_update_from_releases,
    summarize_release_notes,
)
from Main_App.updates.models import UpdateCancelled, UpdateError


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
                "browser_download_url": (
                    f"https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/{tag}/{asset}"
                ),
                "size": 123,
                "digest": "sha256:" + "a" * 64,
                "id": 1234,
            }
        ],
    }


@pytest.fixture(autouse=True)
def _no_real_release_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github_releases,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("Release metadata must be mocked in unit tests"),
    )


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


def test_current_version_reports_no_update_without_installer_asset() -> None:
    result = select_update_from_releases([_release("v0.9.0b1")], current_version="0.9.0b1")

    assert result.update_available is False
    assert result.latest_version == "0.9.0b1"
    assert result.installer_asset is None


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


def test_release_notes_summary_is_compact() -> None:
    body = "\n".join([""] + [f"Change {index}" for index in range(100)])

    summary = summarize_release_notes(body)

    assert summary.startswith("Change 0")
    assert len(summary) <= 600
    assert summary.endswith("...")


def test_selected_asset_carries_normalized_digest_release_version_and_id() -> None:
    release = _release("v1.4.0")
    release["assets"][0]["digest"] = "sha256:" + "A" * 64
    result = select_update_from_releases([release], current_version="1.3.0")
    assert result.installer_asset is not None
    assert result.installer_asset.sha256 == "a" * 64
    assert result.installer_asset.version == "1.4.0"
    assert result.installer_asset.asset_id == 1234


@pytest.mark.parametrize("digest", [None, "", "invalid", "a" * 64, "sha512:" + "a" * 64, True])
def test_latest_unverifiable_release_is_still_available_not_up_to_date(digest: object) -> None:
    latest = _release("v1.5.0")
    latest["assets"][0]["digest"] = digest
    result = select_update_from_releases([latest, _release("v1.4.0")], current_version="1.4.0")
    assert result.update_available
    assert result.latest_version == "1.5.0"
    assert result.installer_asset is not None
    assert result.installer_asset.sha256 is None


def test_asset_version_matching_is_exact_not_a_filename_substring() -> None:
    correct = _release("v2.0.0")
    other = _release("v12.0.0")
    correct["assets"].extend(other["assets"])
    result = select_update_from_releases([correct], current_version="1.3.0")
    assert result.installer_asset_name == "FPVSToolbox-2.0.0-setup.exe"


def test_two_equivalent_matching_versions_are_ambiguous() -> None:
    release = _release("v2.0.0")
    release["assets"].extend(_release("v2.0")["assets"])
    with pytest.raises(UpdateError, match="multiple matching"):
        select_update_from_releases([release], current_version="1.3.0")


def test_missing_or_wrong_version_installer_does_not_hide_latest_release() -> None:
    latest = _release("v2.0.0", asset_name="FPVSToolbox-12.0.0-setup.exe")
    result = select_update_from_releases([latest, _release("v1.3.0")], current_version="1.3.0")
    assert result.update_available
    assert result.latest_version == "2.0.0"
    assert result.installer_asset is None


def test_studio_legacy_alias_is_not_accepted_for_toolbox() -> None:
    result = select_update_from_releases(
        [_release("v0.9.9.10", asset_name="FPVSToolbox-0.9.10-setup.exe")],
        current_version="0.9.9",
    )
    assert result.installer_asset is None
    other = select_update_from_releases(
        [_release("v0.9.9.11", asset_name="FPVSToolbox-0.9.11-setup.exe")],
        current_version="0.9.9",
    )
    assert other.update_available
    assert other.installer_asset is None


@pytest.mark.parametrize(
    "changes",
    [
        {"browser_download_url": "http://github.com/untrusted.exe"},
        {"browser_download_url": "https://example.com/untrusted.exe"},
        {"name": "../FPVSToolbox-2.0.0-setup.exe"},
        {"name": "FPVSToolbox-2.0.0-setup.exe:stream"},
        {"size": None},
        {"size": True},
        {"size": -1},
        {"size": 4 * 1024**3 + 1},
    ],
)
def test_invalid_asset_metadata_disables_download_without_hiding_release(
    changes: dict[str, object],
) -> None:
    release = _release("v2.0.0")
    release["assets"][0].update(changes)
    result = select_update_from_releases([release], current_version="1.3.0")
    assert result.update_available
    assert result.installer_asset is None


def test_explicit_channel_override_and_draft_filter_are_preserved() -> None:
    releases = [_release("v99.0.0", draft=True), _release("v2.0.0b1"), _release("v1.3.0")]
    result = select_update_from_releases(
        releases, current_version="1.3.0", include_prereleases=True
    )
    assert result.latest_version == "2.0.0b1"
    assert result.is_prerelease
    stable = select_update_from_releases(
        releases, current_version="1.3.0b1", include_prereleases=False
    )
    assert stable.latest_version == "1.3.0"


class _MetadataResponse(io.BytesIO):
    def __init__(self, payload: bytes, url: str | None = None) -> None:
        super().__init__(payload)
        self.url = url or github_releases.DEFAULT_RELEASES_API_URL

    def geturl(self) -> str:
        return self.url


def test_metadata_fetch_remains_metadata_only_with_finite_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _MetadataResponse(json.dumps([_release("v2.0.0")]).encode("utf-8"))
    calls: list[dict[str, object]] = []

    def urlopen(_request: object, **kwargs: object) -> _MetadataResponse:
        calls.append(kwargs)
        return response

    monkeypatch.setattr(github_releases, "urlopen", urlopen)
    result = check_for_updates(current_version="1.3.0")
    assert result.update_available
    assert calls == [{"timeout": 5}]
    assert response.closed


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/zcm58/FPVS-Toolbox-Repo/releases",
        "https://example.com/releases",
        "https://api.github.com/repos/someone/else/releases",
    ],
)
def test_metadata_only_uses_approved_https_release_endpoint(url: str) -> None:
    with pytest.raises(UpdateError, match="HTTPS GitHub Releases"):
        fetch_release_metadata(url)


def test_metadata_size_limit_prevents_unbounded_read(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _MetadataResponse(b"[{}]")
    monkeypatch.setattr(github_releases, "_MAX_METADATA_BYTES", 3)
    monkeypatch.setattr(github_releases, "urlopen", lambda *_args, **_kwargs: response)
    with pytest.raises(UpdateError, match="size limit"):
        fetch_release_metadata(github_releases.DEFAULT_RELEASES_API_URL)
    assert response.closed


def test_metadata_cancel_check_after_read_uses_read1(monkeypatch: pytest.MonkeyPatch) -> None:
    event = Event()
    response = _MetadataResponse(b"[]")

    def cancel_read(_size: int) -> bytes:
        event.set()
        return b"[]"

    monkeypatch.setattr(response, "read1", cancel_read)
    monkeypatch.setattr(response, "read", lambda *_args: pytest.fail("Must use bounded read1"))
    monkeypatch.setattr(github_releases, "urlopen", lambda *_args, **_kwargs: response)
    with pytest.raises(UpdateCancelled):
        check_for_updates(current_version="1.3.0", cancel_event=event)
    assert response.closed


def test_metadata_total_deadline_is_checked_after_each_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _MetadataResponse(b"[]")
    ticks = iter([0, 0, github_releases.MAX_METADATA_SECONDS + 1])
    monkeypatch.setattr(github_releases.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(github_releases, "urlopen", lambda *_args, **_kwargs: response)
    with pytest.raises(UpdateError, match="time limit"):
        fetch_release_metadata(github_releases.DEFAULT_RELEASES_API_URL)


@pytest.mark.parametrize("payload", [b"not-json", b"\xff", b'{"unexpected": "dict"}'])
def test_bad_metadata_is_reported_as_an_update_error(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    response = _MetadataResponse(payload)
    monkeypatch.setattr(github_releases, "urlopen", lambda *_args, **_kwargs: response)
    with pytest.raises(UpdateError):
        fetch_release_metadata(github_releases.DEFAULT_RELEASES_API_URL)
