"""Numerical thread defaults do not require constructing the application GUI."""

from __future__ import annotations

import os

import pytest

from Main_App.workers import mp_env


THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


@pytest.mark.parametrize("cores", [None, 1, 8])
def test_single_process_thread_defaults_follow_available_cores(monkeypatch, cores):
    for name in THREAD_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(mp_env.os, "cpu_count", lambda: cores)

    mp_env.set_blas_threads_single_process()

    expected_cores = cores or 1
    for name in THREAD_VARIABLES[:-1]:
        assert os.environ[name] == str(expected_cores)
    assert os.environ["NUMEXPR_NUM_THREADS"] == str(max(1, expected_cores // 2))


def test_single_process_thread_defaults_preserve_explicit_limits(monkeypatch):
    for name in THREAD_VARIABLES:
        monkeypatch.setenv(name, "2")
    monkeypatch.setattr(mp_env.os, "cpu_count", lambda: 8)

    mp_env.set_blas_threads_single_process()

    assert all(os.environ[name] == "2" for name in THREAD_VARIABLES)
