"""Compact scientific-notation input for prepared source-map color limits."""

from __future__ import annotations

import math
import re

from PySide6.QtCore import QLocale
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox, QWidget

_MANTISSA = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
_NUMBER = re.compile(_MANTISSA + r"(?:[eE][+-]?[0-9]+)?\Z")
_EXPONENT_PREFIX = re.compile(_MANTISSA + r"[eE][+-]?\Z")
_MINIMUM_NONZERO = 1e-323  # QDoubleSpinBox supports at most 323 decimal places.


def parse_scientific_value(text: str) -> float:
    """Parse finite decimal/scientific text without silently underflowing to zero."""
    stripped = text.strip()
    if not _NUMBER.fullmatch(stripped):
        raise ValueError("Enter a decimal number or scientific notation, such as 2e-9.")
    value = float(stripped)
    mantissa = re.split("[eE]", stripped, maxsplit=1)[0]
    nonzero_mantissa = any(digit in "123456789" for digit in mantissa)
    if not math.isfinite(value) or (nonzero_mantissa and abs(value) < _MINIMUM_NONZERO):
        raise ValueError("The color limit must be finite and representable.")
    return value


def format_scientific_value(value: float) -> str:
    """Keep ordinary Z values readable and small amplitudes compact."""
    if not math.isfinite(value):
        raise ValueError("The color limit must be finite.")
    return "0" if value == 0.0 else format(value, ".6g")


def scientific_input_state(text: str, minimum: float, maximum: float) -> str:
    """Distinguish editable prefixes from complete, bounded finite numbers."""
    stripped = text.strip()
    if stripped in {"", "+", "-", ".", "+.", "-."} or _EXPONENT_PREFIX.fullmatch(stripped):
        return "intermediate"
    try:
        value = parse_scientific_value(stripped)
    except ValueError:
        return "invalid"
    return "acceptable" if minimum <= value <= maximum else "invalid"


def scientific_step_size(value: float, direction: int, *, zero_step: float = 0.05) -> float:
    """Step one decimal order below magnitude, preserving decade round trips."""
    if not math.isfinite(value) or not math.isfinite(zero_step) or zero_step <= 0.0:
        raise ValueError("Scientific stepping requires finite values and a positive step.")
    if value == 0.0:
        return max(zero_step, _MINIMUM_NONZERO)
    magnitude = abs(value)
    exponent = math.floor(math.log10(magnitude))
    decade = 10.0 ** exponent
    if value * direction < 0.0 and math.isclose(magnitude, decade, rel_tol=1e-12, abs_tol=0.0):
        exponent -= 1
    return max(10.0 ** (exponent - 1), _MINIMUM_NONZERO)


class ScientificDoubleSpinBox(QDoubleSpinBox):
    """A bounded color-range control that retains small source amplitudes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zero_step = 0.05
        self.setDecimals(323)
        self.setRange(-1_000_000.0, 1_000_000.0)
        self.setLocale(QLocale.c())
        self.setGroupSeparatorShown(False)
        self.setKeyboardTracking(False)
        self.valueChanged.connect(self._remember_step)

    def textFromValue(self, value: float) -> str:
        return format_scientific_value(value)

    def valueFromText(self, text: str) -> float:
        try:
            return parse_scientific_value(text)
        except ValueError:
            return self.value()

    def validate(self, text: str, position: int) -> tuple[QValidator.State, str, int]:
        state = scientific_input_state(text, self.minimum(), self.maximum())
        return {
            "acceptable": QValidator.State.Acceptable,
            "intermediate": QValidator.State.Intermediate,
            "invalid": QValidator.State.Invalid,
        }[state], text, position

    def fixup(self, text: str) -> str:
        if scientific_input_state(text, self.minimum(), self.maximum()) == "acceptable":
            return format_scientific_value(parse_scientific_value(text))
        return self.textFromValue(self.value())

    def stepBy(self, steps: int) -> None:
        self.interpretText()
        step = scientific_step_size(self.value(), steps, zero_step=self._zero_step)
        self.setValue(min(self.maximum(), max(self.minimum(), self.value() + steps * step)))

    def _remember_step(self, value: float) -> None:
        if value != 0.0:
            self._zero_step = scientific_step_size(value, 1 if value > 0.0 else -1)
