"""Review a versioned Studio cohort before changing project or recording membership."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import UUID

from Main_App.io.file_filters import is_eeg_recording_file
from Main_App.projects.raw_identity import infer_raw_participant_id

FORMAT = "fpvs-study-handoff"
NAMESPACE = "studio_cohort"
_SHA = re.compile("[0-9a-f]{64}")


def digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate_study_handoff(source: Mapping[str, Any]) -> tuple[dict, dict]:
    from Main_App.projects.fpvs_config_import import FPVSConfigImportError, _import_setup

    if source.get("format") != FORMAT or type(source.get("format_version")) is not int or source["format_version"] != 1:
        raise FPVSConfigImportError("Unsupported whole-study handoff format. Export a supported version from Studio.")
    try:
        if str(UUID(source["study_id"])) != source["study_id"]:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise FPVSConfigImportError("Missing or invalid Studio source-study UUID.") from exc
    visits, setups = source.get("visits"), source.get("setups")
    if (not isinstance(visits, list) or not visits or not isinstance(setups, dict)
            or not isinstance(source.get("project_title"), str) or not source["project_title"].strip()
            or source.get("collection_complete") is not True
            or type(source.get("roster_sequence")) is not int or source["roster_sequence"] < 1
            or digest(visits) != source.get("roster_revision")):
        raise FPVSConfigImportError("Studio cohort has invalid collection status, roster revision, sequence or title.")
    identifiers = set()
    for visit in visits:
        if not isinstance(visit, dict) or not all(isinstance(visit.get(k), str) and visit[k].strip()
                                                  for k in ("visit_id", "participant_number", "state")):
            raise FPVSConfigImportError("A Studio visit lacks its source identity.")
        key = visit["visit_id"]
        if key in identifiers or visit.get("setup_id") is not None and visit["setup_id"] not in setups:
            raise FPVSConfigImportError("Duplicate Studio visit or missing referenced setup.")
        if visit.get("execution_id") is not None and key != visit["execution_id"]:
            raise FPVSConfigImportError("Studio visit and execution identity disagree.")
        number = visit.get("participant_session_number")
        if number is not None and (type(number) is not int or number < 1):
            raise FPVSConfigImportError("Invalid participant visit number.")
        if not isinstance(visit.get("issues"), list) or not isinstance(visit.get("runs"), list):
            raise FPVSConfigImportError("Studio visit is missing recorded evidence or review issues.")
        if any(not isinstance(reason, str) for reason in visit["issues"]):
            raise FPVSConfigImportError("Invalid Studio visit review issue.")
        if visit.get("protocol_version_id") is not None:
            try:
                UUID(visit["protocol_version_id"])
            except (ValueError, TypeError, AttributeError) as exc:
                raise FPVSConfigImportError("Invalid as-run protocol version identifier.") from exc
        electrodes = visit.get("manual_removed_electrodes")
        if electrodes is not None and (not isinstance(electrodes, list) or
                                      any(not isinstance(e, str) or not e.strip() for e in electrodes)):
            raise FPVSConfigImportError("Invalid electrode review in Studio visit.")
        if visit.get("recording") is not None and not isinstance(visit["recording"], dict):
            raise FPVSConfigImportError("Invalid Studio recording declaration.")
        if visit["state"] == "completed" and not visit["issues"]:
            if not visit.get("execution_id") or not visit.get("protocol_version_id") or not visit.get("recording") or not visit.get("setup_id"):
                raise FPVSConfigImportError("Completed visit lacks the evidence needed for a recording match.")
            runs = visit["runs"]
            setup_conditions = {c["condition_id"]: c["name"] for c in setups[visit["setup_id"]]["conditions"]}
            if (not runs or any(not isinstance(run, dict) or run.get("state") != "completed" or not run.get("run_id")
                                or setup_conditions.get(run.get("condition_id")) != run.get("condition_name") for run in runs)
                    or len({run["run_id"] for run in runs}) != len(runs)):
                raise FPVSConfigImportError("Completed visit lacks a consistent recorded condition order.")
        identifiers.add(key)
    if any(not isinstance(s, dict) or digest(s) != key or s.get("project", {}).get("project_id") != source.get("project_id")
           for key, s in setups.items()):
        raise FPVSConfigImportError("A captured study setup has a conflicting fingerprint or project.")
    scope = source.get("website_study")
    if scope is not None:
        fields = {"project_id", "experiment_id", "experiment_version", "protocol_sha256"}
        if (not isinstance(scope, dict) or set(scope) != fields or not all(isinstance(v, str) and v for v in scope.values())
                or not _SHA.fullmatch(scope["protocol_sha256"])):
            raise FPVSConfigImportError("Invalid website study identity.")
        try:
            UUID(scope["project_id"])
        except ValueError as exc:
            raise FPVSConfigImportError("Invalid website study UUID.") from exc
        for visit in visits:
            snapshot = setups.get(visit.get("setup_id"), {}).get("toolbox", {})
            if any(snapshot.get("study_id" if k == "project_id" else k) != v for k, v in scope.items()):
                raise FPVSConfigImportError("Website study destination conflicts with captured visit provenance.")
    errors = []
    for setup in setups.values():
        try:
            _import_setup(setup, Path("study.fpvsconfig"), b"")
            return setup, dict(source)
        except FPVSConfigImportError as exc:
            errors.append(str(exc))
    raise FPVSConfigImportError("No supported as-run setup can seed this project. " + " ".join(errors))


def _method(setup: dict) -> tuple:
    from Main_App.projects.fpvs_config_import import _import_setup

    result = _import_setup(setup, Path("study.fpvsconfig"), b"")
    return (result.event_map, result.frequency_protocol.to_manifest(), result.oddball_marker_code)


def version_key(visit: Mapping[str, Any]) -> str:
    return visit.get("protocol_version_id") or "Unrecorded version"


def _pid(value: str) -> str:
    match = re.fullmatch(r"(?:p|sub|s)?(\d+)", value, re.I)
    return str(int(match[1])) if match else value.casefold()


@dataclass(frozen=True)
class ReviewRow:
    visit: dict
    previous: dict
    candidates: tuple[str, ...]
    status: str
    change: str
    problem: str


@dataclass(frozen=True)
class StudyReview:
    rows: tuple[ReviewRow, ...]
    files: dict[str, tuple[int, int]]
    omitted: dict[str, dict]
    folder: Path
    baseline: str | None
    prior: dict


def review_study(imported, folder: Path, existing=None, *, hardware: str | None = None) -> StudyReview:
    """Compare visits, reviewed matches and currently present files without writing."""
    source = imported.provenance
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("Choose the folder containing the lab's EEG recordings.")
    previous = {}
    baseline = None
    if existing is not None:
        saved = (existing.project_root / "project.json").read_bytes()
        previous = json.loads(saved).get("tools", {}).get(NAMESPACE)
        if not previous:
            raise ValueError("The existing project has no verified Studio study identity.")
        baseline = hashlib.sha256(saved).hexdigest()
    if previous:
        if previous["study_id"] != source["study_id"]:
            raise ValueError("This analysis project belongs to a different Studio study.")
        if (source["roster_sequence"] < previous["roster_sequence"] or
                source["roster_sequence"] == previous["roster_sequence"] and source["roster_revision"] != previous["roster_revision"]):
            raise ValueError("This handoff predates or conflicts with the accepted roster. Export the latest study.")
    files = {}
    for path in sorted(folder.rglob("*")):
        if not is_eeg_recording_file(path) or not path.is_file():
            continue
        if not path.resolve().is_relative_to(folder):
            raise ValueError(f"Recording resolves outside the selected folder: {path.name}")
        stat = path.stat()
        files[path.relative_to(folder).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    by_pid: dict[str, list[str]] = {}
    for name in files:
        by_pid.setdefault(_pid(infer_raw_participant_id(name)), []).append(name)
    visits = source["visits"]
    counts = Counter(_pid(v["participant_number"]) for v in visits)
    prior_visits = previous.get("visits", {})
    prior_people = {v["participant_number"] for v in prior_visits.values()}
    rows = []
    for visit in visits:
        key = visit["visit_id"]
        prior = prior_visits.get(key, {})
        pid = _pid(visit["participant_number"])
        candidates = tuple(by_pid.get(pid, ()))
        change = "new" if not prior else "unchanged" if digest(visit) == prior["evidence_sha256"] else "changed"
        if change == "new" and previous:
            change = "additional visit" if visit["participant_number"] in prior_people else "new participant"
        reason = ""
        if not visit.get("setup_id") or not visit.get("participant_session_number") or visit["state"] != "completed" or visit["issues"]:
            reason = "Incomplete or unverified as-run evidence"
        elif hardware and _hardware(visit) != hardware:
            reason = f"Recorded hardware {_hardware(visit) or 'unknown'} differs from project hardware {hardware}"
        elif not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_-]*", visit["participant_number"]):
            reason = "Unsupported participant identifier"
        else:
            try:
                _method(source["setups"][visit["setup_id"]])
            except ValueError as exc:
                reason = str(exc)
        reviewed = prior.get("raw_file")
        stable_match = reviewed in files and tuple(prior.get("file_identity", ())) == files[reviewed] if reviewed else False
        if change == "unchanged" and (stable_match or prior.get("decision") in {"awaiting_eeg", "excluded"}):
            status = prior["decision"]
        elif reason:
            status = "exception"
        elif len(candidates) == 1 and counts[pid] == 1:
            status = "clear"
        else:
            status = "ambiguous" if candidates else "missing"
        rows.append(ReviewRow(visit, prior, candidates, status, change, reason))
    ids = {row.visit["visit_id"] for row in rows}
    omitted = {key: row for key, row in prior_visits.items() if key not in ids and row.get("in_source_roster", True)}
    return StudyReview(tuple(rows), files, omitted, folder, baseline, previous)


def _hardware(visit):
    return {"serial": "biosemi", "biosemi_active_three": "biosemi_active_three",
            "brainproducts_triggerbox": "brain_products", "brainproducts_parallel": "brain_products",
            "unicorn_udp": "unicorn"}.get((visit.get("recording") or {}).get("selected_backend"))


def find_study_project(projects_root: Path, study_id: str):
    from Main_App.projects.project import Project

    matches = []
    for path in Path(projects_root).glob("*/project.json"):
        if path.parent.name.startswith("."):
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("tools", {}).get(NAMESPACE, {}).get("study_id") == study_id:
            matches.append(path.parent)
    if len(matches) > 1:
        raise ValueError("Several Toolbox projects reference this study. Open the intended project before importing.")
    return Project.load(matches[0]) if matches else None


def _reviewed_state(imported, review, decisions, omissions, versions, warnings, hardware):
    source = imported.provenance
    if not versions or set(versions) - {version_key(r.visit) for r in review.rows}:
        raise ValueError("Select an experiment version present in the roster.")
    if len(versions) > 1 and tuple(warnings) != (True, True):
        raise ValueError("Mixing versions requires both comparability confirmations.")
    if set(omissions) != set(review.omitted) or any(v not in {"retain", "archive"} for v in omissions.values()):
        raise ValueError("Explicitly resolve each omitted visit before changing project membership.")
    matches = {}
    used = set()
    selected_setup = signature = None
    for row in review.rows:
        visit, key = row.visit, row.visit["visit_id"]
        decision, name = decisions.get(key, (None, None))
        if decision not in {"matched", "awaiting_eeg", "excluded"}:
            raise ValueError(f"Confirm a recording or explicitly defer visit {key}.")
        if decision == "excluded" and row.previous.get("decision") != "excluded":
            raise ValueError("Scientific exclusion is recorded during QC. Defer an unavailable recording.")
        entry = {
            "execution_id": visit.get("execution_id"), "participant_number": visit["participant_number"],
            "participant_session_number": visit.get("participant_session_number"),
            "protocol_version_id": visit.get("protocol_version_id"), "setup_id": visit.get("setup_id"),
            "manual_removed_electrodes": visit.get("manual_removed_electrodes"),
            "evidence_sha256": digest(visit), "decision": decision, "in_source_roster": True,
        }
        if decision == "matched":
            if row.problem or not name or name not in review.files or name in used:
                raise ValueError(f"Visit {key} requires a distinct reviewed recording and compatible evidence.")
            path = (review.folder / name).resolve(strict=True)
            stat = path.stat()
            if not path.is_relative_to(review.folder) or review.files[name] != (stat.st_size, stat.st_mtime_ns):
                raise ValueError("An EEG file changed after review. Review the roster again.")
            used.add(name)
            entry.update(raw_file=name, file_identity=list(review.files[name]),
                         recording_id="studio_" + hashlib.sha256(key.encode()).hexdigest()[:20])
            setup = source["setups"][visit["setup_id"]]
            recording = visit["recording"] or {}
            method = (_method(setup), recording.get("selected_backend"), recording.get("acquisition_profile"))
            entry["method_sha256"] = digest(method)
            if version_key(visit) in versions:
                platform = _hardware(visit)
                if platform != hardware or (path.suffix.casefold() == ".bdf") != (platform != "brain_products"):
                    raise ValueError(f"Recording hardware for {key} conflicts with the selected hardware or EEG file.")
                if signature is not None and method != signature:
                    raise ValueError("Selected versions have incompatible frequency, duration, marker or acquisition settings.")
                signature = method
                selected_setup = setup
        matches[key] = entry
    if selected_setup is None:
        for row in review.rows:
            if version_key(row.visit) in versions and not row.problem and row.visit.get("setup_id"):
                selected_setup = source["setups"][row.visit["setup_id"]]
                recording = row.visit["recording"]
                signature = (_method(selected_setup), recording.get("selected_backend"), recording.get("acquisition_profile"))
                break
        if selected_setup is None:
            raise ValueError("The selected version has no supported as-run setup for this project.")
    for key, entry in review.prior.get("visits", {}).items():
        if key not in matches and not entry.get("in_source_roster", True):
            matches[key] = deepcopy(entry)
    for key, decision in omissions.items():
        prior = deepcopy(review.omitted[key])
        prior["in_source_roster"] = False
        if decision == "archive":
            prior["decision"] = "archived"
        matches[key] = prior
    if any(v["decision"] == "matched" and version_key(v) in versions and v.get("method_sha256") != digest(signature)
           for v in matches.values()):
        raise ValueError("Retained visits use a method incompatible with the selected analysis.")
    if sum(r.get("raw_file") is not None and r["decision"] == "matched" for r in matches.values()) != len(
            {r["raw_file"] for r in matches.values() if r["decision"] == "matched"}):
        raise ValueError("A retained visit already owns this EEG recording.")
    state = {
        **({"website_study": dict(source["website_study"])} if source.get("website_study") else {}),
        "study_id": source["study_id"], "roster_revision": source["roster_revision"],
        "roster_sequence": source["roster_sequence"], "raw_folder": str(review.folder),
        "versions": sorted(versions), "mixed_version_confirmations": list(warnings) if len(versions) > 1 else [],
        "visits": matches, "source_sha256": imported.source_sha256,
    }
    return state, selected_setup


def selected_recording_ids(manifest: Mapping[str, Any] | None) -> set[str] | None:
    cohort = (manifest or {}).get("tools", {}).get(NAMESPACE)
    if cohort is None:
        return None
    return {
        row["recording_id"] for row in cohort["visits"].values() if row["decision"] == "matched"
        and version_key(row) in cohort["versions"]
    }


def commit_study_review(projects_root, imported, review, *, decisions, omissions, versions,
                        warnings=(), hardware, existing=None, group_assignments=None):
    """Publish exactly the reviewed change, preserving source files and older receipts."""
    from Main_App.io.atomic_write import rename_with_retry
    from Main_App.projects.fpvs_config_import import _create_imported_project, _unique_project_root
    from Main_App.projects.project import Project

    if review_study(imported, review.folder, existing, hardware=hardware).files != review.files:
        raise ValueError("The EEG folder changed after review. Reopen the roster to check its matches.")
    state, setup = _reviewed_state(imported, review, decisions, omissions, versions, warnings, hardware)
    if existing:
        return _publish(existing.project_root, imported, review, state, setup, hardware, group_assignments or {})
    root = Path(projects_root).resolve()
    root.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(prefix=".studio-import-", dir=root) as staging:
        work = Path(staging) / "project"
        work.mkdir()
        _create_imported_project(work, imported)
        _publish(work, imported, review, state, setup, hardware, {})
        from Main_App.projects.manifest_store import project_manifest_transaction
        with project_manifest_transaction(root / f".studio-import-{state['study_id']}"):
            if find_study_project(root, state["study_id"]) is not None:
                raise ValueError("This study was imported during review. Reopen it to update the existing project.")
            destination = _unique_project_root(root, imported.project_title)
            rename_with_retry(work, destination)
    return Project.load(destination)


def _register_reviewed_visits(manifest, current, state, folder, group_assignments):
    groups = manifest["groups"]
    sessions = manifest.setdefault("sessions", {})
    sources = manifest.setdefault("recording_sources", {})
    recordings = manifest.setdefault("recordings", {})
    participants = manifest.setdefault("participants", {})
    session_ids = {info["visit_index"]: key for key, info in sessions.items()}
    source_ids = {(info["group_id"], info["session_id"]): key for key, info in sources.items()}
    previous_visits = (current.manifest.get("tools", {}).get(NAMESPACE) or {}).get("visits", {})
    for key, visit in state["visits"].items():
        index = visit["participant_session_number"]
        if index is None:
            continue
        session = session_ids.setdefault(index, f"visit{index}")
        sessions.setdefault(session, {"label": f"Visit {index}", "visit_index": index})
        if visit["decision"] != "matched":
            continue
        existing_recording = current.recordings.get(visit["recording_id"], {})
        pid = visit["participant_number"]
        if previous_visits.get(key, {}).get("participant_number") == pid:
            pid = existing_recording.get("participant_id", pid)
        participant = participants.setdefault(pid, {})
        group = current.participants.get(pid, {}).get("group_id") or group_assignments.get(pid)
        if not group and len(groups) == 1:
            group = next(iter(groups))
        if group not in groups:
            raise ValueError(f"Select a canonical project group for participant {pid}.")
        participant["group_id"] = group
        source = source_ids.get((group, session))
        if not source:
            source = session if session not in sources else f"{group}__{session}"
            if source in sources:
                raise ValueError(f"Recording source ID {source} already identifies another group or session.")
            source_ids[group, session] = source
            sources[source] = {"session_id": session, "group_id": group, "raw_input_folder": str(folder),
                               "reviewed_files_only": True}
        recording = recordings.setdefault(visit["recording_id"], {})
        recording.update(participant_id=pid, visit_index=index, session_id=session,
                         source_id=source, raw_file=str(folder / visit["raw_file"]))


def _publish(root, imported, review, state, setup, hardware, group_assignments):
    from Main_App.io.atomic_write import atomic_write, replace_with_retry
    from Main_App.processing.raw_registration_state import registration_tool_updates
    from Main_App.projects.fpvs_config_import import _import_setup
    from Main_App.projects.hardware import confirm_hardware_selection
    from Main_App.projects.manifest_store import project_manifest_transaction
    from Main_App.projects.project import Project, REPEATED_SESSION_PROJECT_SCHEMA_VERSION, _recordings_lock_fingerprint

    path = root / "project.json"
    with project_manifest_transaction(path) as transaction:
        current_bytes = path.read_bytes()
        if review.baseline and hashlib.sha256(current_bytes).hexdigest() != review.baseline:
            raise ValueError("Project changed after review. Reopen the whole-study handoff.")
        manifest = json.loads(current_bytes)
        previous = manifest.get("tools", {}).get(NAMESPACE, {})
        if previous and all(previous.get(key) == value for key, value in state.items()):
            return Project.load(root)
        current = Project(root, manifest)
        registry = manifest.setdefault("tools", {})
        history = list(previous.get("history", ()))
        if previous:
            receipt = {k: v for k, v in previous.items() if k != "history"}
            history.append(receipt)
            state["previous_processing_run"] = previous.get("current_result", {}).get(
                "processing_run_id", previous.get("previous_processing_run"))
        state["history"] = history
        if not previous:
            manifest["groups"] = {"cohort": {"label": "Study cohort", "folder_name": "Cohort",
                                              "raw_input_folder": str(review.folder)}}
            manifest["preprocessing"] = confirm_hardware_selection(current.preprocessing, hardware, confirmed_change=True)
        method_sha256 = digest(_method(setup))
        if not previous or previous.get("method_sha256") != method_sha256:
            scientific = _import_setup(setup, Path(imported.source_filename), b"")
            if previous and current.frequency_protocol.condition_trigger_maps is not None:
                raise ValueError("The revised method requires review of this project's source-specific trigger maps.")
            manifest.update(event_map=scientific.event_map, frequency_protocol=scientific.frequency_protocol.to_manifest())
        state["method_sha256"] = method_sha256
        _register_reviewed_visits(manifest, current, state, review.folder, group_assignments)
        registry[NAMESPACE] = state
        manifest["schema_version"] = REPEATED_SESSION_PROJECT_SCHEMA_VERSION
        # The original locked graph was validated above. Validate the amended graph in canonical path form.
        candidate = deepcopy(manifest)
        candidate.pop("recordings_lock_fingerprint", None)
        registered = Project(root, candidate)
        if current.groups_locked:
            manifest["recordings_lock_fingerprint"] = _recordings_lock_fingerprint(
                registered.sessions, registered.recording_sources, registered.recordings)
        active = sorted(selected_recording_ids(manifest))
        if previous:
            registry.update(registration_tool_updates(root, active, revised_cohort=True))
            prior_result = _preserve_reviewed_result(root, previous)
            if prior_result:
                history[-1]["previous_result"] = prior_result
        evidence = root / ".fpvs_imports" / "studio" / f"{imported.source_sha256}.json"
        if not evidence.exists():
            evidence.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write(evidence, replace=replace_with_retry) as stream:
                json.dump({"source_filename": imported.source_filename, "source_sha256": imported.source_sha256,
                           "handoff": imported.provenance}, stream, ensure_ascii=False, allow_nan=False)
        transaction.write(manifest)
    return Project.load(root)


def _preserve_reviewed_result(root: Path, previous: Mapping[str, Any]) -> str | None:
    from shutil import copyfileobj
    from Main_App.io.atomic_write import atomic_write
    from Main_App.processing.artifact_freshness import (
        ANALYSIS_READY_FULL_AUDIT_ARTIFACT, StalePostProcessingArtifactError,
        canonical_artifact_path, require_current_artifact,
    )
    original = canonical_artifact_path(root, ANALYSIS_READY_FULL_AUDIT_ARTIFACT)
    try:
        require_current_artifact(root, ANALYSIS_READY_FULL_AUDIT_ARTIFACT, original)
    except StalePostProcessingArtifactError:
        return None
    coverage = digest({k: v for k, v in previous.items() if k != "history"})
    destination = root / ".fpvs_imports" / "studio" / "prior-results" / f"{coverage}.xlsx"
    destination.parent.mkdir(exist_ok=True, parents=True)
    if not destination.exists():
        with original.open("rb") as source, atomic_write(destination, binary=True) as target:
            copyfileobj(source, target)
    return destination.relative_to(root).as_posix()


def _released_result(root, workbook_path, manifest):
    from Main_App.processing.artifact_freshness import (
        ANALYSIS_READY_FULL_AUDIT_ARTIFACT, require_current_artifact,
    )
    from Main_App.processing.roi_coverage import require_project_final_release
    from Main_App.processing.recording_condition_outcomes import CELL_EXCLUDED
    state = manifest["tools"][NAMESPACE]
    workbook = Path(workbook_path).resolve(strict=True)
    require_current_artifact(root, ANALYSIS_READY_FULL_AUDIT_ARTIFACT, workbook)
    outcome, coverage, release = require_project_final_release(root)
    selected = selected_recording_ids(manifest)
    if {c.recording_id for c in coverage.cells} != selected or outcome.expected_plan_run_id == state.get("previous_processing_run"):
        raise ValueError("Run Processing and analysis for this reviewed cohort before releasing the new result.")
    included_ids = {cell.recording_id for cell in coverage.cells if cell.source_evidence is not None
                    and not cell.downstream_cell_excluded}
    unavailable_ids = {cell.recording_id for cell in coverage.cells if cell.source_evidence is None
                       and cell.outcome_status != CELL_EXCLUDED and not cell.downstream_cell_excluded}
    accepted = {key: r for key, r in state["visits"].items() if r.get("recording_id") in selected}
    with workbook.open("rb") as stream:
        fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "roster_revision": state["roster_revision"], "roster_sequence": state["roster_sequence"],
        "versions": state["versions"], "mixed_version_confirmations": state["mixed_version_confirmations"],
        "included": sorted(k for k, r in accepted.items() if r["recording_id"] in included_ids),
        "excluded": sorted(k for k, r in accepted.items() if r["recording_id"] not in included_ids | unavailable_ids),
        "unavailable": sorted(k for k, r in accepted.items() if r["recording_id"] in unavailable_ids - included_ids),
        "awaiting_eeg": sorted(k for k, r in state["visits"].items() if r["decision"] == "awaiting_eeg"),
        "processing_run_id": outcome.expected_plan_run_id, "release_fingerprint": release.fingerprint,
        "workbook": workbook.relative_to(root.resolve()).as_posix(), "workbook_sha256": fingerprint,
    }


def require_current_study_result(root: Path, workbook: Path, manifest: Mapping | None) -> None:
    """Check a downstream workbook against the reviewed cohort and still-active release."""
    state = (manifest or {}).get("tools", {}).get(NAMESPACE)
    if state is not None and (not state.get("current_result") or
                              state["current_result"] != _released_result(root, workbook, manifest)):
        raise ValueError("Run Processing and analysis for the reviewed cohort before using these results.")


def record_current_result(project_root: Path, workbook_path: Path) -> None:
    """Bind a verified released workbook to the exact reviewed study and processing run."""
    from Main_App.projects.manifest_store import project_manifest_transaction
    root = Path(project_root)
    manifest_path = root / "project.json"
    with project_manifest_transaction(manifest_path) as tx:
        manifest = json.loads(manifest_path.read_bytes())
        state = manifest.get("tools", {}).get(NAMESPACE)
        if state is None:
            return
        verified = _released_result(root, workbook_path, manifest)
        if verified != state.get("current_result"):
            state["current_result"] = verified
            tx.write(manifest)
