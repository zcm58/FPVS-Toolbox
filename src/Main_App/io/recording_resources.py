"""Source-format resource estimates kept outside numerical processing."""

from pathlib import Path

from Main_App.io.recording_sources import recording_source_files


def estimate_source_preload_bytes(path: Path) -> int:
    """Preserve conservative source-size admission before opening a recording.

    Packed 24-bit BDF samples need four source bytes of budget per source byte;
    BrainVision companion sets retain the existing eightfold upper bound.
    Actual loaded array sizes remain the final admission authority.
    """
    if path.suffix.lower() in {".vhdr", ".bvrh"}:
        return sum(item.stat().st_size for item in recording_source_files(path)) * 8
    return path.stat().st_size * 4
