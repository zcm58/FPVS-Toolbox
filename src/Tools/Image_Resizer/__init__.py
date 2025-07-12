# src/Tools/Image_Resizer/__init__.py
from .image_resize_core import process_images_in_folder
from .pyside_resizer import FPVSImageResizerQt

# Expose the Qt version as the default
FPVSImageResizer = FPVSImageResizerQt
__all__ = [
    "FPVSImageResizer",
    "FPVSImageResizerQt",
    "process_images_in_folder",
]
