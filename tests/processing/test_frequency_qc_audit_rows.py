"""Audit traversal must retain the former pandas-row evidence and QC decisions."""

from collections import defaultdict
from dataclasses import asdict
from fractions import Fraction
import pickle
import struct
import warnings

import numpy as np
import pandas as pd
import pytest

from Main_App.processing import frequency_domain_qc as qc


# Frozen from c44665827da158de0643758b4bbb999b26d8b6b2. These copies deliberately
# do not call the current parser, converter or normalizers as their oracle.
_FROZEN_AUDIT_COLUMNS = (
    "Electrode", "Target Frequency Exact (Hz)", "BCA Status", "Reason Codes",
)


def _frozen_optional_cell_text(value):
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _frozen_exact_frequency_column(value):
    text = _frozen_optional_cell_text(value)
    if not text:
        return ""
    try:
        frequency = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return ""
    return f"{float(frequency):.4f}_Hz"


def _frozen_normalize_electrode(value):
    return str(value or "").strip().upper()


def _frozen_c4466582_audit_rows(*, file_path, reader, log_func):
    from Main_App.io import MissingXlsxColumnsError

    try:
        frame = reader(
            file_path,
            sheet_name="Spectral Metric QC",
            required_columns=list(_FROZEN_AUDIT_COLUMNS),
        )
    except MissingXlsxColumnsError as exc:
        log_func(
            "Frequency-domain QC ignored malformed optional spectral audit "
            f"metadata in {file_path}: {exc}"
        )
        return {}
    except (OSError, ValueError):
        return {}

    rows_by_cell = defaultdict(list)
    if frame.columns.is_unique:
        positions = frame.columns.get_indexer(_FROZEN_AUDIT_COLUMNS)
        row_values = (
            tuple(values[position] if position >= 0 else None for position in positions)
            for values in frame.to_numpy(copy=False)
        )
    else:
        row_values = (
            tuple(row.get(column) for column in _FROZEN_AUDIT_COLUMNS)
            for _, row in frame.iterrows()
        )
    for raw_electrode, raw_frequency, raw_status, raw_reasons in row_values:
        electrode = _frozen_normalize_electrode(
            _frozen_optional_cell_text(raw_electrode)
        )
        column = _frozen_exact_frequency_column(raw_frequency)
        if not electrode or not column:
            continue
        reason_codes = tuple(
            reason.strip()
            for reason in _frozen_optional_cell_text(raw_reasons).split(";")
            if reason.strip()
        )
        rows_by_cell[(electrode, column)].append(
            {
                "bca_status": _frozen_optional_cell_text(raw_status).casefold(),
                "reason_codes": reason_codes,
            }
        )
    return {key: tuple(value) for key, value in rows_by_cell.items()}


def _ordered(value):
    if isinstance(value, dict):
        return [(key, _ordered(item)) for key, item in value.items()]
    if isinstance(value, (tuple, list)):
        return type(value), [_ordered(item) for item in value]
    if isinstance(value, float):
        return "float_bits", struct.pack(">d", value)
    return value


def _capture_parser(parser, frame=None, *, error=None):
    logs, reads = [], []
    before = pickle.dumps(frame, protocol=5)

    def reader(path, **kwargs):
        reads.append((path, kwargs))
        if error is not None:
            raise error
        return frame

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value = parser(file_path="unused.xlsx", reader=reader, log_func=logs.append)
            result = ("returned", _ordered(value))
        except Exception as exc:
            result = ("raised", type(exc), str(exc))
    assert pickle.dumps(frame, protocol=5) == before
    return result, reads, logs, [(row.category, str(row.message)) for row in caught]


def _frequency_frame(tokens):
    return pd.DataFrame([
        [" O1 ", token, "AVAILABLE", " first ; second ; first "]
        for token in tokens
    ], columns=_FROZEN_AUDIT_COLUMNS)


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
    monkeypatch.setattr(qc, "_read_bca_method_audit_rows", _frozen_c4466582_audit_rows)
    expected = qc._collect_summed_bca_flags(**kwargs)
    assert _ordered(asdict(observed)) == _ordered(asdict(expected))
    assert observed.flags


@pytest.mark.parametrize("frame", list(_frames()))
def test_frequency_token_reuse_matches_frozen_parser_and_untouched_frame(frame):
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == (
        _capture_parser(_frozen_c4466582_audit_rows, frame)
    )


@pytest.mark.parametrize("error", [
    OSError("source unavailable"), ValueError("Worksheet missing"),
    RuntimeError("unexpected reader failure"),
])
def test_frequency_token_reuse_keeps_reader_error_precedence(error):
    assert _capture_parser(qc._read_bca_method_audit_rows, error=error) == (
        _capture_parser(_frozen_c4466582_audit_rows, error=error)
    )


def test_frequency_token_reuse_keeps_optional_malformed_audit_warning():
    from Main_App.io import MissingXlsxColumnsError

    error = MissingXlsxColumnsError("Spectral Metric QC", ["BCA Status"])
    observed = _capture_parser(qc._read_bca_method_audit_rows, error=error)
    assert observed == _capture_parser(_frozen_c4466582_audit_rows, error=error)
    assert len(observed[2]) == 1


def test_frequency_token_reuse_retains_numeric_nonfinite_and_exact_text_behavior():
    frame = _frequency_frame([
        1, 1.0, 1.2, np.float64(1.2), -0.0, float("nan"), np.inf, -np.inf,
        None, pd.NA, "", "NaN", "1/0", "6/5", "1.2", " 6/5 ",
    ])
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == (
        _capture_parser(_frozen_c4466582_audit_rows, frame)
    )


_TOKEN_EVENTS = []


class _FrequencyToken:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        _TOKEN_EVENTS.append(self.value)
        warnings.warn(f"frequency token {self.value}", UserWarning, stacklevel=1)
        return self.value


class _TextToken(str):
    def __str__(self):
        _TOKEN_EVENTS.append("text subclass")
        warnings.warn("text subclass conversion", UserWarning, stacklevel=1)
        return super().__str__()


def test_frequency_token_reuse_does_not_memoize_custom_scalar_side_effects():
    frame = _frequency_frame([
        _FrequencyToken("6/5"), _FrequencyToken("6/5"),
        _TextToken("6/5"), _TextToken("6/5"), np.str_("6/5"),
    ])
    _TOKEN_EVENTS.clear()
    expected = _capture_parser(_frozen_c4466582_audit_rows, frame)
    expected_events = list(_TOKEN_EVENTS)
    _TOKEN_EVENTS.clear()
    observed = _capture_parser(qc._read_bca_method_audit_rows, frame)
    assert observed == expected
    assert _TOKEN_EVENTS == expected_events
    assert len(expected[3]) == 4


@pytest.mark.parametrize("tokens, expected_conversions", [
    ([str(Fraction(index * 6, 5)) for index in range(1, 42)] * 64, 41),
    ([str(Fraction(index, 3)) for index in range(258)] * 2, 260),
    (["0." + "0" * 125 + "1"] * 2 + ["0." + "0" * 126 + "1"] * 2, 3),
    (["", "", "1/0", "1/0"], 2),
])
def test_frequency_token_reuse_is_bounded_to_one_table(
    monkeypatch, tokens, expected_conversions,
):
    frame = _frequency_frame(tokens)
    expected = _capture_parser(_frozen_c4466582_audit_rows, frame)
    original = qc._exact_frequency_column
    calls, allocations = [], []

    def counted(value):
        calls.append(value)
        return original(value)

    def allocate():
        cache = {}
        allocations.append(cache)
        return cache

    monkeypatch.setattr(qc, "_exact_frequency_column", counted)
    monkeypatch.setattr(qc, "dict", allocate, raising=False)
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == expected
    assert len(calls) == expected_conversions
    assert len(allocations[0]) <= 256
    assert all(type(token) is str and len(token) <= 128 for token in allocations[0])
    # Neither returned evidence nor an earlier table's cache owns a later read.
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == expected
    assert len(calls) == 2 * expected_conversions
    assert len(allocations) == 2 and allocations[0] is not allocations[1]


def test_frequency_token_reuse_keeps_current_status_order_and_detached_outputs():
    frame = _frequency_frame(["6/5", "6/5", "1.2"])
    read = lambda *args, **kwargs: frame  # noqa: E731
    result = qc._read_bca_method_audit_rows(
        file_path="unused.xlsx", reader=read, log_func=lambda message: None,
    )
    result[("O1", "1.2000_Hz")][0]["bca_status"] = "caller mutation"
    frame.iloc[1] = ["Pz", "12/5", "UNAVAILABLE", "changed ; first ; first"]
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == (
        _capture_parser(_frozen_c4466582_audit_rows, frame)
    )


def test_frequency_token_reuse_preserves_conversion_before_skip_error_order():
    frame = pd.DataFrame([
        [None, "1e10000", "available", ""],
        ["O1", _FrequencyToken("must not run"), "available", ""],
    ], columns=_FROZEN_AUDIT_COLUMNS)
    _TOKEN_EVENTS.clear()
    expected = _capture_parser(_frozen_c4466582_audit_rows, frame)
    assert expected[0][0:2] == ("raised", OverflowError)
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == expected
    assert _TOKEN_EVENTS == []


@pytest.mark.parametrize("failure", ["creation", "lookup", "admission"])
def test_frequency_token_cache_allocation_failure_uses_original_converter(
    monkeypatch, failure,
):
    frame = _frequency_frame(["6/5", "6/5", "12/5"])
    expected = _capture_parser(_frozen_c4466582_audit_rows, frame)
    converter = qc._exact_frequency_column
    calls, cache_operations = [], []

    class FailingCache(dict):
        def get(self, key):
            cache_operations.append("lookup")
            if failure == "lookup":
                raise MemoryError("cache lookup allocation")
            return super().get(key)

        def __setitem__(self, key, value):
            cache_operations.append("admission")
            if failure == "admission":
                raise MemoryError("cache insertion allocation")
            super().__setitem__(key, value)

    def allocate():
        if failure == "creation":
            raise MemoryError("cache creation allocation")
        return FailingCache()

    def counted(value):
        calls.append(value)
        return converter(value)

    monkeypatch.setattr(qc, "dict", allocate, raising=False)
    monkeypatch.setattr(qc, "_exact_frequency_column", counted)
    assert _capture_parser(qc._read_bca_method_audit_rows, frame) == expected
    assert calls == ["6/5", "6/5", "12/5"]
    assert cache_operations == {
        "creation": [], "lookup": ["lookup"], "admission": ["lookup", "admission"],
    }[failure]


def test_frequency_token_converter_memory_error_is_not_retried_or_suppressed(monkeypatch):
    calls = []

    def fail(value):
        calls.append(value)
        raise MemoryError("frequency conversion failed")

    monkeypatch.setattr(qc, "_exact_frequency_column", fail)
    observed = _capture_parser(
        qc._read_bca_method_audit_rows, _frequency_frame(["6/5", "12/5"]),
    )
    assert observed[0] == ("raised", MemoryError, "frequency conversion failed")
    assert calls == ["6/5"]
