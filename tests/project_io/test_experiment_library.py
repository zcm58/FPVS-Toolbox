"""Public dataset integrity, containment, cancellation, and local reopening."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import stat
from threading import Event
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from Main_App.projects import FrequencyProtocol, Project
from Main_App.projects import experiment_library as library
from Main_App.projects import public_datasets as catalog


class Response(io.BytesIO):
    def __init__(self, data, *, url=None, length=None):
        super().__init__(data)
        self.url = url
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def geturl(self):
        return self.url


def _payloads():
    protocol = FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=45,
        expected_analyzed_oddball_cycles_source="manual",
    )
    project = {
        "schema_version": "2.1.0", "name": "Simulated FPVS-Oddball Demo",
        "results_folder": ".", "event_map": {"Red": 1, "Green": 2},
        "frequency_protocol": protocol.to_manifest(),
        "groups": {"demo": {"label": "Demo", "folder_name": "Demo", "raw_input_folder": "Input"}},
        "participants": {"P1": {"group_id": "demo", "raw_file": "Input/P1.bdf"}},
    }
    return {
        "project.json": json.dumps(project).encode(),
        "Input/P1.bdf": b"synthetic raw recording bytes" * 40,
        "README.md": b"Synthetic demonstration data.",
        "LICENSE": b"CC BY 4.0",
        "CITATION.cff": b"cff-version: 1.2.0\n",
    }


def _archive(tmp_path, *, payloads=None, manifest_changes=None, additional=()):
    payloads = _payloads() if payloads is None else payloads
    manifest = {
        "schema_version": "1.0", "item_id": "simulated-fpvs-oddball-demo", "version": "1.0.0",
        "project_file": "project.json",
        "files": [{"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in payloads.items()],
    }
    if manifest_changes:
        manifest_changes(manifest)
    files = {**payloads, "dataset-manifest.json": json.dumps(manifest).encode()}
    path = tmp_path / "dataset.zip"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
        for info, data in additional:
            zipped.writestr(info, data)
    item = catalog.PublicDataset(
        item_id="simulated-fpvs-oddball-demo", version="1.0.0", title="Simulated FPVS-Oddball Demo",
        description="Simulated FPVS-oddball experiment. Download this to test FPVS Toolbox on your PC.",
        filename="simulated-fpvs-oddball-demo-1.0.0.zip", size_bytes=path.stat().st_size,
        uncompressed_size_bytes=sum(map(len, files.values())) + sum(len(data) for _, data in additional),
        file_count=len(files) + len(additional), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        min_toolbox_version="3.0.0", project_format=catalog.PROJECT_FORMAT,
        participant_count=1, condition_count=2, sample_rate_hz=256,
    )
    return path, item


def _serve(monkeypatch, archive, *, content=None, length=None):
    payload = archive.read_bytes() if content is None else content
    calls = []

    def respond(url, *, accept):
        calls.append((url, accept))
        return Response(payload, url=url, length=len(payload) if length is None else length)

    monkeypatch.setattr(library, "public_response", respond)
    return calls


def test_catalog_has_public_route_and_no_authentication(tmp_path, monkeypatch):
    _, item = _archive(tmp_path)
    document = json.dumps({"schema_version": "1.0", "library_name": "OpenFPVS", "access_level": "download", "items": [item.to_dict()]}).encode()
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response(document, url=request.full_url)

    monkeypatch.setattr(catalog, "build_opener", lambda *args: Opener())
    assert catalog.list_public_datasets() == (item,)
    assert requests[0].full_url == "https://openfpvs.com/public-library/v1/catalog?kind=dataset"
    assert not ({"authorization", "cookie", "x-fpvs-token"} & {name.lower() for name in requests[0].headers})


@pytest.mark.parametrize("change", [
    {"size_bytes": True}, {"sha256": "0" * 63}, {"item_id": "../demo"},
    {"filename": "different.zip"}, {"kind": "experiment"}, {"unknown": "value"},
])
def test_catalog_rejects_untrusted_or_unsupported_records(tmp_path, change):
    _, item = _archive(tmp_path)
    with pytest.raises(library.LibraryError):
        catalog.PublicDataset.from_dict({**item.to_dict(), **change})


def test_read_only_archive_validation_checks_every_file(tmp_path):
    archive, item = _archive(tmp_path)
    before = set(tmp_path.iterdir())
    manifest = library.validate_dataset_archive(archive, item)
    assert manifest.project_file == "project.json"
    assert len(manifest.files) == item.file_count
    assert set(tmp_path.iterdir()) == before
    assert {file.path for file in manifest.files} >= {"Input/P1.bdf", "LICENSE", "CITATION.cff"}


@pytest.mark.parametrize("name", ["../outside.json", "C:/outside.json", "Input\\outside.json", "input/p1.bdf", "install.py"])
def test_archive_rejects_unsafe_or_colliding_members(tmp_path, name):
    archive, item = _archive(tmp_path, additional=[(name, b"outside")])
    with pytest.raises(library.LibraryError):
        library.validate_dataset_archive(archive, item)
    assert not (tmp_path.parent / "outside.json").exists()


def test_archive_rejects_symbolic_link_members(tmp_path):
    link = ZipInfo("Input/link.json")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive, item = _archive(tmp_path, additional=[(link, b"../../outside")])
    with pytest.raises(library.LibraryError, match="linked"):
        library.validate_dataset_archive(archive, item)


def test_archive_rejects_per_file_digest_mismatch_after_archive_hash_matches(tmp_path):
    archive, item = _archive(tmp_path, manifest_changes=lambda doc: doc["files"][1].update(sha256="0" * 64))
    with pytest.raises(library.LibraryError, match="verification failed"):
        library.validate_dataset_archive(archive, item)


@pytest.mark.parametrize("field", ["size_bytes", "uncompressed_size_bytes", "file_count", "participant_count", "condition_count"])
def test_archive_rejects_published_metadata_mismatch(tmp_path, field):
    archive, item = _archive(tmp_path)
    with pytest.raises(library.LibraryError):
        library.validate_dataset_archive(archive, replace(item, **{field: getattr(item, field) + 1}))


@pytest.mark.parametrize("field", ["results_folder", "input_folder"])
def test_archive_rejects_project_path_escape_before_model_loading(tmp_path, field):
    payloads = _payloads()
    project = json.loads(payloads["project.json"])
    project[field] = "../outside"
    payloads["project.json"] = json.dumps(project).encode()
    archive, item = _archive(tmp_path, payloads=payloads)
    with pytest.raises(library.LibraryError, match="unsafe"):
        library.validate_dataset_archive(archive, item)


def _repeated_payloads(folder="Input", raw_file="Input/P1.bdf"):
    payloads = _payloads()
    project = json.loads(payloads["project.json"])
    project["sessions"] = {"visit1": {"visit_index": 1}}
    project["recording_sources"] = {
        "demo_visit1": {"group_id": "demo", "session_id": "visit1", "raw_input_folder": folder},
    }
    project["recordings"] = {
        "p1_visit1": {"participant_id": "P1", "source_id": "demo_visit1", "session_id": "visit1", "raw_file": raw_file},
    }
    payloads["project.json"] = json.dumps(project).encode()
    return payloads


@pytest.mark.parametrize(("folder", "raw_file", "expected_error"), [
    ("Input", "Input/P1.bdf", None),
    ("LocalRecordings", "Input/P1.bdf", "recording source"),
    ("Input", "Input/P2.bdf", "packaged BDF file"),
    ("Input", "README.md", "packaged BDF file"),
])
def test_public_install_checks_repeated_recordings_against_package(
    tmp_path, monkeypatch, folder, raw_file, expected_error,
):
    payloads = _repeated_payloads(folder, raw_file)
    archive, item = _archive(tmp_path, payloads=payloads)
    _serve(monkeypatch, archive)
    root = tmp_path / "Projects"
    root.mkdir()
    if expected_error is None:
        target = library.install_public_dataset(item, root)
        assert (target / raw_file).read_bytes() == payloads[raw_file]
        assert json.loads((target / ".openfpvs-dataset.json").read_bytes())["recording_path_validation"]
    else:
        phases = []
        with pytest.raises(library.LibraryError, match=expected_error):
            library.install_public_dataset(item, root, phase_callback=phases.append)
        assert phases == ["download", "verify"]
        assert not any(child.is_dir() for child in root.iterdir())


def _old_install(tmp_path, folder="Input", raw_file="Input/P1.bdf"):
    payloads = _repeated_payloads(folder, raw_file)
    archive, item = _archive(tmp_path, payloads=payloads)
    target = tmp_path / "Projects" / f"{item.item_id}-{item.version}"
    target.mkdir(parents=True)
    with ZipFile(archive) as zipped:
        for name in (*payloads, "dataset-manifest.json"):
            dest = target / name
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(zipped.read(name))
    receipt = target / ".openfpvs-dataset.json"
    receipt.write_text(json.dumps({"schema_version": "1.0", "dataset": item.to_dict(), "origin": catalog.DEFAULT_ORIGIN}))
    return target, item


@pytest.mark.parametrize(("folder", "raw_file"), [("LocalRecordings", "LocalRecordings/P1.bdf"), ("Input", "Input/P2.bdf")])
def test_legacy_package_recording_paths_rejected_offline_and_on_direct_open(tmp_path, monkeypatch, folder, raw_file):
    target, item = _old_install(tmp_path, folder, raw_file)
    manifest = target / "project.json"
    receipt = target / ".openfpvs-dataset.json"
    before = manifest.read_bytes(), receipt.read_bytes()
    monkeypatch.setattr(library, "public_response", lambda *a, **k: pytest.fail("offline"))
    notices = []
    assert library.list_installed_datasets(target.parent, on_notice=notices.append) == ()
    assert len(notices) == 1 and "Keep a backup" in notices[0]
    for reopen in (
        lambda: library.installed_dataset_path(item, target.parent),
        lambda: library.install_public_dataset(item, target.parent),
        lambda: Project.load(target),
        lambda: Project.load(target, manifest={}),
    ):
        with pytest.raises(library.LibraryError, match="use the BDF paths listed in dataset-manifest.json"):
            reopen()
    assert (manifest.read_bytes(), receipt.read_bytes()) == before
    assert not (target / "1 - Excel Data Files").exists()


@pytest.mark.parametrize("direct_first", [False, True])
def test_legacy_package_migrates_offline_preserving_edits_and_later_external_sources(tmp_path, monkeypatch, direct_first):
    target, item = _old_install(tmp_path)
    monkeypatch.setattr(library, "public_response", lambda *a, **k: pytest.fail("offline"))
    manifest = target / "project.json"
    project = json.loads(manifest.read_bytes())
    project["name"] = "My local visits"
    project["recordings"]["p1_visit1"]["raw_file"] = str(Path("Input") / "P1.bdf")
    project["recording_sources"]["demo_visit1"]["raw_input_folder"] = str(target / "Input")
    manifest.write_text(json.dumps(project))
    edited = manifest.read_bytes()
    if direct_first:
        assert Project.load(target).recordings["p1_visit1"]["raw_file"] == target / "Input" / "P1.bdf"
    else:
        assert library.list_installed_datasets(target.parent) == (item,)
    assert manifest.read_bytes() == edited
    receipt = json.loads((target / ".openfpvs-dataset.json").read_bytes())
    assert receipt["recording_path_validation"] and receipt["origin"] == catalog.DEFAULT_ORIGIN

    local = tmp_path / "My recordings"
    local.mkdir()
    project["recording_sources"]["demo_visit1"]["raw_input_folder"] = str(local)
    project["recordings"]["p1_visit1"]["raw_file"] = str(local / "P1.bdf")
    manifest.write_text(json.dumps(project))
    assert library.install_public_dataset(item, target.parent) == target
    assert Project.load(target).recordings["p1_visit1"]["raw_file"] == local / "P1.bdf"


def test_legacy_migration_rejects_oversize_inventory_before_model_loading(tmp_path):
    target, _ = _old_install(tmp_path)
    (target / "dataset-manifest.json").write_bytes(b" " * (library._JSON_LIMIT + 1))
    with pytest.raises(library.LibraryError, match="file manifest exceeds its size limit"):
        Project.load(target)
    assert "recording_path_validation" not in json.loads((target / ".openfpvs-dataset.json").read_bytes())


def test_legacy_external_edit_can_be_recovered_and_registered_again(tmp_path):
    target, item = _old_install(tmp_path)
    manifest = target / "project.json"
    packaged = json.loads(manifest.read_bytes())
    external = tmp_path / "Previously added recordings"
    external.mkdir()
    edited = json.loads(manifest.read_bytes())
    edited["name"] = "My local settings"
    edited["recording_sources"]["demo_visit1"]["raw_input_folder"] = str(external)
    edited["recordings"]["p1_visit1"]["raw_file"] = str(external / "P1.bdf")
    manifest.write_text(json.dumps(edited))
    backup = manifest.read_bytes()
    with pytest.raises(library.LibraryError, match="register any trusted external recordings again"):
        Project.load(target)
    assert manifest.read_bytes() == backup

    packaged["name"] = edited["name"]
    manifest.write_text(json.dumps(packaged))
    assert library.installed_dataset_path(item, target.parent) == target
    manifest.write_bytes(backup)
    assert Project.load(target).recording_sources["demo_visit1"]["raw_input_folder"] == external


def test_install_opens_normal_project_and_reopens_offline_preserving_edits(tmp_path, monkeypatch):
    archive, item = _archive(tmp_path)
    root = tmp_path / "Projects"
    root.mkdir()
    calls = _serve(monkeypatch, archive)
    phases = []
    target = library.install_public_dataset(item, root, phase_callback=phases.append)
    assert phases == ["download", "verify", "setup"]
    assert (target / "Input/P1.bdf").read_bytes() == _payloads()["Input/P1.bdf"]
    assert library.list_installed_datasets(root) == (item,)
    project = json.loads((target / "project.json").read_bytes())
    project["name"] = "My local demo"
    (target / "project.json").write_text(json.dumps(project))
    assert library.install_public_dataset(item, root) == target
    assert library.installed_dataset_path(item, root) == target
    renamed = replace(item, title="Updated public title", description="Updated public description")
    assert library.installed_dataset_path(renamed, root) == target
    assert json.loads((target / "project.json").read_bytes())["name"] == "My local demo"
    assert len(calls) == 1
    assert calls[0][0].endswith("/datasets/simulated-fpvs-oddball-demo/versions/1.0.0/download")


@pytest.mark.parametrize("stage", ["download", "verify", "setup"])
def test_cancellation_cleans_staging_and_retry_succeeds(tmp_path, monkeypatch, stage):
    archive, item = _archive(tmp_path)
    root = tmp_path / "Projects"
    root.mkdir()
    _serve(monkeypatch, archive)
    event = Event()

    def phase(value):
        if value == stage:
            event.set()

    with pytest.raises(library.LibraryCancelled):
        library.install_public_dataset(item, root, phase_callback=phase, cancel_event=event)
    assert not any(path.is_dir() for path in root.iterdir())
    assert library.list_installed_datasets(root) == ()
    event.clear()
    assert library.install_public_dataset(item, root, cancel_event=event).is_dir()


@pytest.mark.parametrize("failure", ["truncated", "oversized", "digest"])
def test_failed_download_never_publishes_a_partial_project(tmp_path, monkeypatch, failure):
    archive, item = _archive(tmp_path)
    root = tmp_path / "Projects"
    root.mkdir()
    data = archive.read_bytes()
    if failure == "truncated":
        data = data[:-1]
    elif failure == "oversized":
        data += b"extra"
    else:
        data = b"x" + data[1:]
    _serve(monkeypatch, archive, content=data, length=item.size_bytes)
    with pytest.raises(library.LibraryError):
        library.install_public_dataset(item, root)
    assert library.installed_dataset_path(item, root) is None
    assert not any(path.is_dir() for path in root.iterdir())


def test_existing_user_folder_is_preserved(tmp_path, monkeypatch):
    archive, item = _archive(tmp_path)
    root = tmp_path / "Projects"
    target = root / f"{item.item_id}-{item.version}"
    target.mkdir(parents=True)
    (target / "user-data.json").write_text('{"keep":true}')
    calls = _serve(monkeypatch, archive)
    with pytest.raises(library.LibraryError, match="completed Library installation"):
        library.install_public_dataset(item, root)
    assert (target / "user-data.json").read_text() == '{"keep":true}'
    assert not calls


def test_concurrent_installs_publish_once_and_reuse_the_same_project(tmp_path, monkeypatch):
    archive, item = _archive(tmp_path)
    root = tmp_path / "Projects"
    root.mkdir()
    calls = _serve(monkeypatch, archive)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: library.install_public_dataset(item, root), range(2)))
    assert results[0] == results[1]
    assert len(calls) == 1
    assert len(library.list_installed_datasets(root)) == 1


def test_local_discovery_preserves_valid_installation_with_damaged_siblings(tmp_path, monkeypatch):
    archive, item = _archive(tmp_path)
    _serve(monkeypatch, archive)
    root = tmp_path / "Projects"
    root.mkdir()
    target = library.install_public_dataset(item, root)
    broken = root / "A broken installation"
    broken.mkdir()
    (broken / ".openfpvs-dataset.json").write_text("{", encoding="utf-8")
    (root / "Ordinary project").mkdir()
    notices = []
    assert library.list_installed_datasets(root, on_notice=notices.append) == (item,)
    assert len(notices) == 1 and broken.name in notices[0]
    assert library.installed_dataset_path(item, root) == target


def test_local_manifest_read_enforces_limit_on_open_file(tmp_path, monkeypatch):
    archive, item = _archive(tmp_path)
    _serve(monkeypatch, archive)
    root = tmp_path / "Projects"
    root.mkdir()
    manifest = library.install_public_dataset(item, root) / "project.json"
    original_open = Path.open
    read_sizes = []
    grow_on_read = False

    def observed_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == manifest and stream.mode == "rb":
            original_read = stream.read

            def read(size=-1):
                read_sizes.append(size)
                if grow_on_read:
                    with original_open(path, "ab") as writer:
                        writer.write(b" ")
                return original_read(size)

            stream.read = read
        return stream

    monkeypatch.setattr(Path, "open", observed_open)
    assert library.list_installed_datasets(root) == (item,)
    assert read_sizes and all(0 < size <= library._JSON_LIMIT + 1 for size in read_sizes)
    grow_on_read = True
    with pytest.raises(library.LibraryError, match="changed while reading"):
        library.installed_dataset_path(item, root)
    manifest.write_bytes(b" " * (library._JSON_LIMIT + 1))
    with pytest.raises(library.LibraryError, match="size limit"):
        library.installed_dataset_path(item, root)
