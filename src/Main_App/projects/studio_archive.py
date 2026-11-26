"""Project-owned Studio handoff evidence and archived full-audit workbooks."""

import hashlib
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from Main_App.io.safe_file import regular_file_info
from Main_App.io.xlsx_xml import _OFFICE_REL_NS, _RELATIONSHIP_TAG, _SHEET_TAG, _SPREADSHEET_NS, _xlsx_member_path


_SHA256 = re.compile("[0-9a-f]{64}")
_ARCHIVES = Path(".fpvs_imports/studio/prior-results")
_WORKBOOK_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"


def _managed_file(root: Path, relative: Path) -> Path:
    root = root.resolve(strict=True)
    parent = root
    for part in relative.parent.parts:
        parent = (parent / part).resolve()
        if not parent.is_relative_to(root) or parent == root:
            raise ValueError("The Studio archive directory must stay inside this project.")
    target = parent / relative.name
    regular_file_info(target)
    return target


def studio_evidence_path(root: Path, fingerprint: str) -> Path:
    if not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint):
        raise ValueError("Invalid Studio handoff fingerprint.")
    return _managed_file(root, _ARCHIVES.parent / f"{fingerprint}.json")


def archive_reviewed_result(root: Path, original: Path, coverage: str, released_hash: str | None) -> tuple[str, str]:
    """Copy the workbook and fingerprint those same bytes before publishing."""
    from Main_App.io.atomic_write import atomic_write

    if not _SHA256.fullmatch(coverage):
        raise ValueError("Invalid Studio archive fingerprint.")
    relative = _ARCHIVES / f"{coverage}.xlsx"
    target = _managed_file(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    publication = nullcontext(None) if target.exists() else atomic_write(target, binary=True)
    with original.open("rb") as source, publication as destination:
        if destination is None:
            fingerprint = hashlib.file_digest(source, "sha256").hexdigest()
            with target.open("rb") as archived:
                if fingerprint != hashlib.file_digest(archived, "sha256").hexdigest():
                    raise ValueError("The previous Studio workbook differs from its archived copy.")
        else:
            checksum = hashlib.sha256()
            while block := source.read(1024 * 1024):
                destination.write(block)
                checksum.update(block)
            fingerprint = checksum.hexdigest()
        if released_hash is not None and fingerprint != released_hash:
            raise ValueError("The previous Studio workbook differs from its release.")
    return relative.as_posix(), fingerprint


def _workbook_metadata(package: ZipFile, name: str) -> ElementTree.Element:
    # These package descriptors describe sheet names and links, independent
    # of the number of data rows in the archived result.
    member = package.getinfo(name)
    if member.file_size > 2 * 1024 * 1024:
        raise ValueError("The archived workbook has oversized package metadata.")
    return ElementTree.fromstring(package.read(member))


def _verify_workbook_package(package: ZipFile) -> None:
    names = package.namelist()
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("The archived workbook contains duplicate package entries.")
    types = _workbook_metadata(package, "[Content_Types].xml")
    if not any(part.get("PartName") == "/xl/workbook.xml" and part.get("ContentType") == _WORKBOOK_TYPE
               for part in types) or any(
        "macro" in part.get("ContentType", "").lower() or "vbaproject" in part.get("ContentType", "").lower()
        for part in types
    ):
        raise ValueError("The archive must contain a standard XLSX workbook.")
    root_links = _workbook_metadata(package, "_rels/.rels").iter(_RELATIONSHIP_TAG)
    documents = [rel for rel in root_links if rel.get("Type") == f"{_OFFICE_REL_NS}/officeDocument"]
    if (len(documents) != 1 or documents[0].get("TargetMode") == "External"
            or documents[0].get("Target") not in {"xl/workbook.xml", "/xl/workbook.xml"}):
        raise ValueError("The archive does not identify the expected workbook.")
    workbook = _workbook_metadata(package, "xl/workbook.xml")
    links = _workbook_metadata(package, "xl/_rels/workbook.xml.rels")
    worksheets = {
        rel.get("Id"): _xlsx_member_path("xl/workbook.xml", rel.get("Target", ""))
        for rel in links.iter(_RELATIONSHIP_TAG)
        if rel.get("Type") == f"{_OFFICE_REL_NS}/worksheet" and rel.get("TargetMode") != "External"
    }
    sheets = list(workbook.iter(_SHEET_TAG))
    if workbook.tag != f"{{{_SPREADSHEET_NS}}}workbook" or not sheets:
        raise ValueError("The archived workbook contains no worksheets.")
    for sheet in sheets:
        member = package.getinfo(worksheets[sheet.attrib[f"{{{_OFFICE_REL_NS}}}id"]])
        parser = ElementTree.XMLPullParser(events=("start",))
        with package.open(member) as data:
            parser.feed(data.read(16 * 1024))
        first = next(parser.read_events(), None)
        if (not member.filename.startswith("xl/worksheets/") or first is None
                or first[1].tag != f"{{{_SPREADSHEET_NS}}}worksheet"):
            raise ValueError("The archived workbook contains an invalid worksheet.")


def verified_archived_workbook(root: Path, receipt: Mapping) -> Path:
    """Return only the regular, digest-named XLSX verified against its receipt."""

    value = receipt.get("previous_result")
    if not isinstance(value, str) or not re.fullmatch(
        r"\.fpvs_imports/studio/prior-results/[0-9a-f]{64}\.xlsx", value,
    ):
        raise ValueError("The archived result has an invalid workbook path.")
    release = receipt.get("current_result") or {}
    released_hash = release.get("workbook_sha256") if isinstance(release, Mapping) else None
    expected = receipt.get("previous_result_sha256", released_hash)
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected) or (
        released_hash is not None and released_hash != expected
    ):
        raise ValueError("The archived workbook has no verifiable release checksum.")
    path = _managed_file(root, Path(value))
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("The archived workbook differs from its recorded checksum.")
        try:
            with ZipFile(stream) as package:
                _verify_workbook_package(package)
        except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("The archived result is not a readable XLSX workbook.") from exc
    return path
