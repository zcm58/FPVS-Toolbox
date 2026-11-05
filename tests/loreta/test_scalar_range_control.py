"""Scientific color limits must never silently become zero or non-finite."""

import pytest

from Tools.LORETA_Visualizer.scalar_range_control import (
    format_scientific_value,
    parse_scientific_value,
    scientific_input_state,
    scientific_step_size,
)


@pytest.mark.parametrize("text,value", [("-2.3e-9", -2.3e-9), ("+4E-12", 4e-12),
                                        (" .125 ", .125), ("1.64", 1.64), ("-0e-999", 0.0)])
def test_scientific_values_parse_without_decimal_rounding(text, value):
    assert parse_scientific_value(text) == value


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "1e999", "1e-999", "5e-324",
                                  "1,000", "1,2", "1_000", "0x10", "1e", "1e+", "--2", "2 e-9"])
def test_nonfinite_ambiguous_and_underflowing_limits_are_rejected(text):
    with pytest.raises(ValueError):
        parse_scientific_value(text)


@pytest.mark.parametrize("text", ["", "-", "+.", ".", "-2e", "1.5e-", "2E+"])
def test_scientific_prefixes_remain_editable(text):
    assert scientific_input_state(text, -1e6, 1e6) == "intermediate"


def test_scientific_validation_respects_bounds_and_preserves_small_signed_values():
    assert scientific_input_state("-2e-9", -1e6, 1e6) == "acceptable"
    assert scientific_input_state("2e7", -1e6, 1e6) == "invalid"
    assert scientific_input_state("-1", 0.0, 10.0) == "invalid"
    assert scientific_input_state("nan", -1e6, 1e6) == "invalid"


@pytest.mark.parametrize("value,formatted", [(0.0, "0"), (-0.0, "0"), (1.64, "1.64"),
                                             (-2.3e-9, "-2.3e-09"), (1.234567e-12, "1.23457e-12")])
def test_color_range_format_is_compact_and_readable(value, formatted):
    assert format_scientific_value(value) == formatted


@pytest.mark.parametrize("value", [1.0, -1.0, 1e-9, -1e-9, 1e-100])
def test_adaptive_steps_preserve_scale_and_reverse_at_decade_boundaries(value):
    direction = -1 if value > 0 else 1
    step = scientific_step_size(value, direction)
    moved = value + direction * step
    returned = moved - direction * scientific_step_size(moved, -direction)
    assert step == pytest.approx(abs(value) * .01, rel=1e-12, abs=0.0)
    assert returned == pytest.approx(value, rel=1e-12, abs=0.0)


def test_zero_steps_retain_recent_amplitude_scale():
    assert scientific_step_size(0.0, 1, zero_step=1e-10) == 1e-10
    assert scientific_step_size(1.64, 1) == .1
    assert scientific_step_size(1e-323, -1) > 0.0
