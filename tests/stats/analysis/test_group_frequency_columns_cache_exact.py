from __future__ import annotations

import struct
import math

import pytest

from Tools.Stats.analysis import dv_policy_group_significant as policy


def _original_parse(columns):
    out = []
    frequency_index = 0
    for name in columns:
        if not isinstance(name, str) or not name.endswith("_Hz"):
            continue
        try:
            out.append((float(name[:-3]), name, frequency_index))
            frequency_index += 1
        except ValueError:
            continue
    return sorted(out, key=lambda item: item[0])


def _bits(rows):
    return tuple((struct.pack("d", frequency), label, index) for frequency, label, index in rows)


@pytest.fixture(autouse=True)
def clear_cache():
    cache = policy._cached_frequency_columns
    cache.cache_clear()
    yield
    cache.cache_clear()


@pytest.mark.parametrize(
    "headers",
    [
        ["Electrode", "0.0000_Hz", "1.2000_Hz", "2.4000_Hz"],
        ["3_Hz", "1_Hz", "1.0_Hz", "2_Hz", "-0_Hz", "0_Hz"],
        ["nan_Hz", "-nan_Hz", "inf_Hz", "-inf_Hz", "2_Hz", "nan_Hz"],
        ["bad_Hz", "_Hz", "1.2 Hz", "1e-300_Hz", "1e309_Hz", "-1e-300_Hz"],
        [],
    ],
)
def test_parse_miss_and_hit_preserve_every_float_bit_label_and_original_index(headers):
    expected = _bits(_original_parse(headers))

    assert _bits(policy._parse_frequency_columns(headers)) == expected
    assert _bits(policy._parse_frequency_columns(tuple(headers))) == expected
    cacheable = all(math.isfinite(frequency) for frequency, _label, _index in _original_parse(headers))
    assert policy._cached_frequency_columns.cache_info().hits == int(cacheable)


def test_cached_result_and_mutated_header_are_detached():
    headers = ["2_Hz", "1_Hz"]
    first = policy._parse_frequency_columns(headers)
    first.clear()
    second = policy._parse_frequency_columns(headers)
    headers[0] = "3_Hz"

    assert _bits(second) == _bits(_original_parse(["2_Hz", "1_Hz"]))
    assert _bits(policy._parse_frequency_columns(headers)) == _bits(_original_parse(headers))
    assert policy._cached_frequency_columns.cache_info().misses == 2


class _Text(str):
    pass


class _Headers(list):
    pass


@pytest.mark.parametrize(
    "headers",
    [
        ["1_Hz", None, 2, object()],
        [_Text("1_Hz"), "2_Hz"],
        _Headers(["1_Hz"]),
        ["1" * 129 + "_Hz"],
        ["1_Hz"] * 32_769,
    ],
    ids=["non_string", "custom_string", "custom_sequence", "large_token", "large_header"],
)
def test_custom_or_oversized_inputs_retain_original_parser(headers):
    expected = _bits(_original_parse(headers))

    assert _bits(policy._parse_frequency_columns(headers)) == expected
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_cache_is_bounded_by_header_count():
    for frequency in range(12):
        policy._parse_frequency_columns([f"{frequency}_Hz"])

    info = policy._cached_frequency_columns.cache_info()
    assert info.maxsize == 8
    assert info.currsize == 8


def test_replaced_parser_cannot_reuse_previous_result(monkeypatch):
    headers = ["1_Hz", "2_Hz"]
    expected = policy._parse_frequency_columns(headers)
    calls = []

    def replacement(columns):
        calls.append(tuple(columns))
        return list(reversed(_original_parse(columns)))

    monkeypatch.setattr(policy, "_parse_frequency_columns_uncached", replacement)

    assert _bits(policy._parse_frequency_columns(headers)) == _bits(list(reversed(expected)))
    assert calls == [tuple(headers)]
    assert policy._cached_frequency_columns.cache_info().misses == 1


def test_stateful_replaced_converter_is_never_memoized(monkeypatch):
    calls = []

    def stateful(value):
        calls.append(value)
        return float(value) + len(calls)

    monkeypatch.setattr(policy, "float", stateful, raising=False)
    first = policy._parse_frequency_columns(["1_Hz"])
    second = policy._parse_frequency_columns(["1_Hz"])

    assert first == [(2., "1_Hz", 0)]
    assert second == [(3., "1_Hz", 0)]
    assert calls == ["1", "1"]
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_stateful_replaced_parser_is_never_memoized(monkeypatch):
    calls = []

    def stateful(columns):
        calls.append(tuple(columns))
        return [(float(len(calls)), "1_Hz", 0)]

    monkeypatch.setattr(policy, "_parse_frequency_columns_uncached", stateful)
    assert policy._parse_frequency_columns(["1_Hz"]) == [(1., "1_Hz", 0)]
    assert policy._parse_frequency_columns(["1_Hz"]) == [(2., "1_Hz", 0)]
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_replaced_sorter_is_never_memoized(monkeypatch):
    calls = []

    def stateful(values, *, key):
        calls.append(None)
        return sorted(values, key=key, reverse=len(calls) % 2 == 0)

    monkeypatch.setattr(policy, "sorted", stateful, raising=False)
    assert policy._parse_frequency_columns(["2_Hz", "1_Hz"]) == [(1., "1_Hz", 1), (2., "2_Hz", 0)]
    assert policy._parse_frequency_columns(["2_Hz", "1_Hz"]) == [(2., "2_Hz", 0), (1., "1_Hz", 1)]
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_nonfinite_headers_preserve_fresh_nan_tuple_and_set_semantics():
    headers = ["nan_Hz", "inf_Hz", "1e309_Hz"]
    first = policy._parse_frequency_columns(headers)
    second = policy._parse_frequency_columns(headers)

    assert _bits(first) == _bits(_original_parse(headers))
    assert _bits(second) == _bits(_original_parse(headers))
    assert first[0][0] is not second[0][0]
    assert first[0] != second[0]
    assert len({first[0], second[0]}) == 2
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_parser_code_replacement_retains_direct_behavior(monkeypatch):
    def replacement(_columns):
        return [(42., "42_Hz", 0)]

    monkeypatch.setattr(policy._parse_frequency_columns_uncached, "__code__", replacement.__code__)

    assert policy._parse_frequency_columns(["1_Hz"]) == [(42., "42_Hz", 0)]
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_parser_default_change_disables_admission(monkeypatch):
    monkeypatch.setattr(policy._parse_frequency_columns_uncached, "__defaults__", (["2_Hz"],))

    assert policy._parse_frequency_columns(["1_Hz"]) == [(1., "1_Hz", 0)]
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_conversion_identity_change_cannot_reuse_previous_result(monkeypatch):
    headers = ["1_Hz", "2_Hz"]
    policy._parse_frequency_columns(headers)
    monkeypatch.setattr(policy, "float", lambda value: float(value) + 10.0, raising=False)

    assert policy._parse_frequency_columns(headers) == [(11.0, "1_Hz", 0), (12.0, "2_Hz", 1)]
    assert policy._cached_frequency_columns.cache_info().misses == 1


def test_unhashable_parser_retains_direct_call(monkeypatch):
    class UnhashableParser:
        __hash__ = None

        def __call__(self, columns):
            return _original_parse(columns)

    headers = ["2_Hz", "1_Hz"]
    monkeypatch.setattr(policy, "_parse_frequency_columns_uncached", UnhashableParser())

    assert _bits(policy._parse_frequency_columns(headers)) == _bits(_original_parse(headers))
    assert policy._cached_frequency_columns.cache_info().currsize == 0


def test_cache_allocation_failure_uses_original_parser(monkeypatch):
    headers = ["1_Hz", "2_Hz"]

    def unavailable(*_args):
        raise MemoryError("cache admission failed")

    monkeypatch.setattr(policy, "_cached_frequency_columns", unavailable)

    assert _bits(policy._parse_frequency_columns(headers)) == _bits(_original_parse(headers))
