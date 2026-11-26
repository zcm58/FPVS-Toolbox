"""Project-owned BIDS admission shared by full, lazy, and prefetched reads."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import ExitStack, nullcontext
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def project_import_root(app: Any, settings: Mapping[str, Any]) -> Path:
    """Require explicit project context; never create a dataset beside a source."""
    project = getattr(app, "currentProject", None)
    value = settings.get("project_root") or getattr(project, "project_root", None)
    if not value:
        raise ValueError("Open a project before importing an EEG recording into BIDS.")
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("The EEG import project root must be absolute.")
    if not root.is_dir():
        raise ValueError("The EEG import project root does not exist.")
    return root.resolve(strict=True)


def read_project_bids_raw(
    app: Any,
    path: str | Path,
    *,
    settings: Mapping[str, Any],
    preload: bool | str = False,
    stim_channel: str = "Status",
    include: Sequence[str] | None = None,
    temporary_imports: ExitStack | None = None,
) -> Any:
    """Prepare a verified BIDS import, then return the shared MNE recording."""
    from Main_App.io.bids_import import prepare_bids_recording, read_bids_recording
    from Main_App.projects.studio_recording_identity import STUDIO_SOURCE_APPROVALS_KEY, studio_source_approvals

    import_settings = {**settings, "stim_channel": stim_channel}
    root = project_import_root(app, settings)
    if Path(path).suffix.lower() in {".vhdr", ".bvrh"} and STUDIO_SOURCE_APPROVALS_KEY not in import_settings:
        project = getattr(app, "currentProject", None)
        manifest = getattr(project, "manifest", None)
        current_root = getattr(project, "project_root", None)
        if isinstance(manifest, Mapping) and current_root is not None and Path(current_root) == root:
            import_settings[STUDIO_SOURCE_APPROVALS_KEY] = studio_source_approvals(manifest)
    temporary = settings.get("enable_bids_import_cache", True) is False
    # Preloaded samples live in RAM or their caller-owned map after this read.
    # Lazy readers keep the import alive through their enclosing reader scope.
    owner = ExitStack() if temporary and preload is not False else nullcontext(temporary_imports)
    extra = {}
    if Path(path).suffix.lower() == ".bdf":
        extra["stim_channel"] = stim_channel
        if include is not None:
            extra["include"] = list(include)
    with owner as imports:
        descriptor = prepare_bids_recording(
            path, project_root=root, settings=import_settings,
            temporary_imports=imports,
        )
        raw = read_bids_recording(
            descriptor, preload=preload, extra_params=extra, stim_channel=stim_channel,
        )
    if descriptor.studio_source_sha256_by_file is not None:
        raw._studio_source_sha256_by_file = descriptor.studio_source_sha256_by_file
    raw._fpvs_bids_import = {
        **getattr(raw, "_fpvs_bids_import", {}),
        "dataset_root": str(descriptor.dataset_root),
        "conversion_seconds": descriptor.conversion_seconds,
        "reused": descriptor.reused,
    }
    if temporary:
        raw._fpvs_bids_import.update(temporary=True, import_key=descriptor.import_key)
    logger.info(
        "bids_import_ready source=%s dataset=%s reused=%s conversion_seconds=%.6f",
        path, descriptor.dataset_root, descriptor.reused, descriptor.conversion_seconds,
    )
    return raw
