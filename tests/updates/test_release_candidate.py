"""Check that a later qualification job accepts only the original build bytes."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts/packaging"))
    release_candidate = importlib.import_module("release_candidate")
    build = tmp_path / "build-job"
    qualification = tmp_path / "qualification-job"
    commit = "a" * 40
    version = "3.1.1"
    run_id = "123456"

    (build / "src").mkdir(parents=True)
    (build / "src/config.py").write_text(f'FPVS_TOOLBOX_VERSION: str = "{version}"\n', encoding="utf-8")
    provenance = build / release_candidate.PROVENANCE
    provenance.parent.mkdir(parents=True)
    provenance.write_text(json.dumps({"commit": commit, "run_id": run_id, "run_attempt": "1"}), encoding="utf-8")
    inventory = build / release_candidate.INVENTORY
    inventory.parent.mkdir(parents=True)
    inventory.write_bytes(b"owned file inventory")
    installer_root = build / "installers"
    installer_root.mkdir()
    for name, payload in (
        (f"FPVSToolbox-{version}-setup.exe", b"installer bytes"),
        (f"FPVSToolbox-Update-{version}.json", b'{"target_version":"3.1.1"}'),
    ):
        (installer_root / name).write_bytes(payload)
        checksum = hashlib.sha256(payload).hexdigest()
        (installer_root / f"{name}.sha256").write_text(f"{checksum}  {name}\n", encoding="ascii")

    receipt = release_candidate.candidate_receipt(build, commit, run_id)
    (build / release_candidate.RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    shutil.copytree(build, qualification)
    return release_candidate, qualification, commit, run_id


def test_candidate_can_be_qualified_from_a_different_checkout(candidate):
    release, checkout, commit, run_id = candidate
    release.verify_candidate(checkout, commit, run_id)


@pytest.mark.parametrize(("commit", "run_id"), [("b" * 40, "123456"), ("a" * 40, "234567")])
def test_candidate_rejects_a_different_build_identity(candidate, commit, run_id):
    release, checkout, _, _ = candidate
    with pytest.raises(RuntimeError, match="different commit or workflow run"):
        release.verify_candidate(checkout, commit, run_id)


def test_candidate_rejects_a_replaced_ownership_inventory(candidate):
    release, checkout, commit, run_id = candidate
    (checkout / release.INVENTORY).write_bytes(b"other owned file inventory")
    with pytest.raises(RuntimeError, match="differs from its build receipt"):
        release.verify_candidate(checkout, commit, run_id)


def test_candidate_rejects_an_installer_replaced_with_its_checksum(candidate):
    release, checkout, commit, run_id = candidate
    installer = checkout / "installers/FPVSToolbox-3.1.1-setup.exe"
    replacement = b"different installer bytes"
    installer.write_bytes(replacement)
    checksum = hashlib.sha256(replacement).hexdigest()
    installer.with_suffix(".exe.sha256").write_text(f"{checksum}  {installer.name}\n", encoding="ascii")
    with pytest.raises(RuntimeError, match="differs from its build receipt"):
        release.verify_candidate(checkout, commit, run_id)


def test_candidate_rejects_an_unexpected_release_file(candidate):
    release, checkout, commit, run_id = candidate
    (checkout / "installers/extra.exe").touch()
    with pytest.raises(RuntimeError, match="exact full-release asset set"):
        release.verify_candidate(checkout, commit, run_id)
