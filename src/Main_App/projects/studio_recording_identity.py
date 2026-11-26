"""Look up the exact BrainVision source bytes approved for a Studio visit."""

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re


STUDIO_SOURCE_APPROVALS_KEY = "_fpvs_studio_source_sha256"
_SHA256 = re.compile("[0-9a-f]{64}")


def studio_source_path_key(path: Path | str) -> str:
    # Snapshot and look up approvals without accessing the recording on the GUI thread.
    return os.path.normcase(os.path.abspath(path))


def studio_source_approvals(manifest: Mapping | None) -> dict[str, dict]:
    if not isinstance(manifest, Mapping):
        return {}
    cohort = (manifest.get("tools") or {}).get("studio_cohort")
    if not cohort:
        return {}
    from Main_App.projects.studio_cohort import version_key

    approvals = {}
    for visit in cohort["visits"].values():
        if visit.get("decision") != "matched" or version_key(visit) not in cohort["versions"]:
            continue
        path = Path(cohort["raw_folder"]) / visit["raw_file"]
        if path.suffix.lower() not in {".vhdr", ".bvrh"}:
            continue
        # A hashless historical approval must be distinguished from an ordinary lab recording.
        reviewed = visit.get("source_sha256_by_file")
        hashes = dict(reviewed) if isinstance(reviewed, Mapping) else {}
        approvals[studio_source_path_key(path)] = hashes
        sources = visit.get("recording_sources")
        if isinstance(sources, list) and sources and isinstance(sources[0], dict) and sources[0].get("path"):
            approvals[studio_source_path_key(sources[0]["path"])] = hashes
    return approvals


def read_project_studio_source_approvals(project_root: Path) -> dict[str, dict]:
    """Resolve headless BrainVision admission when no in-memory project snapshot was supplied."""
    from Main_App.projects.manifest_store import manifest_file_path

    manifest_path = manifest_file_path(project_root / "project.json")
    try:
        with manifest_path.open(encoding="utf-8-sig") as stream:
            manifest = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(manifest, dict):
        raise ValueError("Cannot verify the reviewed recording against an invalid project manifest.")
    return studio_source_approvals(manifest)


def require_studio_source_hashes(hashes: object) -> dict[str, str]:
    if (not isinstance(hashes, dict) or len(hashes) < 3
            or any(not isinstance(path, str) or not os.path.isabs(path)
                   or not isinstance(value, str) or not _SHA256.fullmatch(value) for path, value in hashes.items())):
        raise ValueError("Review the Studio cohort again to confirm the complete recording and its companions.")
    return hashes


def studio_source_approval(approvals: Mapping | None, file_path: Path | str) -> dict[str, str] | None:
    if not approvals or Path(file_path).suffix.lower() not in {".vhdr", ".bvrh"}:
        return None
    key = studio_source_path_key(file_path)
    if key not in approvals:
        key = studio_source_path_key(Path(file_path).resolve())
    return require_studio_source_hashes(approvals[key]) if key in approvals else None
