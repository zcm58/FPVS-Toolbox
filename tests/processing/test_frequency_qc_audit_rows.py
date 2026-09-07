"""Audit traversal must retain the former pandas-row evidence and QC decisions."""

from collections import defaultdict

import numpy as np
import pandas as pd
import pytest

from Main_App.processing import frequency_domain_qc as qc


def _former_audit_rows(*, file_path, reader, log_func):
    frame = reader(file_path, sheet_name=qc.SPECTRAL_METRIC_QC_SHEET_NAME,
                   required_columns=list(qc._BCA_AUDIT_REQUIRED_COLUMNS))
    result = defaultdict(list)
    for _, row in frame.iterrows():
        electrode = qc._normalize_electrode(qc._optional_cell_text(row.get("Electrode")))
        column = qc._exact_frequency_column(row.get("Target Frequency Exact (Hz)"))
        if not electrode or not column:
            continue
        reasons = tuple(reason.strip() for reason in qc._optional_cell_text(
            row.get("Reason Codes")).split(";") if reason.strip())
        result[(electrode, column)].append({
            "bca_status": qc._optional_cell_text(row.get("BCA Status")).casefold(),
            "reason_codes": reasons,
        })
    return {key: tuple(values) for key, values in result.items()}


def _frames():
    columns = list(qc._BCA_AUDIT_REQUIRED_COLUMNS)
    yield pd.DataFrame([
        [" O1 ", "6/5", "Available", None],
        ["O1", "1.2", "unavailable", " zero_noise ; missing_bin "],
        ["O2", "12/5", "unavailable", "nonfinite_target"],
        ["PZ", np.nan, pd.NA, ""],
        [None, "1/0", "available", ""],
        ["OZ", float("inf"), "available", float("nan")],
    ], columns=columns)
    yield pd.DataFrame({column: pd.array(values, dtype="string") for column, values in zip(
        columns, [["O1", "O2", None], ["6/5", "12/5", None],
                  ["available", "unavailable", None], [None, "zero_noise", None]], strict=True)})
    yield pd.DataFrame([[1, 6, 1, 0], [2, 12, 2, 1]], columns=columns)
    yield pd.DataFrame([[1, 1.2, 1, 0], [2, 2.4, 2, 1]], columns=columns)
    yield pd.DataFrame({column: pd.array([1, None], dtype="Int64") for column in columns})
    yield pd.DataFrame({column: pd.Categorical(values) for column, values in zip(
        columns, [["O1", "O2"], ["6/5", "12/5"],
                  ["available", "unavailable"], ["", "zero_noise"]], strict=True)})
    yield pd.DataFrame({"Target Frequency Exact (Hz)": ["6/5"], "Electrode": ["O1"]})
    yield pd.DataFrame(columns=columns)
    yield pd.DataFrame([["O1", "O2", "6/5", "available", ""]],
                       columns=["Electrode", *columns])


@pytest.mark.parametrize("frame", list(_frames()))
def test_audit_payload_and_method_status_match_former_rows_exactly(frame):
    kwargs = {"file_path": "unused.xlsx", "reader": lambda *args, **kwargs: frame,
              "log_func": lambda message: None}
    expected = _former_audit_rows(**kwargs)
    observed = qc._read_bca_method_audit_rows(**kwargs)
    assert observed == expected
    assert [qc._bca_method_state(value) for value in observed.values()] == [
        qc._bca_method_state(value) for value in expected.values()]
    assert qc._hash_payload({str(key): value for key, value in observed.items()}) == (
        qc._hash_payload({str(key): value for key, value in expected.items()}))


def test_valid_audit_does_not_construct_a_series_per_row(monkeypatch):
    frame = next(_frames())
    def forbidden(*args, **kwargs):
        raise AssertionError("The normal audit path must not use iterrows.")
    monkeypatch.setattr(pd.DataFrame, "iterrows", forbidden)
    rows = qc._read_bca_method_audit_rows(
        file_path="unused.xlsx", reader=lambda *args, **kwargs: frame,
        log_func=lambda message: None,
    )
    assert len(rows[("O1", "1.2000_Hz")]) == 2


@pytest.mark.parametrize("status, reasons", [
    ("available", ""), ("unavailable", "zero_noise"),
    ("unavailable", "nonfinite_target"), ("invalid", ""),
])
def test_audit_optimization_preserves_complete_flags_and_finite_gates(
    tmp_path, monkeypatch, status, reasons,
):
    from Main_App import io
    path = tmp_path / "P1_C1.xlsx"
    path.touch()
    bca = pd.DataFrame({"Electrode": ["O1", "O2"], "1.2000_Hz": [11.0, -300.0]})
    audit = pd.DataFrame([
        ["O1", "6/5", "available", ""], ["O2", "6/5", status, reasons],
    ], columns=list(qc._BCA_AUDIT_REQUIRED_COLUMNS))
    monkeypatch.setattr(io, "read_xlsx_sheet_selected_columns", lambda *args, **kwargs:
                        audit if kwargs["sheet_name"] == qc.SPECTRAL_METRIC_QC_SHEET_NAME else bca)
    monkeypatch.setattr(qc, "_source_bca_value_category", lambda **kwargs:
                        qc._bca_value_category(kwargs["fallback_value"]))
    kwargs = {"subjects": ["P1"], "conditions": ["C1"],
              "subject_data": {"P1": {"C1": str(path)}}, "selected_harmonics": [1.2],
              "thresholds": qc.FrequencyDomainQcThresholds(), "log_func": lambda message: None}
    observed = qc._collect_summed_bca_flags(**kwargs)
    monkeypatch.setattr(qc, "_read_bca_method_audit_rows", _former_audit_rows)
    expected = qc._collect_summed_bca_flags(**kwargs)
    assert observed == expected
    assert observed.flags
