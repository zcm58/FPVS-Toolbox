from __future__ import annotations

from Tools.Sequence_Figure.gui import _image_dialog_title, _image_placeholder, _slot_label


def test_image_picker_copy_labels_base_and_oddball_slots() -> None:
    assert [_image_placeholder(index) for index in range(5)] == [
        "Select base image 1",
        "Select base image 2",
        "Select base image 3",
        "Select base image 4",
        "Select Oddball Image",
    ]
    assert _image_dialog_title(0) == "Select Base Image 1"
    assert _image_dialog_title(4) == "Select Oddball Image"
    assert _image_dialog_title(0, condition=2) == "Condition 3: Select Base Image 1"
    assert _image_dialog_title(4, condition=0) == "Condition 1: Select Oddball Image"


def test_slot_labels_identify_base_and_oddball_after_an_image_is_selected() -> None:
    assert [_slot_label(index) for index in range(5)] == [
        "Base 1", "Base 2", "Base 3", "Base 4", "Oddball",
    ]
