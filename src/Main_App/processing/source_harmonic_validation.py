"""Reuse a checked native QC release within one pair of source-map producers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from Main_App.processing.artifact_freshness import manifest_without_artifact_freshness
from Main_App.processing.post_processing_context import FileSnapshot, capture_validation_files
from Main_App.processing.source_release_files import NativeReleaseFiles

if TYPE_CHECKING:
    from Main_App.processing.recording_condition_outcomes import RecordingConditionOutcomeLedger
    from Main_App.processing.roi_coverage import FinalReleaseReceipt, RoiCoverageLedger

    Release = tuple[RecordingConditionOutcomeLedger, RoiCoverageLedger, FinalReleaseReceipt]


def _project_state(root: Path) -> tuple[str, FileSnapshot] | None:
    """Compare the complete project except for source/derived publication status."""
    from Main_App.processing.processing_ledger import ledger_path

    manifest_path = root / "project.json"
    ledger = ledger_path(root)
    interpolation = root / ".fpvs_processing" / "condition_interpolation_run.json"
    try:
        if any(path.resolve() != path for path in (manifest_path, ledger, interpolation)):
            return None
        manifest = json.loads(manifest_path.read_bytes())
        if not isinstance(manifest, dict):
            return None
        # Preserve list order, signed zeros and numeric types.
        payload = json.dumps(
            manifest_without_artifact_freshness(manifest), sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        files = capture_validation_files((ledger, interpolation), hash_contents=True)
        if files[0][1] is None:
            return None
        if files[1][1] is None:
            try:
                interpolation.lstat()
            except FileNotFoundError:
                pass
            else:
                return None
    except (OSError, RuntimeError, ValueError):
        return None
    return hashlib.sha256(payload).hexdigest(), files


@dataclass(frozen=True)
class _VerifiedRelease:
    state: tuple[str, FileSnapshot]
    release: Release
    files: NativeReleaseFiles


class SourceHarmonicValidation:
    def __init__(self, requested_workers: int | None = None) -> None:
        self._previous: _VerifiedRelease | None = None
        self.files: NativeReleaseFiles | None = None
        self.requested_workers = requested_workers
        self.reads = 0

    def current_release(self, root: Path, *, expected_decision_fingerprint: str) -> Release:
        from Main_App.processing.raw_registration_state import require_registered_raw_processing_complete
        from Main_App.processing.roi_coverage import require_current_final_release
        from Main_App.workers.mp_env import compute_dynamic_worker_ceiling

        previous, self._previous = self._previous, None
        self.reads += 1
        self.files = None
        state = _project_state(root)
        workers = compute_dynamic_worker_ceiling(self.requested_workers)
        if previous is not None:
            if (
                state == previous.state
                and previous.release[1].decision_fingerprint == expected_decision_fingerprint
                and previous.files.current(workers)
                and _project_state(root) == state
            ):
                require_registered_raw_processing_complete(root)
                self.files = previous.files
                return previous.release
            # Reproduce the authoritative diagnostic with independent reads on
            # any change, including an open writer that restored a file's mtime.
            return _read_release_independently(root, expected_decision_fingerprint)

        release = require_current_final_release(root, expected_decision_fingerprint=expected_decision_fingerprint)
        if state is not None:
            files = NativeReleaseFiles.from_outcomes(release[0], project_root=root)
            if files is not None:
                if not files.current(workers):
                    return _read_release_independently(root, expected_decision_fingerprint)
                if state == _project_state(root):
                    self.files = files
                    self._previous = _VerifiedRelease(state, deepcopy(release), files)
        return release


def _read_release_independently(root: Path, fingerprint: str) -> Release:
    from Main_App.io.xlsx_selected_reader import xlsx_read_cache_scope
    from Main_App.processing.post_processing_context import post_processing_validation_scope
    from Main_App.processing.roi_coverage import require_current_final_release

    with post_processing_validation_scope(fresh=True), xlsx_read_cache_scope():
        return require_current_final_release(root, expected_decision_fingerprint=fingerprint)


_SOURCE_PAIR: ContextVar[SourceHarmonicValidation | None] = ContextVar("source_harmonic_validation", default=None)


def current_source_harmonic_validation() -> SourceHarmonicValidation | None:
    return _SOURCE_PAIR.get()


@contextmanager
def source_harmonic_validation_scope(project=None) -> Iterator[None]:
    """Keep validated evidence in this worker only, until both source methods finish."""
    from Main_App.workers.mp_env import project_worker_override

    requested = project_worker_override(getattr(project, "preprocessing", None), getattr(project, "options", None))
    token = _SOURCE_PAIR.set(SourceHarmonicValidation(requested))
    try:
        yield
    finally:
        _SOURCE_PAIR.reset(token)
