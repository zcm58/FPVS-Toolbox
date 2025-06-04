import subprocess

from pathlib import Path
=======

from config import FPVS_TOOLBOX_VERSION


if __name__ == "__main__":

    root = Path(__file__).resolve()
    while not (root / ".git").is_dir():
        root = root.parent

    src_dir = root / "src"
=======

    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "--windowed",
        "-n",
        f"FPVS_Toolbox_{FPVS_TOOLBOX_VERSION}",

        "--paths",
        str(src_dir),
        "-i",
        r"C:\\Users\\zackm\\OneDrive - Mississippi State University\\Office Desktop\\ToolBox Icon.ico",
        "--collect-all",
        "mne",
        "--hidden-import",
        "mne.io.bdf",
        "--hidden-import",
        "mne.io.eeglab",
        "--hidden-import",
        "scipy",
        "--hidden-import",
        "pandas",
        "--hidden-import",
        "numpy",
        "-F",
        str(src_dir / "main.py"),
    ]
    subprocess.run(cmd, check=True, cwd=root)

        "--paths=src",
        "-i",
        r"C:\\Users\\zackm\\OneDrive - Mississippi State University\\Office Desktop\\ToolBox Icon.ico",
        "--collect-all", "mne",
        "--hidden-import=mne.io.bdf",
        "--hidden-import=mne.io.eeglab",
        "--hidden-import=scipy",
        "--hidden-import=pandas",
        "--hidden-import=numpy",
        "-F",
        "src/main.py",
    ]
    subprocess.run(cmd, check=True)

