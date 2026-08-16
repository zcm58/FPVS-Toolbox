"""Group-safe and transactional output helpers for publication scalp maps."""

from __future__ import annotations

import logging
import os
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from Main_App.projects import resolve_group_output_directory


CancelCheck = Callable[[], None]
logger = logging.getLogger(__name__)


def request_output_root(request: Any) -> Path:
    """Return the final output directory for one ungrouped or grouped request."""

    base_root = Path(request.output_root).expanduser().resolve(strict=False)
    group_id = str(getattr(request, "group_id", "") or "").strip()
    group_folder = str(getattr(request, "group_folder", "") or "").strip()
    if group_id and not group_folder:
        raise ValueError(
            "Grouped Scalp Maps output requires the canonical project group folder."
        )
    if not group_folder:
        return base_root
    return resolve_group_output_directory(base_root, group_folder)


def validate_output_root(request: Any) -> Path:
    """Return a safe output base that cannot contaminate workbook discovery."""

    output_root = Path(request.output_root).expanduser().resolve(strict=False)
    input_root = Path(request.input_root).expanduser().resolve(strict=False)
    try:
        output_root.relative_to(input_root)
    except ValueError:
        return output_root
    raise ValueError(
        "Scalp Maps output cannot be the processed Excel input folder or one "
        "of its descendants. Choose the project's '4 - Scalp Maps' folder or "
        "another folder outside the Excel data tree."
    )


class PublicationArtifactTransaction:
    """Stage a complete Scalp Maps artifact set before atomic publication.

    All staged files live on the final destination filesystem. Existing
    same-name artifacts are moved to transaction-local backups during commit
    and restored if publication fails. Cancelling or raising before ``commit``
    leaves previously published output untouched.
    """

    def __init__(self, request: Any) -> None:
        # Bind the transaction to the user-selected base so one commit can
        # contain every group-scoped request from an "All groups" run.
        self.target_root = validate_output_root(request)
        self.target_root.mkdir(parents=True, exist_ok=True)
        self._stage_root = _create_stage_directory(self.target_root)
        self.staging_output_root = self._stage_root / "new"
        self.staging_output_root.mkdir(parents=True, exist_ok=True)
        self._entries: dict[Path, Path] = {}
        self._committed = False

    def __enter__(self) -> PublicationArtifactTransaction:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if not self._committed:
            self.abort()

    def ensure_request_target(self, request: Any) -> None:
        """Reject requests outside this transaction's selected output base."""

        requested = request_output_root(request).resolve(strict=False)
        expected = self.target_root.resolve(strict=False)
        try:
            requested.relative_to(expected)
        except ValueError as exc:
            raise ValueError(
                "Scalp Maps artifact transaction belongs to a different output base."
            ) from exc

    def staging_output_root_for(self, request: Any) -> Path:
        """Return the group-preserving staging directory for one request."""

        self.ensure_request_target(request)
        final_root = request_output_root(request).resolve(strict=False)
        base_root = self.target_root.resolve(strict=False)
        relative = final_root.relative_to(base_root)
        staged_root = self.staging_output_root / relative
        staged_root.mkdir(parents=True, exist_ok=True)
        return staged_root

    def stage_path(self, final_path: Path) -> Path:
        """Allocate and register a staged counterpart for ``final_path``."""

        final = Path(final_path).resolve(strict=False)
        target = self.target_root.resolve(strict=False)
        try:
            relative = final.relative_to(target)
        except ValueError as exc:
            raise ValueError(
                f"Scalp Maps artifact escapes its output directory: {final}"
            ) from exc
        staged = self.staging_output_root / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        self._entries[final] = staged
        return staged

    def register_staged_path(self, staged_path: Path) -> Path:
        """Register a file already rendered below ``staging_output_root``."""

        staged = Path(staged_path).resolve(strict=False)
        staging_root = self.staging_output_root.resolve(strict=False)
        try:
            relative = staged.relative_to(staging_root)
        except ValueError as exc:
            raise ValueError(
                f"Staged Scalp Maps artifact escapes its transaction: {staged}"
            ) from exc
        final = (self.target_root / relative).resolve(strict=False)
        self._entries[final] = staged
        return final

    def commit(self, *, cancel_check: CancelCheck | None = None) -> tuple[Path, ...]:
        """Atomically replace the registered artifact set, with rollback."""

        if self._committed:
            raise RuntimeError("Scalp Maps artifact transaction was already committed.")
        if cancel_check is not None:
            cancel_check()

        entries = tuple(sorted(self._entries.items(), key=lambda item: str(item[0]).casefold()))
        missing = [staged for _final, staged in entries if not staged.is_file()]
        if missing:
            raise FileNotFoundError(f"Staged Scalp Maps artifact is missing: {missing[0]}")

        backups: dict[Path, Path] = {}
        published: list[Path] = []
        try:
            for final, staged in entries:
                if cancel_check is not None:
                    cancel_check()
                final.parent.mkdir(parents=True, exist_ok=True)
                if final.exists():
                    relative = final.relative_to(self.target_root.resolve(strict=False))
                    backup = self._stage_root / "previous" / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final, backup)
                    backups[final] = backup
                os.replace(staged, final)
                published.append(final)
            if cancel_check is not None:
                cancel_check()
        except Exception:  # Atomic commit boundary: roll back every publish/cancel failure.
            rollback_root = self._stage_root / "rollback-new"
            for final in reversed(published):
                if final.exists():
                    relative = final.relative_to(self.target_root.resolve(strict=False))
                    displaced = rollback_root / relative
                    displaced.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final, displaced)
            for final, backup in backups.items():
                if backup.exists():
                    final.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, final)
            raise

        self._committed = True
        self._cleanup_stage_best_effort(phase="after publication")
        return tuple(final for final, _staged in entries)

    def abort(self) -> None:
        """Discard only this transaction's hidden staging directory."""

        if self._committed:
            return
        # Cleanup must never mask the cancellation or generation exception
        # which caused ``__exit__`` to abort the transaction. Windows virus
        # scanners and workbook previewers can briefly retain a handle to the
        # hidden staging directory; leaving that directory behind is safer
        # than changing a typed CANCELLED/root-error outcome into ERROR.
        self._cleanup_stage_best_effort(phase="after abort")

    def _cleanup_stage_best_effort(self, *, phase: str) -> None:
        try:
            self._cleanup_stage()
        except OSError:
            logger.warning(
                "Scalp Maps could not remove staging directory %s %s; "
                "the hidden directory may remain until it is no longer locked.",
                self._stage_root,
                phase,
                exc_info=True,
                extra={
                    "operation": "publication_maps_staging_cleanup_failed",
                    "cleanup_phase": phase,
                    "staging_root": str(self._stage_root),
                },
            )

    def _cleanup_stage(self) -> None:
        if self._stage_root.exists():
            shutil.rmtree(self._stage_root)


def _create_stage_directory(target_root: Path) -> Path:
    """Create a private-ish stage while preserving inherited Windows ACLs.

    ``tempfile.mkdtemp`` requests POSIX mode 0o700. In some managed Windows
    environments that produces a directory which the creating process cannot
    traverse. A directly created, random child inherits the already validated
    destination ACL and retains the same collision-safe exclusive creation.
    """

    for _attempt in range(32):
        candidate = target_root / f".scalp-maps-stage-{secrets.token_hex(8)}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError("Could not allocate a unique Scalp Maps staging directory.")


__all__ = [
    "CancelCheck",
    "PublicationArtifactTransaction",
    "request_output_root",
    "validate_output_root",
]
