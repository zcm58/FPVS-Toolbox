"""GUI-neutral validation for the editable condition rows."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True)
class ConditionInputError:
    row: int
    field: str
    message: str


def validate_condition_rows(
    rows: Sequence[tuple[str, str]],
) -> tuple[dict[str, int], tuple[ConditionInputError, ...]]:
    """Validate the whole draft without dropping partial or duplicate entries."""
    mapping: dict[str, int] = {}
    errors: list[ConditionInputError] = []
    seen: set[str] = set()
    for index, (raw_label, raw_id) in enumerate(rows):
        label, ident = raw_label.strip(), raw_id.strip()
        if not label and not ident:
            continue
        if not label:
            errors.append(ConditionInputError(index, "label", "Enter a condition name."))
        elif any(char in '<>:"/\\|?*' for char in label):
            errors.append(ConditionInputError(index, "label", "Remove file-name characters: < > : \" / \\ | ? *"))
        elif label in seen:
            errors.append(ConditionInputError(index, "label", "Use a different condition name; this name is already used."))
        seen.add(label)
        if not ident.isascii() or not ident.isdecimal() or not 1 <= int(ident) <= 999999:
            errors.append(ConditionInputError(index, "id", "Enter a recorded marker ID from 1 to 999999."))
        if not any(error.row == index for error in errors):
            mapping[label] = int(ident)
    return mapping, tuple(errors)
