"""Allowlisted disposable cache locations; never discover arbitrary user folders."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile

from Main_App.projects import resolve_project_excel_root


@dataclass(frozen=True)
class CacheLocation:
    label: str
    boundary: Path
    path: Path
    kind: str


def checked_path(path: Path, boundary: Path | None = None) -> Path:
    """Reject redirected ancestors before reading or deleting an owned entry."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Cache paths must be explicit absolute paths: {path}")
    for current in (path, *path.parents):
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError(f"Refusing redirected cache path: {current}")
    resolved = path.resolve(strict=False)
    if boundary is not None:
        root = checked_path(boundary)
        if resolved == root or not resolved.is_relative_to(root):
            raise ValueError(f"Refusing cache path outside its owning root: {path}")
    return resolved


def project_cache_locations(root: Path, manifest: dict, check_cancel=lambda: None) -> tuple[CacheLocation, ...]:
    locations = [CacheLocation(label, root, root / relative, kind) for label, relative, kind in (
        ("Prepared EEG", ".fpvs_cache/preprocessed", "preprocessed"),
        ("Prepared kurtosis", ".fpvs_cache/prepared_kurtosis", "kurtosis"),
        ("Preflight QC", ".fpvs_processing/preflight_qc", "preflight"),
        ("Source PSD calculations", ".fpvs_processing/source_psd_cache", "source_psd"),
    )]
    # Detectability writes only its named cache beside condition workbooks or
    # within its configured output tree. Inspect bounded managed output trees.
    excel = resolve_project_excel_root(root, manifest)
    if excel.is_relative_to(root):
        for directory, depth in _directories_to_depth(excel, root, 3, check_cancel):
            cache = directory / "_individual_detectability_cache"
            if cache.exists():
                locations.append(CacheLocation("Individual detectability", root, cache, "detectability"))
    return tuple(locations)


def _directories_to_depth(start: Path, boundary: Path, maximum: int, check_cancel):
    if not start.exists():
        return
    pending = [(start, 0)]
    while pending:
        check_cancel()
        directory, depth = pending.pop()
        checked_path(directory, boundary)
        yield directory, depth
        if depth < maximum:
            for child in directory.iterdir():
                check_cancel()
                if child.name.startswith(".") or child.name == "_individual_detectability_cache":
                    continue
                if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                    continue
                checked_path(child, boundary)
                if child.is_dir():
                    pending.append((child, depth + 1))


def app_cache_locations() -> tuple[CacheLocation, ...]:
    from Main_App.updates.downloader import default_update_cache_dir
    locations = []
    updates = default_update_cache_dir()
    if updates.is_absolute():
        locations.append(CacheLocation("Downloaded installers", updates.parent, updates, "updates"))
    temporary_root = Path(tempfile.gettempdir()).absolute()
    locations.append(CacheLocation("Inactive EEG memory maps", temporary_root, temporary_root / "fpvs_memmap", "memmap"))
    from Tools.LORETA_Visualizer.fsaverage_cache import fpvs_toolbox_root
    try:
        toolbox_root = fpvs_toolbox_root()
    except RuntimeError:
        return tuple(locations)
    for name, kind in (("meshes", "meshes"), ("mri_templates", "mri_templates")):
        locations.append(CacheLocation(f"Visualizer {name.replace('_', ' ')}", toolbox_root,
                                       toolbox_root / ".fpvs_cache" / "loreta_visualizer" / name, kind))
    return tuple(locations)


def owned_cache_file(location: CacheLocation, path: Path) -> bool:
    relative = path.relative_to(location.path)
    name = relative.name
    if name.endswith(".lock"):
        return False
    if location.kind == "preflight" and relative.parent.name == ".slots":
        namespace = relative.parts[:-2]
        return (len(namespace) in (1, 2)
                and bool(re.fullmatch(r"v\d+_[a-z0-9_]+", namespace[0]))
                and (len(namespace) == 1 or namespace[1] in {"events", "occurrences"})
                and bool(re.fullmatch(r"(?:(?:index-state|[0-9a-f]{64})\.json|\.index-[^/]+\.tmp)", name)))
    patterns = {
        "preprocessed": r".+_[0-9a-f]{16}(?:_raw(?:-\d+)?\.fif|\.json(?:\.tmp)?)",
        "kurtosis": r"(?:[0-9a-f]{64}\.[0-9a-f]{20}\.npz|latest\.json|\.(?:pending|manifest)-[^/]+\.tmp)",
        "preflight": r"(?:[0-9a-f]{64}\.json|\.[0-9a-f]{64}\.[^/]+\.tmp)",
        "source_psd": r"(?:[0-9a-f]{64}\.(?:npz|json)|\.[0-9a-f]{64}\.[0-9a-f]{32}\.(?:npz|json)\.tmp)",
        "detectability": r".+__[0-9a-f]{16}__[0-9a-f]{16}\.npz(?:\.tmp)?",
        "updates": r"(?i)FPVS[^/]*\.exe",
        "memmap": r".+_raw\.dat",
        "meshes": r"[0-9a-f]{64}(?:\.npz|\.\d+\.[0-9a-f]{32}\.tmp\.npz)",
        "mri_templates": r"brain_0p5mm(?:\.tmp)?\.nii",
    }
    if not re.fullmatch(patterns[location.kind], name):
        return False
    if location.kind == "kurtosis":
        return len(relative.parts) == 2 and bool(re.fullmatch(r"[0-9a-f]{24}", relative.parts[0]))
    if location.kind == "preflight":
        return len(relative.parts) in (2, 3) and bool(re.fullmatch(r"v\d+_[a-z0-9_]+", relative.parts[0])) and (len(relative.parts) == 2 or relative.parts[1] in {"events", "occurrences"})
    if location.kind == "source_psd":
        return len(relative.parts) == 2 and relative.parts[0] == "v1"
    if location.kind == "memmap":
        if len(relative.parts) != 2 or not re.fullmatch(r"pid_\d+", relative.parts[0]):
            return False
        return not process_is_alive(int(relative.parts[0][4:]))
    if location.kind == "mri_templates":
        return len(relative.parts) == 2 and bool(re.fullmatch(r"[0-9a-f]{64}", relative.parts[0]))
    return len(relative.parts) == 1


def process_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        # Uncertain ownership must preserve a possibly live process's files.
        return True
