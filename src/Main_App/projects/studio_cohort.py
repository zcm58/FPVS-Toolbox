"""Review a versioned Studio cohort before changing project or recording membership."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from copy import deepcopy
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import UUID

from Main_App.io.file_filters import is_eeg_recording_file
from Main_App.io.recording_sources import bdf_change_identity, companion_identity, recording_content_identity, source_hashes_by_file
from Main_App.projects.raw_identity import infer_raw_participant_id
from Main_App.projects.studio_archive import archive_reviewed_result, studio_evidence_path
from Main_App.projects.studio_handoff import (
    STUDIO_MARKER_DIAGNOSTICS, STUDIO_RECORDER_PLATFORMS, StudioRecordingSelection, studio_recording_selection,
    validate_studio_marker_code_map,
)

FORMAT = "fpvs-study-handoff"
NAMESPACE = "studio_cohort"
_SHA = re.compile("[0-9a-f]{64}")
logger = logging.getLogger(__name__)


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
            or not isinstance(source.get("project_id"), str) or not source["project_id"].strip()
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
            if (not runs or any(not isinstance(run, dict) or run.get("state") != "completed"
                                or not isinstance(run.get("run_id"), str) or not run["run_id"].strip()
                                or run.get("condition_id") not in setup_conditions
                                or setup_conditions.get(run.get("condition_id")) != run.get("condition_name") for run in runs)
                    or len({run["run_id"] for run in runs}) != len(runs)):
                raise FPVSConfigImportError("Completed visit lacks a consistent recorded condition order.")
        identifiers.add(key)
    if any(not isinstance(s, dict) or digest(s) != key or s.get("project", {}).get("project_id") != source.get("project_id")
           for key, s in setups.items()):
        raise FPVSConfigImportError("A captured study setup has a conflicting fingerprint or project.")
    recorded = {(visit.get("recording") or {}).get("selected_backend") for visit in visits
                if visit["state"] == "completed" and not visit["issues"]}
    if recorded and recorded.issubset(STUDIO_MARKER_DIAGNOSTICS):
        raise FPVSConfigImportError(" ".join(STUDIO_MARKER_DIAGNOSTICS[backend] for backend in sorted(recorded)))
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


def _visit_selection(source, visit) -> StudioRecordingSelection | None:
    return studio_recording_selection(source["setups"][visit["setup_id"]], as_run=visit.get("recording") or {})


def _validate_run_markers(run, condition_code, oddball_code, condition):
    """Reconcile the compact as-run marker records when a Studio roster carries them."""
    expected = {"condition_start": condition_code, "oddball_onset": oddball_code}
    problem = f"Studio marker evidence for {run['condition_name']} ({run['run_id']})"
    sequences, repeats = condition.get("sequence_count"), condition.get("oddball_cycle_repeats_per_sequence")
    expected_count = 1 + sequences * repeats if type(sequences) is int and type(repeats) is int else None
    for key in ("planned_event_count", "sent_events", "error_events"):
        if key in run and (type(run[key]) is not int or run[key] < 0):
            raise ValueError(f"{problem} has an invalid {key}.")
    if expected_count is not None and any(
        run[k] != expected_count for k in ("planned_event_count", "sent_events") if k in run
    ):
        raise ValueError(f"{problem} has a marker count that conflicts with the captured condition.")
    if run.get("error_events") or ("sent_events" in run and "planned_event_count" in run
                                  and run["sent_events"] != run["planned_event_count"]):
        raise ValueError(f"{problem} reports missing or failed sends.")
    declared = validate_studio_marker_code_map(run["code_map"], expected, problem) if "code_map" in run else None
    for key in ("planned_markers", "attempted_markers"):
        if key not in run:
            continue
        markers = run[key]
        if (not isinstance(markers, list) or not markers
                or (expected_count is not None and len(markers) != expected_count)
                or any(len(markers) != run[k] for k in ("planned_event_count", "sent_events") if k in run)):
            raise ValueError(f"{problem} has an incomplete {key} list.")
        last_frame, last_time = -1, 0
        last_index = None
        attempted = key == "attempted_markers"
        for i, marker in enumerate(markers):
            if not isinstance(marker, list) or len(marker) != (6 if attempted else 3):
                raise ValueError(f"{problem} has an invalid {key} entry.")
            if attempted:
                index, frame, code, label, elapsed, status = marker
                if (type(index) is not int or index < 0 or (last_index is not None and index != last_index + 1)
                        or status != "sent"):
                    raise ValueError(f"{problem} has a failed or out-of-order marker attempt.")
                last_index = index
                if elapsed is not None:
                    if (type(elapsed) not in (int, float) or (type(elapsed) is float and not math.isfinite(elapsed))
                            or elapsed < last_time):
                        raise ValueError(f"{problem} has an invalid or out-of-order callback time.")
                    last_time = elapsed
            else:
                frame, code, label = marker
            role = "condition_start" if i == 0 else "oddball_onset"
            if (type(frame) is not int or frame <= last_frame or type(code) is not int or label != role
                    or code != expected[role] or (declared is not None and role not in declared)):
                raise ValueError(f"{problem} has a {key} entry inconsistent with the captured condition.")
            last_frame = frame
    if "planned_markers" in run and "attempted_markers" in run:
        planned, attempted = run["planned_markers"], run["attempted_markers"]
        if len(planned) != len(attempted) or any(p != a[1:4] for p, a in zip(planned, attempted)):
            raise ValueError(f"{problem} has sends that differ from its planned marker sequence.")


def study_recording_consensus(source) -> tuple[str | None, StudioRecordingSelection | None]:
    """Resolve recorder and montage agreement independently across captured visits."""
    selections = set()
    for visit in source["visits"]:
        if visit["state"] == "completed" and not visit["issues"] and visit.get("setup_id"):
            try:
                selection = _visit_selection(source, visit)
            except ValueError:
                return None, None  # The review row reports the conflicting capture.
            if selection is None:
                return None, None
            selections.add(selection)
    platforms = {selection.platform for selection in selections}
    return (platforms.pop() if len(platforms) == 1 else None,
            selections.pop() if len(selections) == 1 else None)


def _visit_method(source, visit):
    recording = visit["recording"] or {}
    method = (_method(source["setups"][visit["setup_id"]]), recording.get("selected_backend"),
              recording.get("acquisition_profile"))
    selection = _visit_selection(source, visit)
    # Retained visits from historical rosters already use the three-field digest.
    return (*method, selection.montage) if selection else method


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
    files: dict[str, dict]
    omitted: dict[str, dict]
    folder: Path
    baseline: str | None
    prior: dict
    unreadable: dict[str, str] = field(default_factory=dict)
    source_sha256: str = ""
    existing_root: Path | None = None
    signal_ids: dict = field(default_factory=dict)


def _recording_inventory(folder: Path, *, hash_names: set[str] | None = None):
    files, unreadable, signal_ids = {}, {}, {}
    for path in sorted(folder.rglob("*")):
        if not is_eeg_recording_file(path) or not path.is_file():
            continue
        if not path.resolve().is_relative_to(folder):
            raise ValueError(f"Recording resolves outside the selected folder: {path.name}")
        name = path.relative_to(folder).as_posix()
        try:
            if path.suffix.lower() in {".vhdr", ".bvrh"} and (hash_names is None or name in hash_names):
                members = recording_content_identity(path)
                components = {
                    "recording_sources": [{k: v for k, v in row.items() if k != "sha256"} for row in members],
                    "source_sha256_by_file": source_hashes_by_file(members),
                }
            else:
                components = companion_identity(path)
            if components:
                header = components["recording_sources"][0]
                identity = [header["size"], header["mtime_ns"]]
                signal = Path(components["recording_sources"][1]["path"])
                stat = signal.stat()
            else:
                signal = path
                stat = path.stat()
                identity = [stat.st_size, stat.st_mtime_ns]
                if hash_names is None or name in hash_names:
                    components["bdf_change_identity"] = bdf_change_identity(path, stat)
            signal_ids[name] = (stat.st_dev, stat.st_ino) if stat.st_ino else signal.resolve()
        except (OSError, ValueError) as exc:
            unreadable[name] = str(exc)
            continue
        files[name] = {"file_identity": identity, **components}
    return files, unreadable, signal_ids


def _same_reviewed_recording(visit: Mapping, files: Mapping) -> bool:
    current = files.get(visit.get("raw_file"))
    return current is not None and all(visit.get(k) == v for k, v in current.items())


def _retained_recording_needs_review(visit: Mapping, files: Mapping, same_folder: bool) -> bool:
    return visit.get("decision") == "matched" and (not same_folder or not _same_reviewed_recording(visit, files))


def _compatible_recording(name: str, platform: str | None) -> bool:
    suffix = Path(name).suffix.casefold()
    return suffix in {".vhdr", ".bvrh"} if platform == "brain_products" else (
        platform in {"biosemi", "biosemi_active_three", "unicorn"} and suffix == ".bdf"
    )


def _accepted_project_id(previous, imported, root):
    if "project_id" in previous:
        return previous["project_id"]
    # Projects created before the manifest kept this field still retain the source export.
    original = next(iter(previous.get("history", ())), previous)
    if original["source_sha256"] == imported.source_sha256:
        return imported.provenance["project_id"]
    try:
        evidence = json.loads(studio_evidence_path(root, original["source_sha256"]).read_bytes())
        if (evidence["source_sha256"] == original["source_sha256"]
                and evidence["handoff"]["study_id"] == previous["study_id"]):
            return evidence["handoff"]["project_id"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise ValueError("Restore the accepted Studio study export before reviewing a different handoff.")


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
        if _accepted_project_id(previous, imported, existing.project_root) != source["project_id"]:
            raise ValueError("The revised study names a different Studio project.")
        if (source["roster_sequence"] < previous["roster_sequence"] or
                source["roster_sequence"] == previous["roster_sequence"] and source["roster_revision"] != previous["roster_revision"]):
            raise ValueError("This handoff predates or conflicts with the accepted roster. Export the latest study.")
    files, unreadable, signal_ids = _recording_inventory(folder)
    signal_counts = Counter(signal_ids.values())
    by_pid: dict[str, list[str]] = {}
    for name in files:
        by_pid.setdefault(_pid(infer_raw_participant_id(name)), []).append(name)
    visits = source["visits"]
    counts = Counter(_pid(v["participant_number"]) for v in visits)
    prior_visits = previous.get("visits", {})
    matched_signals = Counter(signal_ids[v["raw_file"]] for v in prior_visits.values()
                              if v["decision"] == "matched" and v.get("raw_file") in signal_ids)
    overlapping = {key for key, v in prior_visits.items() if v["decision"] == "matched"
                   and matched_signals[signal_ids.get(v.get("raw_file"))] > 1}
    same_folder = bool(previous) and Path(previous["raw_folder"]) == folder
    prior_people = {v["participant_number"] for v in prior_visits.values()}
    methods = {}
    rows = []
    for visit in visits:
        key = visit["visit_id"]
        prior = prior_visits.get(key, {})
        if prior.get("execution_id") and any(
            prior.get(field) is not None and prior[field] != visit.get(field)
            for field in ("participant_number", "participant_session_number")
        ):
            raise ValueError(f"Studio execution {key} changed participant or visit number. Check the source roster.")
        pid = _pid(visit["participant_number"])
        platform = _hardware(visit)
        candidates = tuple(name for name in by_pid.get(pid, ()) if _compatible_recording(name, platform))
        change = "new" if not prior else "unchanged" if digest(visit) == prior["evidence_sha256"] else "changed"
        if change == "new" and previous:
            change = "additional visit" if visit["participant_number"] in prior_people else "new participant"
        reason = ""
        if not visit.get("setup_id") or not visit.get("participant_session_number") or visit["state"] != "completed" or visit["issues"]:
            reason = "Incomplete or unverified as-run evidence"
        elif not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_-]*", visit["participant_number"]):
            reason = "Unsupported participant identifier"
        else:
            try:
                setup_id = visit["setup_id"]
                if setup_id not in methods:
                    setup = source["setups"][setup_id]
                    methods[setup_id] = _method(setup), {c["condition_id"]: c for c in setup["conditions"]}
                (event_map, _, oddball), conditions = methods[setup_id]
                selection = _visit_selection(source, visit)
                for run in visit["runs"]:
                    _validate_run_markers(run, event_map[run["condition_name"].strip()], oddball, conditions[run["condition_id"]])
                if hardware and platform != hardware:
                    reason = f"Recorded hardware {platform or 'unknown'} differs from project hardware {hardware}"
                elif selection and existing and not selection.matches(existing.preprocessing):
                    reason = f"Studio montage {selection.label} conflicts with the current project recording settings."
            except ValueError as exc:
                reason = str(exc)
        stable_match = same_folder and _same_reviewed_recording(prior, files)
        if key in overlapping and not reason:
            status = "ambiguous"
        elif change == "unchanged" and ((stable_match and not reason) or prior.get("decision") in {"awaiting_eeg", "excluded"}):
            status = prior["decision"]
        elif reason:
            status = "exception"
        elif prior.get("decision") == "matched" and not stable_match:
            status = "reconfirm_recording"
        elif len(candidates) == 1 and counts[pid] == 1 and signal_counts[signal_ids[candidates[0]]] == 1:
            status = "clear"
        else:
            status = "ambiguous" if candidates else "missing"
        rows.append(ReviewRow(visit, prior, candidates, status, change, reason))
    ids = {row.visit["visit_id"] for row in rows}
    omitted = {key: row for key, row in prior_visits.items() if key not in ids and (
        row.get("in_source_roster", True) or key in overlapping or _retained_recording_needs_review(row, files, same_folder))}
    return StudyReview(tuple(rows), files, omitted, folder, baseline, previous, unreadable,
                       imported.source_sha256, existing.project_root if existing is not None else None, signal_ids)


def _hardware(visit):
    selected = (visit.get("recording") or {}).get("selected_backend")
    return STUDIO_RECORDER_PLATFORMS.get(selected) if isinstance(selected, str) else None


def find_study_project(projects_root: Path, study_id: str, *, warnings: list[str] | None = None):
    from Main_App.projects.project import Project

    matches = []
    failures = []
    root = Path(projects_root)
    if not root.exists():
        return None
    for sibling in root.iterdir():
        if sibling.name.startswith("."):
            continue
        path = sibling / "project.json"
        try:
            if not sibling.is_dir():
                continue
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            tools = payload.get("tools", {}) if isinstance(payload, dict) else None
            cohort = tools.get(NAMESPACE, {}) if isinstance(tools, dict) else None
            if not isinstance(cohort, dict):
                raise ValueError("Invalid project or Studio cohort metadata.")
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            message = f"Could not check Studio study identity in {path}: {exc}"
            logger.warning("%s", message)
            failures.append(message)
            continue
        if cohort.get("study_id") == study_id:
            matches.append(path.parent)
    if len(matches) > 1:
        raise ValueError("Several Toolbox projects reference this study. Open the intended project before importing.")
    if warnings is not None:
        warnings.extend(failures)
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
    selected_setup = selection = signature = None
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
            if not path.is_relative_to(review.folder):
                raise ValueError("An EEG file changed after review. Review the roster again.")
            used.add(name)
            entry.update(raw_file=name, **review.files[name],
                         recording_id="studio_" + hashlib.sha256(key.encode()).hexdigest()[:20])
            setup = source["setups"][visit["setup_id"]]
            method = _visit_method(source, visit)
            entry["method_sha256"] = digest(method)
            platform = _hardware(visit)
            if not _compatible_recording(name, platform):
                raise ValueError(f"Recording hardware for {key} conflicts with the EEG file format.")
            if version_key(visit) in versions:
                if platform != hardware:
                    raise ValueError(f"Recording hardware for {key} conflicts with the selected hardware.")
                if signature is not None and method != signature:
                    raise ValueError("Selected versions have incompatible frequency, duration, marker or acquisition settings.")
                signature = method
                selected_setup = setup
                selection = _visit_selection(source, visit)
        matches[key] = entry
    if selected_setup is None:
        for row in review.rows:
            if version_key(row.visit) in versions and not row.problem and row.visit.get("setup_id"):
                if _hardware(row.visit) != hardware:
                    raise ValueError("Selected visit hardware conflicts with the project recording system.")
                method = _visit_method(source, row.visit)
                if selected_setup is None:
                    selected_setup = source["setups"][row.visit["setup_id"]]
                    selection = _visit_selection(source, row.visit)
                    signature = method
                elif method != signature:
                    raise ValueError("Selected visits have incompatible frequency, duration, marker or acquisition settings.")
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
        elif _retained_recording_needs_review(prior, review.files, Path(review.prior["raw_folder"]) == review.folder):
            raise ValueError(f"The recording for omitted visit {key} differs from its approval. "
                             "Archive the previous membership or import a roster that includes the visit for review.")
        matches[key] = prior
    if any(v["decision"] == "matched" and version_key(v) in versions and v.get("method_sha256") != digest(signature)
           for v in matches.values()):
        raise ValueError("Retained visits use a method incompatible with the selected analysis.")
    selected_signals = [review.signal_ids[r["raw_file"]] for r in matches.values() if r["decision"] == "matched"]
    if len(selected_signals) != len(set(selected_signals)):
        raise ValueError("The same EEG signal cannot be matched to multiple Studio visits, including retained visits.")
    state = {
        **({"website_study": dict(source["website_study"])} if source.get("website_study") else {}),
        "study_id": source["study_id"], "project_id": source["project_id"], "roster_revision": source["roster_revision"],
        "roster_sequence": source["roster_sequence"], "raw_folder": str(review.folder),
        "versions": sorted(versions), "mixed_version_confirmations": list(warnings) if len(versions) > 1 else [],
        "visits": matches, "source_sha256": imported.source_sha256,
    }
    return state, selected_setup, selection


def selected_recording_ids(manifest: Mapping[str, Any] | None) -> set[str] | None:
    cohort = (manifest or {}).get("tools", {}).get(NAMESPACE)
    if cohort is None:
        return None
    return {
        row["recording_id"] for row in cohort["visits"].values() if row["decision"] == "matched"
        and version_key(row) in cohort["versions"]
    }


def commit_study_review(projects_root, imported, review, *, decisions, omissions, versions,
                        warnings=(), hardware=None, existing=None, group_assignments=None, accepted_unreadable=()):
    """Publish exactly the reviewed change, preserving source files and older receipts."""
    from Main_App.io.atomic_write import rename_with_retry
    from Main_App.projects.fpvs_config_import import _create_imported_project, _unique_project_root
    from Main_App.projects.project import Project

    if review.source_sha256 != imported.source_sha256 or review.existing_root != (
        existing.project_root if existing is not None else None
    ):
        raise ValueError("This review belongs to a different Studio export or Toolbox project. Reopen the roster.")
    if hardware is None:
        if existing:
            hardware = existing.preprocessing["hardware_platform"]
        elif imported.study_recording_platform:
            hardware = imported.study_recording_platform
        else:
            raise ValueError("Select the project recording system for this study.")
    hash_names = {name for decision, name in decisions.values() if decision == "matched"}
    present = {row.visit["visit_id"] for row in review.rows}
    hash_names.update(visit["raw_file"] for key, visit in review.prior.get("visits", {}).items()
                      if key not in present and visit["decision"] == "matched" and omissions.get(key) != "archive")
    files, _, signal_ids = _recording_inventory(review.folder, hash_names=hash_names)
    if files.keys() != review.files.keys() or any(signal_ids.get(k) != review.signal_ids.get(k) for k in hash_names) or any(
        any(review.files[name].get(k) != v for k, v in current.items()) for name, current in files.items()
    ):
        raise ValueError("The EEG folder changed after review. Reopen the roster to check its matches.")
    state, setup, selection = _reviewed_state(imported, review, decisions, omissions, versions, warnings, hardware)
    if existing:
        return _publish(existing.project_root, imported, review, state, setup, hardware, group_assignments or {}, selection)
    root = Path(projects_root).resolve()
    root.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(prefix=".studio-import-", dir=root) as staging:
        work = Path(staging) / "project"
        work.mkdir()
        _create_imported_project(work, replace(imported, recording_selection=selection))
        _publish(work, imported, review, state, setup, hardware, {}, selection)
        from Main_App.projects.manifest_store import project_manifest_transaction
        with project_manifest_transaction(root / f".studio-import-{state['study_id']}"):
            unreadable = []
            if find_study_project(root, state["study_id"], warnings=unreadable) is not None:
                raise ValueError("This study was imported during review. Reopen it to update the existing project.")
            unreviewed = sorted(set(unreadable).difference(accepted_unreadable))
            if unreviewed:
                raise ValueError("Reopen the Studio import to review projects whose study identity could not be "
                                 "checked before creating a new project.\n" + "\n".join(unreviewed))
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
    previous = current.manifest.get("tools", {}).get(NAMESPACE) or {}
    previous_visits = previous.get("visits", {})
    if previous and Path(previous["raw_folder"]) != folder:
        _relocate_study_sources(current, manifest, folder, previous)
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


def _relocate_study_sources(current, manifest, folder, previous):
    """Rebase cohort-owned registrations after the analyst chooses the moved EEG folder."""
    old_folder = Path(previous["raw_folder"])
    owned_ids = {visit["recording_id"] for visit in previous["visits"].values() if visit.get("recording_id")}
    for source_id, source in current.recording_sources.items():
        if not source.get("reviewed_files_only") or Path(source["raw_input_folder"]) != old_folder:
            continue
        members = {key: row for key, row in current.recordings.items() if row["source_id"] == source_id}
        if members.keys() - owned_ids:
            raise ValueError(f"Recording source {source_id} also contains registrations outside this Studio cohort. "
                             "Review its source folder in the project before relocating the study.")
        manifest["recording_sources"][source_id]["raw_input_folder"] = str(folder)
        for key, row in members.items():
            relative = Path(row["raw_file"]).relative_to(old_folder)
            manifest["recordings"][key]["raw_file"] = str(folder / relative)
        group = manifest["groups"][source["group_id"]]
        if group.get("raw_input_folder") and Path(group["raw_input_folder"]) == old_folder:
            group["raw_input_folder"] = str(folder)


def _publish(root, imported, review, state, setup, hardware, group_assignments, selection):
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
        current = Project(root, manifest)
        if selection and (selection.platform != hardware or previous and not selection.matches(current.preprocessing)):
            raise ValueError(f"Studio montage {selection.label} conflicts with the project recording settings.")
        # A fresh export may serialize the same accepted roster differently.
        # Source project identity was checked in review, including for historical receipts.
        if (previous and previous.get("website_study") == state.get("website_study")
                and all(previous.get(key) == value for key, value in state.items() if key not in {"source_sha256", "project_id"})):
            return current
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
            manifest["preprocessing"] = (selection.apply(current.preprocessing) if selection else
                                         confirm_hardware_selection(current.preprocessing, hardware, confirmed_change=True))
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
                history[-1]["previous_result"], history[-1]["previous_result_sha256"] = prior_result
        evidence = studio_evidence_path(root, imported.source_sha256)
        if not evidence.exists():
            evidence.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write(evidence, replace=replace_with_retry) as stream:
                json.dump({"source_filename": imported.source_filename, "source_sha256": imported.source_sha256,
                           "handoff": imported.provenance}, stream, ensure_ascii=False, allow_nan=False)
        transaction.write(manifest)
    return Project.load(root)


def _preserve_reviewed_result(root: Path, previous: Mapping[str, Any]) -> tuple[str, str] | None:
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
    return archive_reviewed_result(root, original, coverage, previous.get("current_result", {}).get("workbook_sha256"))


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
