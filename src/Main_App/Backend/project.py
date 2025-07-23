"""Data model representing a preprocessing project manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Optional


_DEFAULTS = {
    "subfolders": {
        "excel": "1 - Excel Data Files",
        "snr": "2 - SNR Plots",
        "stats": "3 - Statistical Analysis Results",
    },
    "preprocessing": {
        "low_pass": 0.1,
        "high_pass": 50,
        "downsample": 256,
        "rejection_z": 5,
        "ref_chan1": "EXG1",
        "ref_chan2": "EXG2",
        "max_chan_idx": 64,
        "max_bad_chans": 10,
    },
    "event_map": {},
    "options": {
        "mode": "batch",
        "run_loreta": False,
    },
}


@dataclass
class Project:
    """Container for project settings stored in ``project.json``."""

    project_root: Path
    name: str
    subfolders: Dict[str, str] = field(default_factory=lambda: _DEFAULTS["subfolders"].copy())
    preprocessing: Dict[str, Any] = field(
        default_factory=lambda: _DEFAULTS["preprocessing"].copy()
    )
    event_map: Dict[str, int] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=lambda: _DEFAULTS["options"].copy())

    MANIFEST_NAME = "project.json"

    def __init__(self, project_root: Path, data: Optional[Dict[str, Any]] | None = None) -> None:
        """Initialize the project from ``data`` or defaults."""

        object.__setattr__(self, "project_root", Path(project_root))
        object.__setattr__(self, "name", Path(project_root).name)
        manifest = data or {}

        sub = _DEFAULTS["subfolders"].copy()
        sub.update(manifest.get("subfolders", {}))
        object.__setattr__(self, "subfolders", sub)

        prep = _DEFAULTS["preprocessing"].copy()
        prep.update(manifest.get("preprocessing", {}))
        object.__setattr__(self, "preprocessing", prep)

        event_map = manifest.get("event_map", {}) or {}
        object.__setattr__(self, "event_map", event_map)

        opts = _DEFAULTS["options"].copy()
        opts.update(manifest.get("options", {}))
        object.__setattr__(self, "options", opts)

    # dataclass will not auto-generate __repr__ due to custom __init__

    @classmethod
    def load(cls, path: Path | str) -> "Project":
        """Load an existing project or scaffold a new one.

        Numbered subfolders are ensured to exist and the manifest is saved
        back to disk after loading or creating a project.
        """

        project_root = Path(path)
        manifest_path = project_root / cls.MANIFEST_NAME

        # Load existing manifest if present
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
        else:
            data = {}

        # Default subfolders with required numbering
        default_subfolders = {
            "excel": "1 - Excel Data Files",
            "snr": "2 - SNR Plots",
            "stats": "3 - Statistical Analysis Results",
        }

        # Merge saved subfolders with defaults
        subfolders = {**default_subfolders, **data.get("subfolders", {})}

        # Ensure directories exist on disk
        for folder_name in subfolders.values():
            (project_root / folder_name).mkdir(parents=True, exist_ok=True)

        # Instantiate project with merged manifest data
        project = cls(project_root=project_root, data={**data, "subfolders": subfolders})

        # Persist updated manifest
        project.save()
        return project

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation."""

        return {
            "subfolders": self.subfolders,
            "preprocessing": self.preprocessing,
            "event_map": self.event_map,
            "options": self.options,
        }

    def save(self) -> None:
        """Write the manifest to ``project.json`` at :attr:`project_root`."""

        manifest_path = self.project_root / self.MANIFEST_NAME
        manifest_path.write_text(json.dumps(self.to_dict(), indent=2))
