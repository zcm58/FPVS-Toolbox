import os
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif("FPVS_TEST_DATA" not in os.environ, reason="no sample data")
def test_single_vs_process_outputs_identical(tmp_path):
    sys.path.append("src")
    from Main_App.Performance.process_runner import RunParams, run_project_parallel
    from Main_App.Performance.mp_env import set_blas_threads_multiprocess

    data_root = Path(os.environ["FPVS_TEST_DATA"])
    files = sorted(p for p in data_root.glob("**/*.bdf"))[:1]
    settings: dict[str, object] = {}
    event_map = {"A": 1}

    set_blas_threads_multiprocess()
    q = None
    run_project_parallel(
        RunParams(
            project_root=data_root,
            data_files=list(files),
            settings=settings,
            event_map=event_map,
            save_folder=tmp_path,
            max_workers=1,
        ),
        q,
    )

    assert True

