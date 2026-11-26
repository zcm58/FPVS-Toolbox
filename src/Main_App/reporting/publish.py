"""Operator-initiated publication of a reviewed final-QC cohort revision."""

from pathlib import Path

from Main_App.exports.reporting_csv import export_reporting_csv
from Main_App.projects.project import Project
from Main_App.reporting.client import deliver_pending
from Main_App.reporting.provenance import reporting_scope
from Main_App.reporting.snapshots import queue_snapshot, read_state


def publish_current(project_root: Path, *, expected_scope: dict[str, str] | None = None) -> str:
    project = Project.load(project_root)
    scope = reporting_scope(project)
    if expected_scope is not None and scope != expected_scope:
        raise ValueError("The study destination changed. Reopen Share study results to review it.")
    state = read_state(project_root)
    if state.get("scope") != scope or state.get("enrollment") != {
        "approval_status": "approved",
        "upload_enabled": True,
    }:
        raise ValueError("Connect this project and obtain administrator approval before sharing results.")
    manifest, csv = export_reporting_csv(project_root, scope)
    current = Project.load(project_root)
    if reporting_scope(current) != scope:
        raise ValueError("The study destination changed. Reopen Share study results to review it.")
    cohort = current.manifest["tools"]["studio_cohort"]
    if cohort["roster_revision"] != manifest["roster_coverage"]["roster_revision"]:
        raise ValueError("The study changed while preparing this revision. Review the current project.")
    queue_snapshot(project_root, manifest, csv)
    return deliver_pending(project_root, expected_scope=scope)
