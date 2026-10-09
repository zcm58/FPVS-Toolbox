from Main_App.gui.condition_input_model import validate_condition_rows
import pytest


@pytest.mark.parametrize("rows,field", [
    ([("Faces", "1"), ("Objects", "")], "id"),
    ([("", "2")], "label"),
    ([("Faces", "1"), ("Faces", "2")], "label"),
    ([("Faces/Objects", "2")], "label"),
    ([("Faces", "0")], "id"),
    ([("Faces", "1000000")], "id"),
    ([("Faces", "2.5")], "id"),
    ([("Faces", "²")], "id"),
])
def test_invalid_draft_identifies_the_field_without_modifying_rows(rows, field):
    original = list(rows)
    _, errors = validate_condition_rows(rows)
    assert errors and errors[0].field == field
    assert rows == original


def test_empty_placeholder_is_permitted_and_valid_rows_are_preserved():
    mapping, errors = validate_condition_rows([(" Faces ", "1"), ("", ""), ("Objects", "2")])
    assert not errors
    assert mapping == {"Faces": 1, "Objects": 2}


def test_duplicate_marker_ids_are_not_reinterpreted_by_presentation_validation():
    mapping, errors = validate_condition_rows([("Faces", "1"), ("Objects", "1")])
    assert not errors
    assert mapping == {"Faces": 1, "Objects": 1}


@pytest.mark.parametrize("labels", [
    ("1 - Faces", "2 - Faces"),
    ("1 - Faces", "2 - faces"),
    ("Faces", "faces"),
    ("Faces", "2-Faces"),
])
def test_condition_output_collisions_identify_the_later_name(labels):
    rows = [(label, str(index + 1)) for index, label in enumerate(labels)]
    mapping, errors = validate_condition_rows(rows)

    assert mapping == {labels[0]: 1}
    assert len(errors) == 1
    assert errors[0].row == 1
    assert errors[0].field == "label"
    assert "output name" in errors[0].message
    assert rows == [(labels[0], "1"), (labels[1], "2")]
