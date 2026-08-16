"""Worker-facing analysis-context and figure bookkeeping for SNR plots."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from Main_App.projects import ProjectDatasetIndex
from Tools.Plot_Generator.analysis_context import (
    SNRAnalysisContext,
    revalidate_snr_analysis_context,
    resolve_snr_analysis_context,
)
from Tools.Plot_Generator.source_data import PlotSourceDataMixin, SourceCurve


class PlotOutputInterfaceMixin(PlotSourceDataMixin):
    """Keep rendering calculations separate from analysis bookkeeping."""

    def _initialize_plot_output_interface(self) -> None:
        self._snr_analysis_context: SNRAnalysisContext | None = None
        self._analysis_source_kind: str | None = None
        self._analysis_project_root: Path | None = None
        self._provenance_allowed_paths: frozenset[Path] | None = None
        self._pending_source_curves: dict[str, tuple[SourceCurve, ...]] = {}
        self._source_curves_seen: list[SourceCurve] = []
        self._frequency_grids_seen: list[list[float]] = []
        self._input_workbook_rows: dict[Path, dict[str, object]] = {}
        self.roi_sample_sizes: dict[str, int] = {}
        self.overlay_roi_sample_sizes: dict[str, dict[str, int]] = {}
        self.spectral_qc_runs: list[dict[str, object]] = []

    def _configure_analysis_context(
        self,
        dataset_index: ProjectDatasetIndex,
    ) -> SNRAnalysisContext:
        if self._snr_analysis_context is not None:
            return self._snr_analysis_context
        if dataset_index.manifest is not None:
            self._analysis_source_kind = "managed_full_fft_provenance"
            self._analysis_project_root = dataset_index.project_root
        context = resolve_snr_analysis_context(
            dataset_index,
            legacy_base_frequency_hz=self._analysis_base_freq,
            legacy_oddball_frequency_hz=self._analysis_oddball_freq,
        )
        self._snr_analysis_context = context
        source_kind = context.provenance.get("source_kind")
        self._analysis_source_kind = (
            source_kind if isinstance(source_kind, str) and source_kind else None
        )
        self._analysis_project_root = context.project_root
        self._provenance_allowed_paths = context.allowed_workbook_paths
        self._analysis_base_freq = context.base_frequency_hz
        self._analysis_oddball_freq = context.oddball_frequency_hz
        if not self._explicit_oddballs:
            self.oddballs = self._derive_oddball_harmonics(self.x_max)
        for warning in context.warnings:
            self._record_warning(
                code=warning["code"],
                item=warning["item"],
                message=warning["message"],
            )
            self._emit(f"Warning: {warning['message']}", 0, 0)
        return context

    def _revalidate_analysis_context_for_output(self) -> None:
        """Require one unchanged managed-project identity before rendering."""

        context = self._snr_analysis_context
        if context is not None:
            revalidate_snr_analysis_context(context)

    def _record_dataset_index_diagnostic(
        self,
        dataset_index: ProjectDatasetIndex,
        diagnostic,
    ) -> None:
        message = str(diagnostic.message)
        self._emit(f"Dataset index warning [{diagnostic.code}]: {message}")
        self._record_warning(
            code=f"dataset_index_{diagnostic.code}",
            item=str(dataset_index.scan_root),
            message=message,
        )

    def _restrict_to_provenance_workbooks(
        self,
        paths: Sequence[Path],
        *,
        condition: str | None = None,
    ) -> list[Path]:
        allowed = self._provenance_allowed_paths
        if allowed is None:
            return list(paths)
        accepted: list[Path] = []
        newly_excluded: list[str] = []
        records_by_path = getattr(self, "_workbook_records_by_path", {})
        for raw_path in paths:
            path = Path(raw_path)
            resolved = path.resolve(strict=False)
            if resolved in allowed:
                accepted.append(path)
                continue
            record = records_by_path.get(resolved)
            participant_id = (
                str(record.participant_id).upper()
                if record is not None and record.participant_id
                else None
            )
            record_condition = (
                str(record.condition)
                if record is not None and record.condition
                else str(condition or "")
            )
            was_tracked = resolved in self._input_workbook_rows
            self._track_input_workbook(
                path,
                condition=record_condition,
                status="excluded",
                participant_id=participant_id,
                reason="not in the current processing provenance active cohort",
            )
            if not was_tracked:
                newly_excluded.append(path.name)
        if newly_excluded:
            self._emit(
                "Info: Excluded workbook(s) outside the current active "
                "processing cohort: " + ", ".join(sorted(newly_excluded)),
                0,
                0,
            )
        return accepted

    def _portable_input_path(self, path: Path) -> str:
        resolved = Path(path).resolve(strict=False)
        root = (
            self._analysis_project_root
            if self._analysis_project_root is not None
            else Path(self.folder).resolve(strict=False)
        )
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return resolved.name

    def _track_input_workbook(
        self,
        path: Path,
        *,
        condition: str,
        status: str = "discovered",
        participant_id: str | None = None,
        reason: str | None = None,
        read_sha256: str | None = None,
        read_size_bytes: int | None = None,
    ) -> None:
        resolved = Path(path).resolve(strict=False)
        row = self._input_workbook_rows.setdefault(
            resolved,
            {
                "absolute_path": str(resolved),
                "path": self._portable_input_path(resolved),
                "condition": str(condition),
                "status": "discovered",
                "participant_id": None,
                "reason": None,
            },
        )
        row["status"] = str(status)
        if participant_id:
            row["participant_id"] = str(participant_id)
        if reason:
            row["reason"] = str(reason)
        if read_sha256 is not None:
            row["_read_sha256"] = str(read_sha256)
        if read_size_bytes is not None:
            row["_read_size_bytes"] = int(read_size_bytes)

    def _exclude_group_input_before_read(
        self,
        path: Path,
        *,
        condition: str,
        participant_id: str,
    ) -> bool:
        if not self.enable_group_overlay:
            return False
        group_label = self.subject_groups.get(participant_id)
        if not group_label:
            self._unknown_subject_files.add(path.name)
            reason = "no canonical group assignment"
        elif group_label not in self._selected_group_set:
            self._unselected_group_files.add(path.name)
            reason = f"group {group_label!r} was not selected"
        else:
            return False
        self._track_input_workbook(
            path,
            condition=condition,
            status="excluded",
            participant_id=participant_id,
            reason=reason,
        )
        return True

    def _record_figure_pair(
        self,
        *,
        png_path: Path,
        pdf_path: Path,
    ) -> None:
        self._record_generated_path(png_path)
        self._record_generated_path(pdf_path)
        self._completed_figure_saved = True


__all__ = ["PlotOutputInterfaceMixin"]
