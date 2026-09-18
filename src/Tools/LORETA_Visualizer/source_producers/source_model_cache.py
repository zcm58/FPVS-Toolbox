"""Bounded process-local reuse of native inverse preparation, never serialized.

Each lookup rehashes the exact template inputs. Cached numerical resources are
private copies; each caller owns its returned arrays and MNE objects. Participant
result caches also include this identity through the model's metadata.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any, TypeVar

import numpy as np
import scipy

_T = TypeVar("_T")
_MAX_MODELS = 2
_RESOURCES: OrderedDict[str, Any] = OrderedDict()
_LOCK = RLock()


def source_model_signature(
    *,
    method: str,
    parameters: Mapping[str, Any],
    info: Mapping[str, Any],
    template_paths: Sequence[Path],
    mne_version: str,
) -> str:
    """Identify method, numerical settings, actual EEG geometry and templates."""

    templates = []
    for path in template_paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        templates.append((str(path.resolve()), digest.hexdigest()))
    payload = {
        "schema": "native-source-model-session-v1",
        "method": method,
        "parameters": parameters,
        "info": {
            name: info[name]
            for name in (
                "sfreq",
                "ch_names",
                "chs",
                "dig",
                "bads",
                "projs",
                "custom_ref_applied",
            )
        },
        "templates": templates,
        "dependencies": {"mne": mne_version, "numpy": np.__version__, "scipy": scipy.__version__},
    }
    encoded = json.dumps(payload, default=_json_value, sort_keys=True, allow_nan=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {"dtype": value.dtype.str, "shape": value.shape, "values": value.tolist()}
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Unsupported numerical model signature value: {type(value).__name__}")


def cached_source_model_resources(signature: str, build: Callable[[], _T]) -> _T:
    """Build once per compatible signature; failed builds never enter the cache."""

    with _LOCK:
        if signature in _RESOURCES:
            _RESOURCES.move_to_end(signature)
            return deepcopy(_RESOURCES[signature])
        resources = build()
        _RESOURCES[signature] = deepcopy(resources)
        while len(_RESOURCES) > _MAX_MODELS:
            _RESOURCES.popitem(last=False)
        return resources


def clear_source_model_session_cache() -> None:
    """Release retained native model resources in this process."""

    with _LOCK:
        _RESOURCES.clear()
