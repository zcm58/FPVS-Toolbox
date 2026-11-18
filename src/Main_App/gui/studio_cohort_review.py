"""Operator review of Studio visit evidence and proposed external EEG matches."""

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QTableWidget, QTableWidgetItem,
)

from Main_App.gui.components import AppDialog, SubsectionHeaderLabel, SurfaceSize, make_action_button, make_action_row
from Main_App.gui.hardware_selection import choose_new_project_hardware
from Main_App.projects.preprocessing_settings import new_project_preprocessing_settings
from Main_App.projects.studio_cohort import (
    NAMESPACE, commit_study_review, find_study_project, review_study, version_key,
)


def _trigger_codes(setup):
    codes = setup.get("toolbox", {}).get("event_map", {})
    return ", ".join(f"{name} {code}" for name, code in codes.items()) or "unavailable"


class StudioCohortReview(AppDialog):
    def __init__(self, imported, review, parent=None, *, project_root=None):
        super().__init__("Review Studio cohort", parent,
                         size=SurfaceSize(width=990, height=610, min_width=720, min_height=450))
        self.review = review
        self.imported = imported
        self.decisions = {}
        self.omissions = {}
        self.warnings = ()
        counts = Counter(row.status for row in review.rows)
        extras = sorted(set(review.files) - {p for r in review.rows for p in (*r.candidates, r.previous.get("raw_file"))})
        visit_count = len(review.rows)
        counts_text = [f"{visit_count} {'visit' if visit_count == 1 else 'visits'}"]
        counts_text.extend(f"{count} {name.replace('_', ' ')}" for name, count in sorted(counts.items()))
        if review.omitted:
            counts_text.append(f"{len(review.omitted)} omitted")
        if extras:
            counts_text.append(f"Extra EEG files: {len(extras)}")
        if review.prior:
            new = {r.visit["participant_number"] for r in review.rows if r.change == "new participant"}
            additional = sum(r.change == "additional visit" for r in review.rows)
            if new:
                counts_text.append(f"New participants: {len(new)}")
            if additional:
                counts_text.append(f"Additional visits: {additional}")
        title = SubsectionHeaderLabel(imported.project_title, self)
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        self.root_layout.addWidget(title)
        self.summary = QLabel(" · ".join(counts_text), self)
        self.summary.setWordWrap(True)
        self.root_layout.addWidget(self.summary)
        self.full = QCheckBox("Show full roster and extra files", self)
        roster_actions = QHBoxLayout()
        roster_actions.addWidget(self.full)
        roster_actions.addStretch(1)
        self.root_layout.addLayout(roster_actions)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Participant", "Visit", "Version", "Review", "Recording or decision"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setAccessibleName("Studio visit roster")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        for column, example in ((0, "Participant ID"), (1, "Visit"), (3, "Additional visit · Ambiguous")):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, self.fontMetrics().horizontalAdvance(example) + 20)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.root_layout.addWidget(self.table, 1)
        self.clear_rows = {}
        self.full_only = []
        self.details = {}
        first_exception = None
        versions = {}
        for row in review.rows:
            v = row.visit
            key = v["visit_id"]
            version = version_key(v)
            reason = v.get("protocol_change_reason") or ""
            short_version = version if not v.get("protocol_version_id") else version[:8]
            versions[version] = short_version + (" · " + reason if reason else "")
            information = "Review required" if row.problem else row.status.replace("_", " ").capitalize()
            if review.prior and row.change != "unchanged":
                information = f"{row.change} · {information}"
            index = self._row(v["participant_number"], v.get("participant_session_number"), short_version, information)
            self.table.item(index, 2).setToolTip(version)
            setup = imported.provenance.get("setups", {}).get(v.get("setup_id"), {}) if hasattr(imported, "provenance") else {}
            conditions = [run.get("condition_name", "") for run in v.get("runs", ())]
            hardware = (v.get("recording") or {}).get("selected_backend") or "Hardware unknown"
            refresh = v.get("compiled_refresh_hz")
            refresh_label = f"{refresh:g} Hz" if isinstance(refresh, (float, int)) else "Refresh rate unavailable"
            self.details[index] = "\n".join(filter(None, (
                row.problem, f"{hardware} · {refresh_label}",
                f"Conditions in order: {', '.join(conditions) or 'unavailable'}. "
                f"Trigger codes: {_trigger_codes(setup)}.",
            )))
            self.table.item(index, 1).setToolTip(f"Execution ID: {key}")
            choice = QComboBox(self.table)
            choice.setAccessibleName(f"Recording for {v['participant_number']}, visit {v.get('participant_session_number') or 'unknown'}")
            choice.addItem("Choose a recording or defer…", None)
            choice.addItem("Awaiting EEG", ("awaiting_eeg", None))
            if not row.problem:
                known = dict.fromkeys((*row.candidates, row.previous.get("raw_file")))
                for name in known:
                    if name in review.files:
                        choice.addItem(name, ("matched", name))
                choice.addItem("Choose another EEG recording…", "choose_file")
                choice.activated.connect(lambda _, box=choice: self._choose_recording(box))
            if row.status == "excluded":
                choice.addItem("Excluded after QC", ("excluded", None))
            self.table.setCellWidget(index, 4, choice)
            self.decisions[key] = choice
            if row.status in {"matched", "awaiting_eeg", "excluded"}:
                label = row.previous.get("raw_file") if row.status == "matched" else (
                    "Awaiting EEG" if row.status == "awaiting_eeg" else "Excluded after QC")
                choice.setCurrentIndex(choice.findText(label))
            if row.status == "clear":
                self.clear_rows[key] = row.candidates[0]
            if row.status in {"clear", "matched", "excluded"}:
                self.full_only.append(index)
            elif first_exception is None:
                first_exception = index
        for key, entry in review.omitted.items():
            index = self._row(entry["participant_number"], entry.get("participant_session_number"),
                              version_key(entry)[:8], "Omitted from revision")
            choice = QComboBox(self.table)
            choice.setAccessibleName(f"Decision for omitted visit {entry.get('participant_session_number')} of {entry['participant_number']}")
            choice.addItem("Resolve discrepancy…", None)
            choice.addItem("Retain previous membership", "retain")
            choice.addItem("Archive previous membership", "archive")
            self.table.setCellWidget(index, 4, choice)
            self.omissions[key] = choice
            if first_exception is None:
                first_exception = index
        for name in extras:
            index = self._row("", "", "", "Extra file")
            self.table.setItem(index, 4, QTableWidgetItem(name))
            self.full_only.append(index)
        self.full.toggled.connect(self._show_full)
        self.full.setChecked(first_exception is None)
        self.full.setVisible(bool(self.full_only and first_exception is not None))
        self._show_full(self.full.isChecked())
        detail = QLabel(self)
        detail.setTextFormat(Qt.PlainText)
        detail.setWordWrap(True)
        self.root_layout.addWidget(detail)
        self.table.currentCellChanged.connect(lambda row, *_: detail.setText(self.details.get(row, "")))
        if first_exception is not None:
            self.table.setCurrentCell(first_exception, 4)
        self.versions = QListWidget(self)
        self.versions.setAccessibleName("Experiment versions to process")
        previous = review.prior.get("versions") or [next(iter(versions))]
        for key, label in versions.items():
            item = QListWidgetItem(label)
            item.setToolTip(f"{key}\n{label}" if label != key[:8] else key)
            item.setData(Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in previous else Qt.Unchecked)
            self.versions.addItem(item)
        rows_height = self.versions.sizeHintForRow(0) * len(versions)
        self.versions.setFixedHeight(min(66, rows_height + 2 * self.versions.frameWidth() + 4))
        self.root_layout.addWidget(SubsectionHeaderLabel("Experiment versions to process", self))
        self.root_layout.addWidget(self.versions)
        self.feedback = QLabel(self)
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        self.root_layout.addWidget(self.feedback)
        prior_results = [r for r in review.prior.get("history", ()) if r.get("previous_result")]
        if project_root and prior_results:
            history = QComboBox(self)
            for item in reversed(prior_results):
                pids = {r["participant_number"] for r in item["visits"].values() if r["decision"] == "matched"
                        and version_key(r) in item["versions"]}
                history.addItem(f"Previous cohort · {len(pids)} participants · roster {item['roster_sequence']}",
                                item["previous_result"])
            open_result = make_action_button("Open previous Excel result", parent=self)
            def open_previous():
                from Main_App.gui.open_paths import open_path_in_file_manager
                target = (Path(project_root) / history.currentData()).resolve()
                archives = (Path(project_root) / ".fpvs_imports/studio/prior-results").resolve()
                if not target.is_relative_to(archives) or not target.is_file():
                    self.feedback.setText("The archived result is unavailable.")
                    return
                try:
                    if not open_path_in_file_manager(target):
                        raise OSError("No application opened the workbook.")
                except OSError as exc:
                    self.feedback.setText(f"Could not open the archived workbook. {exc}")
            open_result.clicked.connect(open_previous)
            self.root_layout.addWidget(make_action_row((history, open_result), parent=self))
        count = len(self.clear_rows)
        self.bulk = make_action_button(f"Confirm {count} clear {'match' if count == 1 else 'matches'}", parent=self)
        self.bulk.setVisible(bool(count))
        self.bulk.clicked.connect(self._confirm_clear)
        roster_actions.addWidget(self.bulk)
        cancel = make_action_button("Cancel", parent=self)
        cancel.clicked.connect(self.reject)
        save = make_action_button("Apply review", variant="primary", parent=self)
        save.clicked.connect(self._apply)
        self.root_layout.addWidget(make_action_row((cancel, save), parent=self))

    def _row(self, *values):
        index = self.table.rowCount()
        self.table.insertRow(index)
        for col, value in enumerate(values):
            item = QTableWidgetItem("" if value is None else str(value))
            item.setToolTip(item.text())
            self.table.setItem(index, col, item)
        return index

    def _show_full(self, visible):
        for index in self.full_only:
            self.table.setRowHidden(index, not visible)
        current = self.table.currentRow()
        if current >= 0 and self.table.isRowHidden(current):
            for row in range(self.table.rowCount()):
                if not self.table.isRowHidden(row):
                    self.table.setCurrentCell(row, 4)
                    break

    def _choose_recording(self, choice):
        if choice.currentData() != "choose_file":
            return
        from Main_App.io.file_filters import EEG_RECORDING_FILTER
        source, _ = QFileDialog.getOpenFileName(self, "Match this visit to a recording",
                                                str(self.review.folder), EEG_RECORDING_FILTER)
        choice.setCurrentIndex(0)
        if not source:
            return
        path = Path(source).resolve()
        if not path.is_relative_to(self.review.folder):
            self.feedback.setText("Choose a recording inside the reviewed EEG folder.")
            return
        name = path.relative_to(self.review.folder).as_posix()
        if name not in self.review.files:
            self.feedback.setText("The EEG inventory changed. Reopen review before matching this recording.")
            return
        if choice.findText(name) < 0:
            choice.insertItem(choice.count() - 1, name, ("matched", name))
        choice.setCurrentIndex(choice.findText(name))

    def _confirm_clear(self):
        for key, name in self.clear_rows.items():
            choice = self.decisions[key]
            if choice.currentData() is None:
                choice.setCurrentIndex(choice.findText(name))
        self.bulk.setEnabled(False)
        self.feedback.setText("Clear matches confirmed.")

    def selected_versions(self):
        return [self.versions.item(i).data(Qt.UserRole) for i in range(self.versions.count())
                if self.versions.item(i).checkState() == Qt.Checked]

    def _apply(self):
        versions = self.selected_versions()
        if not versions:
            self.feedback.setText("Select an experiment version to process.")
            return
        if any(not self.decisions[key].currentData() for key in self.clear_rows):
            self.feedback.setText("Confirm the clear matches above, or review them in the full roster.")
            return
        if any(not c.currentData() for c in self.decisions.values()):
            self.feedback.setText("Choose a recording or select Awaiting EEG for each remaining visit.")
            return
        if any(not c.currentData() for c in self.omissions.values()):
            self.feedback.setText("Choose whether to retain or archive each omitted visit.")
            return
        if len(versions) > 1:
            details = []
            affected = {}
            for row in self.review.rows:
                visit = row.visit
                version = version_key(visit)
                if version not in versions:
                    continue
                decision, _ = self.decisions[visit["visit_id"]].currentData()
                visit_label = f"{visit['participant_number']} visit {visit.get('participant_session_number') or '?'}"
                if decision == "awaiting_eeg":
                    visit_label += " (awaiting EEG)"
                elif decision == "excluded":
                    visit_label += " (excluded after QC)"
                affected.setdefault(version, []).append(visit_label)
                if not visit.get("setup_id"):
                    continue
                setup = self.imported.provenance["setups"][visit["setup_id"]]
                protocol = setup["protocol"]
                details.append(f"{version[:8]} · {visit.get('protocol_change_reason') or 'No recorded reason'}\n"
                               f"{protocol['base_hz']} Hz, oddball every {protocol['oddball_every_n']} stimuli. "
                               f"Trigger codes: {_trigger_codes(setup)}")
            scope = []
            for version, visits in affected.items():
                extra = f" and {len(visits) - 4} more" if len(visits) > 4 else ""
                scope.append(f"{version[:8]} ({len(visits)} {'visit' if len(visits) == 1 else 'visits'}): "
                             f"{', '.join(visits[:4])}{extra}")
            risk = "Results from different experiment versions may not be comparable."
            if QMessageBox.question(self, "Compare experiment versions",
                                    "\n\n".join(dict.fromkeys(details)) + "\n\n" + "\n".join(scope) +
                                    f"\n\n{risk} Continue to confirmation?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            if QMessageBox.warning(self, "Confirm mixed-version analysis",
                                   "\n".join(scope) + f"\n\n{risk} Include these versions together in this analysis?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            self.warnings = (True, True)
        self.accept()


def review_imported_study(host, parent, projects_root, imported, existing=None):
    from Main_App.projects.project_manager import _run_source_registration_work

    study_id = imported.provenance["study_id"]
    if existing is None:
        active = getattr(host, "currentProject", None)
        if active and active.manifest.get("tools", {}).get(NAMESPACE, {}).get("study_id") == study_id:
            existing = active
        else:
            existing = _run_source_registration_work(parent, lambda: find_study_project(projects_root, study_id),
                                                     "Finding the study project…")
    if existing:
        from Main_App.projects.project import Project
        root = existing.project_root
        existing = _run_source_registration_work(parent, lambda: Project.load(root),
                                                 "Reading the current project…")
    prior = existing.manifest["tools"][NAMESPACE] if existing else {}
    folder = prior.get("raw_folder")
    if not folder or not Path(folder).is_dir():
        folder = QFileDialog.getExistingDirectory(parent, "Select Folder Containing EEG Recordings", str(folder or projects_root))
        if not folder:
            return None
    hardware = existing.preprocessing if existing else choose_new_project_hardware(parent, new_project_preprocessing_settings())
    if not hardware:
        return None
    review = _run_source_registration_work(parent, lambda: review_study(imported, Path(folder), existing, hardware=hardware["hardware_platform"]),
                                           "Comparing the roster and recordings…")
    dialog = StudioCohortReview(imported, review, parent, project_root=existing.project_root if existing else None)
    while dialog.exec():
        decisions = {key: c.currentData() for key, c in dialog.decisions.items()}
        omissions = {key: c.currentData() for key, c in dialog.omissions.items()}
        versions, warnings = dialog.selected_versions(), dialog.warnings
        assignments = {}
        if existing and len(existing.groups) > 1:
            groups = {info["label"]: key for key, info in existing.groups.items()}
            for row in review.rows:
                pid = row.visit["participant_number"]
                if (decisions[row.visit["visit_id"]][0] != "matched" or
                        existing.participants.get(pid, {}).get("group_id") or pid in assignments):
                    continue
                label, accepted = QInputDialog.getItem(
                    parent, "Assign participant group", f"Select the project group for participant {pid}.",
                    list(groups), 0, False)
                if not accepted:
                    break
                assignments[pid] = groups[label]
            else:
                accepted = True
            if not accepted:
                continue
        try:
            project = _run_source_registration_work(parent, lambda: commit_study_review(
                projects_root, imported, review, decisions=decisions, omissions=omissions,
                versions=versions, warnings=warnings, hardware=hardware["hardware_platform"], existing=existing,
                group_assignments=assignments,
            ), "Saving the reviewed study…")
        except (OSError, RuntimeError, ValueError) as exc:
            dialog.feedback.setText(str(exc))
            continue
        host.currentProject = project
        host.loadProject(project)
        if prior and prior["roster_revision"] != imported.provenance["roster_revision"]:
            message = "The study roster changed. Earlier results cover the previous cohort. Run Processing and analysis for the revised cohort."
            host.log(message)
            host.statusBar().showMessage(message)
        return project
    return None


def reopen_study_review(host):
    from Main_App.gui.project_drafts import confirm_project_draft_exit
    from Main_App.projects.fpvs_config_import import _import_setup
    from Main_App.projects.studio_cohort import validate_study_handoff
    from Main_App.projects.project_manager import _run_source_registration_work

    project = getattr(host, "currentProject", None)
    state = project.manifest.get("tools", {}).get(NAMESPACE) if project else None
    if not state or not confirm_project_draft_exit(host):
        return
    def read_saved():
        current = json.loads((project.project_root / "project.json").read_bytes())
        state = current["tools"][NAMESPACE]
        path = project.project_root / ".fpvs_imports" / "studio" / (state["source_sha256"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"))
        setup, study = validate_study_handoff(saved["handoff"])
        if (study["study_id"], study["roster_revision"]) != (state["study_id"], state["roster_revision"]):
            raise ValueError("Saved Studio evidence conflicts with the current project.")
        return replace(_import_setup(setup, Path(saved["source_filename"]), b""), provenance=study,
                       project_title=study["project_title"], source_sha256=state["source_sha256"])
    try:
        imported = _run_source_registration_work(host, read_saved, "Reading saved study evidence…")
        review_imported_study(host, host, project.project_root.parent, imported, project)
    except (OSError, RuntimeError, ValueError) as exc:
        QMessageBox.warning(host, "Study review", str(exc))
