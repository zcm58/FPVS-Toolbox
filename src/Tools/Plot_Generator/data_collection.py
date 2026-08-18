"""Excel discovery and data collection helpers for Plot Generator workers."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np

from Main_App.projects import DatasetIndexError, ProjectDatasetIndex
from Main_App.projects import WorkbookRecord, load_project_dataset_index
from Main_App.processing.frequency_domain_qc import active_frequency_domain_exclusions
from Tools.Plot_Generator.excel_inputs import (
    _frequency_grids_match,
    _infer_subject_id_from_path,
)
from Tools.Plot_Generator.project_paths import _is_relative_to
from Tools.Plot_Generator.source_identity import (
    SNRPublicationCancelled, SNRPublicationError,
    capture_stable_source_identity,
    verify_source_identity_after_read,
)
from Tools.Plot_Generator.spectral_qc_workflow import PlotSpectralQcWorkflowMixin


class PlotDataCollectionMixin(PlotSpectralQcWorkflowMixin):
    """Worker-state helpers for Excel discovery and FullSNR data collection."""

    def _load_dataset_index(self) -> ProjectDatasetIndex:
        """Load the shared read-only workbook index once in the worker thread."""
        if self._cancellation_checkpoint():
            raise RuntimeError("SNR plot generation was cancelled")
        if getattr(self, "_dataset_index_loaded", False):
            return self._dataset_index
        dataset_source = self.folder
        try:
            index = load_project_dataset_index(dataset_source)
        except DatasetIndexError as exc:
            raise RuntimeError(
                f"Unable to index processed workbooks under {dataset_source}: {exc}"
            ) from exc
        if self._cancellation_checkpoint():
            raise RuntimeError("SNR plot generation was cancelled")
        for diagnostic in index.diagnostics:
            if (
                diagnostic.code == "unresolved_participant"
                and index.manifest is None
            ):
                continue
            self._record_dataset_index_diagnostic(index, diagnostic)
        if index.manifest is not None and len(index.ordered_groups) > 1:
            self.multi_group_mode = True
            group_mode_error = self._group_mode_configuration_error()
            if group_mode_error is not None:
                raise RuntimeError(group_mode_error)
        if index.manifest is not None:
            canonical_groups = index.participant_group_label_map(
                uppercase_keys=True,
                include_legacy_aliases=False,
            )
            if self.enable_group_overlay:
                if not canonical_groups:
                    raise RuntimeError(
                        "No current canonical participant group assignments "
                        "are available for the selected group overlay."
                    )
                canonical_labels = {
                    group.label.casefold(): group.label
                    for group in index.ordered_groups
                }
                missing_labels = [
                    label
                    for label in self.selected_groups
                    if label.casefold() not in canonical_labels
                ]
                if missing_labels:
                    raise RuntimeError(
                        "Selected project group label(s) changed or no longer "
                        "exist: "
                        + ", ".join(missing_labels)
                        + ". Reopen the Plot Generator and reselect groups."
                    )
                self.selected_groups = [
                    canonical_labels[label.casefold()]
                    for label in self.selected_groups
                ]
                self._selected_group_set = set(self.selected_groups)
            if self.subject_groups and self.subject_groups != canonical_groups:
                self._emit(
                    "Group assignments changed since the plot was configured; "
                    "using the current canonical project assignments."
                )
            self.subject_groups = canonical_groups
        self._dataset_index = index
        self._dataset_index_loaded = True
        self._workbook_records_by_path = {
            record.path.resolve(strict=False): record
            for record in index.workbooks
        }
        self._configure_analysis_context(index)
        for record in getattr(index, "excluded_workbooks", ()):
            self._track_input_workbook(
                record.path,
                condition=record.condition,
                status="excluded",
                participant_id=record.participant_id.upper(),
                reason="project participant-condition exclusion",
            )
        return index

    def _list_excel_files(self, condition: str) -> list[Path]:
        """Return shared indexed workbook paths for one condition."""

        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            return []
        index = self._load_dataset_index()
        records = index.select(conditions=(condition,))
        if not records:
            resolved_condition = cond_folder.resolve(strict=False)
            records = tuple(
                record
                for record in index.workbooks
                if _is_relative_to(record.path, resolved_condition)
            )
        paths = {record.path for record in records}
        if index.manifest is None:
            for diagnostic in index.diagnostics:
                if diagnostic.code != "unresolved_participant":
                    continue
                paths.update(
                    path
                    for path in diagnostic.paths
                    if _is_relative_to(path, cond_folder)
                )
        return self._restrict_to_provenance_workbooks(
            sorted(paths),
            condition=condition,
        )

    def _workbook_record(self, excel_path: Path) -> WorkbookRecord | None:
        self._load_dataset_index()
        return self._workbook_records_by_path.get(excel_path.resolve(strict=False))

    def _subject_id_for_workbook(self, excel_path: Path) -> str | None:
        """Return the shared canonical identity for an indexed workbook."""

        record = self._workbook_record(excel_path)
        if record is not None and self._dataset_index.manifest is not None:
            return record.participant_id.upper()
        return _infer_subject_id_from_path(
            excel_path,
            self.subject_groups.keys() if self.subject_groups else None,
        )

    def _collect_data(
        self,
        condition: str,
        *,
        excel_files: Sequence[Path] | None = None,
        offset: int = 0,
        total_override: int | None = None,
    ) -> tuple[List[float], Dict[str, Dict[str, List[float]]]]:
        if self._cancellation_checkpoint():
            return [], {}
        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            self._emit(f"Condition folder not found: {cond_folder}")
            return [], {}
        self._load_dataset_index()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        files = list(excel_files) if excel_files is not None else self._list_excel_files(condition)
        files = self._restrict_to_provenance_workbooks(
            files,
            condition=condition,
        )
        if self._cancellation_checkpoint():
            return [], {}
        if not files:
            self._emit("No Excel files found for condition.")
            return [], {}
        total_files = len(files)
        overall_total = total_override if total_override is not None else total_files
        processed_files = 0
        self._emit(
            f"Found {total_files} Excel files in {cond_folder}",
            offset + processed_files,
            overall_total,
        )
        roi_names = self._selected_roi_names()
        subject_roi_data: Dict[str, Dict[str, List[float]]] = {}
        subject_snr_data: dict[str, dict[str, list[float]]] = {}
        subject_fft_data: dict[str, dict[str, list[float]]] = {}
        source_workbooks: dict[str, str] = {}
        spectral_qc_unavailable: dict[str, str] = {}
        freqs: Iterable[float] | None = None
        self._unknown_subject_files.clear()
        self._unselected_group_files.clear()
        roi_channels_upper = {
            roi: {ch.upper() for ch in self.roi_map.get(roi, [])}
            for roi in roi_names
        }
        roi_channel_arrays = {
            roi: np.asarray(sorted(chans), dtype=str)
            for roi, chans in roi_channels_upper.items()
        }
        included_electrodes_upper = {
            channel
            for channels in roi_channels_upper.values()
            for channel in channels
        }
        frequency_exclusions = active_frequency_domain_exclusions(
            self._analysis_project_root
        )
        if self._cancellation_checkpoint():
            return [], {}
        excluded_participants = {
            str(participant).upper()
            for participant in frequency_exclusions.excluded_participants
        }
        excluded_electrodes_by_subject = (
            frequency_exclusions.auto_excluded_electrodes_by_participant
        )

        for excel_path in files:
            if self._cancellation_checkpoint():
                return [], {}
            self._track_input_workbook(
                excel_path,
                condition=condition,
            )
            subject_id = self._subject_id_for_workbook(excel_path)
            if not subject_id:
                self._emit(
                    f"Skipping {excel_path.name}: unable to determine subject ID.",
                    offset + processed_files,
                    overall_total,
                )
                self._record_failure(item=excel_path.name, error="Unable to determine subject ID")
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="excluded",
                    reason="unable to determine participant ID",
                )
                processed_files += 1
                continue
            if self._exclude_group_input_before_read(
                excel_path,
                condition=condition,
                participant_id=subject_id,
            ):
                processed_files += 1
                continue
            if subject_id.upper() in excluded_participants:
                self._emit(
                    f"Skipping {excel_path.name}: participant is frequency-domain excluded.",
                    offset + processed_files,
                    overall_total,
                )
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="excluded",
                    participant_id=subject_id,
                    reason="frequency-domain participant exclusion",
                )
                processed_files += 1
                continue
            excluded_electrodes = excluded_electrodes_by_subject.get(
                subject_id.upper(),
                frozenset(),
            )
            read_electrodes = set(included_electrodes_upper)
            if excluded_electrodes:
                read_electrodes = {
                    electrode
                    for electrode in read_electrodes
                    if electrode.upper() not in excluded_electrodes
                }
            self._emit(
                f"Reading {excel_path.name}",
                offset + processed_files,
                overall_total,
            )
            try:
                workbook_identity_before_read = capture_stable_source_identity(
                    excel_path,
                    cancellation_checkpoint=self._cancellation_checkpoint,
                )
                df, ordered_freqs, ordered_cols = self._read_full_snr_direct(
                    excel_path,
                    included_electrodes_upper=read_electrodes,
                )
            except Exception as exc:
                if self._cancellation_checkpoint():
                    raise
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="failed",
                    participant_id=subject_id,
                    reason="FullSNR sheet could not be read",
                )
                message = (
                    "FullSNR sheet is required for SNR plots and could not be "
                    f"read from {excel_path.name}: {exc}"
                )
                self._emit(message, offset + processed_files, overall_total)
                raise RuntimeError(message) from exc
            if self._cancellation_checkpoint():
                return [], {}
            if not ordered_cols:
                self._emit(
                    f"No frequencies in x-range [{self.x_min}, {self.x_max}] for {excel_path.name}",
                    offset + processed_files,
                    overall_total,
                )
                self._record_failure(
                    item=excel_path.name,
                    error="No frequencies in selected x-range",
                )
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="excluded",
                    participant_id=subject_id,
                    reason="no frequencies in selected x-range",
                )
                processed_files += 1
                continue
            self._emit(
                f"Using {len(ordered_cols)} frequency columns in {excel_path.name}",
                offset + processed_files,
                overall_total,
            )

            if freqs is not None and not _frequency_grids_match(
                list(freqs), ordered_freqs
            ):
                message = (
                    f"Skipping {excel_path.name}: its FullSNR frequency "
                    "grid does not match the first usable workbook."
                )
                self._emit(
                    message,
                    offset + processed_files,
                    overall_total,
                )
                self._record_failure(
                    item=excel_path.name,
                    error="FullSNR frequency grid mismatch",
                )
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="excluded",
                    participant_id=subject_id,
                    reason="FullSNR frequency grid mismatch",
                )
                processed_files += 1
                continue

            electrode_upper = df["Electrode"].astype(str).str.upper().to_numpy()
            snr_values = df[ordered_cols].to_numpy(dtype=float, copy=False)
            for roi in roi_names:
                chans = roi_channels_upper.get(roi, set())
                if not chans:
                    self._emit(f"No electrode definition for ROI {roi}")
                    self._record_failure(
                        item=f"{excel_path.name}:{roi}",
                        error="No electrodes configured for ROI",
                    )
                    continue
                roi_mask = np.isin(electrode_upper, roi_channel_arrays[roi])
                if not roi_mask.any():
                    self._emit(f"No electrodes for ROI {roi} in {excel_path.name}")
                    self._record_failure(
                        item=f"{excel_path.name}:{roi}",
                        error="No electrodes for ROI",
                    )
                    continue

                roi_values = snr_values[roi_mask]
                valid = np.isfinite(roi_values)
                counts = valid.sum(axis=0)
                sums = np.where(valid, roi_values, 0.0).sum(axis=0)
                means = np.divide(
                    sums,
                    counts,
                    out=np.full(sums.shape, np.nan, dtype=float),
                    where=counts > 0,
                ).tolist()
                subject_roi_data.setdefault(subject_id, {})[roi] = means

            has_usable_roi_data = any(
                subject_id in self._participants_with_roi(subject_roi_data, roi)
                for roi in roi_names
            )
            if not has_usable_roi_data:
                subject_roi_data.pop(subject_id, None)
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="excluded",
                    participant_id=subject_id,
                    reason="no usable selected-ROI data",
                )
                processed_files += 1
                self._emit("", offset + processed_files, overall_total)
                continue

            if freqs is None:
                freqs = list(ordered_freqs)

            if self.spectral_qc_enabled:
                if self._cancellation_checkpoint():
                    return [], {}
                snr_evidence, fft_evidence, qc_unavailable_reason = (
                    self._assemble_spectral_qc_evidence(
                        excel_path,
                        ordered_freqs=ordered_freqs,
                        excluded_electrodes=tuple(excluded_electrodes),
                    )
                )
                if self._cancellation_checkpoint():
                    return [], {}
                if snr_evidence and fft_evidence:
                    subject_snr_data[subject_id] = snr_evidence
                    subject_fft_data[subject_id] = fft_evidence
                    source_workbooks[subject_id] = str(excel_path)
                if subject_id not in source_workbooks:
                    reason = qc_unavailable_reason or (
                        "spectral-QC evidence was unavailable"
                    )
                    self._note_spectral_qc_unavailable(
                        spectral_qc_unavailable,
                        condition=condition,
                        participant_id=subject_id,
                        workbook_path=excel_path,
                        reason=reason,
                    )

            try:
                read_identity = verify_source_identity_after_read(
                    excel_path,
                    before_read=workbook_identity_before_read,
                    cancellation_checkpoint=self._cancellation_checkpoint,
                )
            except SNRPublicationCancelled:
                raise
            except (OSError, SNRPublicationError):
                self._track_input_workbook(
                    excel_path,
                    condition=condition,
                    status="failed",
                    participant_id=subject_id,
                    reason="source workbook changed during read-time fingerprinting",
                )
                raise
            self._track_input_workbook(
                excel_path,
                condition=condition,
                status="included",
                participant_id=subject_id,
                read_sha256=read_identity.sha256,
                read_size_bytes=read_identity.size_bytes,
            )
            processed_files += 1
            self._emit("", offset + processed_files, overall_total)
        if not freqs:
            self._emit(
                "No frequency data found.",
                offset + processed_files,
                overall_total,
            )
            return [], {}
        if not subject_roi_data:
            self._emit("No ROI data to plot.")
            return [], {}
        freq_list = list(freqs)
        if self._cancellation_checkpoint():
            return [], {}
        self._apply_spectral_qc_to_condition(
            condition,
            freq_list,
            subject_snr_data,
            subject_fft_data,
            source_workbooks,
            spectral_qc_unavailable,
            sorted(subject_roi_data),
        )
        if self._cancellation_checkpoint():
            return [], {}
        return freq_list, subject_roi_data
