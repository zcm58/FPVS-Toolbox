from __future__ import annotations

from Tools.Sequence_Figure.gui import _image_dialog_title, _image_placeholder


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
