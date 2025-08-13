"""Data model representing a preprocessing project manifest."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict


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
        # Processing parallelism configuration
        "parallel_mode": "process",
        "max_workers": None,
    },
}


@dataclass
class Project:
    """Container for project settings stored in ``project.json``."""

    project_root: Path
    name: str
    input_folder: Path
    subfolders: Dict[str, str]
    preprocessing: Dict[str, Any]
    event_map: Dict[str, int]
    options: Dict[str, Any]

    MANIFEST_NAME = "project.json"

    def __init__(
        self,
        project_root: Path,
        name: str,
        input_folder: Path,
        subfolders: dict[str, str],
        preprocessing: dict[str, Any],
        event_map: dict[str, int],
        options: dict[str, Any],
    ) -> None:
        self.project_root = Path(project_root)
        self.name = name
        self.input_folder = Path(input_folder)
        self.subfolders = subfolders
        self.preprocessing = preprocessing
        self.event_map = event_map
        self.options = options

    # dataclass will not auto-generate __repr__ due to custom __init__

    @classmethod
    def load(cls, path: Path | str) -> "Project":
        """Load an existing project or scaffold a new one.

        Numbered subfolders are ensured to exist and the manifest is saved
        back to disk after loading or creating a project.
        """

        project_root = Path(path)
        manifest_path = project_root / cls.MANIFEST_NAME

        data = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

        default_subfolders = {
            "excel": "1 - Excel Data Files",
            "snr": "2 - SNR Plots",
            "stats": "3 - Statistical Analysis Results",
        }
        subfolders = {**default_subfolders, **data.get("subfolders", {})}

        for folder_name in subfolders.values():
            (project_root / folder_name).mkdir(parents=True, exist_ok=True)

        preprocessing = _DEFAULTS["preprocessing"].copy()
        preprocessing.update(data.get("preprocessing", {}))

        event_map = data.get("event_map", {}) or {}

        options = _DEFAULTS["options"].copy()
        options.update(data.get("options", {}))

        name = data.get("name", project_root.name)
        input_folder = Path(data.get("input_folder", ""))

        project = cls(
            project_root=project_root,
            name=name,
            input_folder=input_folder,
            subfolders=subfolders,
            preprocessing=preprocessing,
            event_map=event_map,
            options=options,
        )
        project.save()
        return project

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation."""

        return {
            "name": str(self.name),
            "input_folder": str(self.input_folder),
            "subfolders": self.subfolders,
            "preprocessing": self.preprocessing,
            "event_map": self.event_map,
            "options": self.options,
        }

    def save(self) -> None:
        """Write the manifest to ``project.json`` at :attr:`project_root`."""

        manifest_path = self.project_root / self.MANIFEST_NAME
        manifest_path.write_text(json.dumps(self.to_dict(), indent=2))
