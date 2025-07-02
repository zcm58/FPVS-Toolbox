# src/Tools/Image_Resizer/__init__.py
from .FPVSImageResizer import (
    FPVSImageResizerCTK,
    process_images_in_folder,
)
from .pyside_resizer import FPVSImageResizerQt

# Expose the Qt version as the default
FPVSImageResizer = FPVSImageResizerQt
__all__ = [
    "FPVSImageResizer",
    "FPVSImageResizerQt",
    "FPVSImageResizerCTK",
    "process_images_in_folder",
]
