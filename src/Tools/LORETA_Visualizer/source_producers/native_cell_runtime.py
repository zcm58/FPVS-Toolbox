"""Attest the native numerical process for prospective, exact PSD-cell reuse."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import platform
import sys
from functools import lru_cache
from importlib import import_module
from pathlib import Path

from .project_time_domain_inputs import input_file_identity

IMPLEMENTATIONS = (
    "mne.minimum_norm.inverse",
    "mne.minimum_norm.time_frequency",
    "mne.minimum_norm._eloreta",
    "mne.time_frequency.multitaper",
    "scipy.fft._pocketfft.pypocketfft",
    "scipy.linalg._flapack",
    "scipy.signal.windows._windows",
    "numpy._core._multiarray_umath",
    "numpy.linalg._umath_linalg",
    *(
        f"Tools.LORETA_Visualizer.source_producers.{name}"
        for name in (
            "source_psd_workers",
            "hauk_source_psd",
            "source_validity",
            "model_diagnostics",
            "project_time_domain_inputs",
            "native_cell_runtime",
            "native_psd_cells",
            "project_l2_mne_hauk_source_psd_export",
            "project_eloreta_volume_hauk_source_psd_export",
        )
    ),
)


def canonical_digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def model_digest(info, inverse) -> str:
    """Frame native protocol-5 structure and every ordered array without cloning the inverse."""
    structure = hashlib.sha256()
    buffers = hashlib.sha256()

    class Sink:
        def write(self, block):
            structure.update(block)
            return len(block)

    def receive(buffer):
        data = buffer.raw()
        buffers.update(data.nbytes.to_bytes(8, "big"))
        buffers.update(data)

    pickle.Pickler(Sink(), protocol=5, buffer_callback=receive).dump((info, inverse))
    return canonical_digest([structure.hexdigest(), buffers.hexdigest()])


def _files_and_pools(*, executing=True):
    from threadpoolctl import threadpool_info

    files = {name: str(Path(import_module(name).__file__).resolve(strict=True)) for name in IMPLEMENTATIONS}
    pools = []
    fields = ("prefix", "version", "num_threads", "internal_api", "threading_layer", "architecture")
    for row in threadpool_info():
        # OpenMP exposes no portable version query. Its absolute library path,
        # complete binary digest, API and actual thread count identify the runtime.
        known_version = bool(row.get("version")) or (
            row.get("user_api") == "openmp" and row.get("internal_api") == "openmp"
        )
        if executing and (not known_version or type(row.get("num_threads")) is not int or row["num_threads"] < 1):
            raise ValueError("Incomplete native library identity")
        path = str(Path(row["filepath"]).resolve(strict=True))
        name = "native:" + path
        files[name] = path
        pools.append([name, {key: row.get(key) for key in fields}])
    if executing and not pools:
        raise ValueError("No native numerical library identified")
    return files, sorted(pools, key=lambda row: row[0])


@lru_cache(maxsize=96)
def _file_sha256(path, identity):
    with open(path, "rb") as stream:
        handle_identity = input_file_identity(os.fstat(stream.fileno()))
        if handle_identity[:4] != identity[:4] or input_file_identity(os.stat(path)) != identity:
            raise ValueError("Numerical implementation changed before fingerprinting")
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if (
            input_file_identity(os.fstat(stream.fileno())) != handle_identity
            or input_file_identity(os.stat(path)) != identity
        ):
            raise ValueError("Numerical implementation changed during fingerprinting")
    return checksum


def collect_implementation_files():
    """Hash each distinct installed implementation once in the parent per file generation."""
    files, _ = _files_and_pools(executing=False)
    result = {}
    for name, path in files.items():
        identity = input_file_identity(os.stat(path))
        result[name] = (path, identity, _file_sha256(path, identity))
    return result


def executing_runtime(manifest) -> str:
    """Use actual loaded implementations and thread counts in this kernel process."""
    import mne
    import numpy as np
    import scipy

    files, pools = _files_and_pools()
    # A GUI coordinator can import additional native libraries which the
    # numerical child never executes. Its manifest avoids re-reading known
    # binaries; the actual executing inventory defines the cache identity.
    active_digests = {}
    for name, path in files.items():
        identity = input_file_identity(os.stat(path))
        if name not in manifest:
            if not name.startswith("native:"):
                raise ValueError("Missing fingerprint for an executing numerical module")
            active_digests[name] = _file_sha256(path, identity)
            continue
        expected_path, expected_identity, digest = manifest[name]
        if path != expected_path or identity != expected_identity:
            raise ValueError("Executing implementation differs from its attested bytes")
        active_digests[name] = digest
    return canonical_digest(
        {
            "versions": (sys.version, mne.__version__, np.__version__, scipy.__version__),
            "cpu": (platform.system(), platform.machine(), np._core._multiarray_umath.__cpu_features__),
            "libraries": pools,
            "implementations": active_digests,
            "environment": {k: v for k, v in os.environ.items() if k.startswith(("OMP_", "MKL_", "MNE_", "OPENBLAS_"))},
        }
    )
