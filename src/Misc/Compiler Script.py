import subprocess
from config import FPVS_TOOLBOX_VERSION


if __name__ == "__main__":
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "--windowed",
        "--name",
        f"FPVS_Toolbox_{FPVS_TOOLBOX_VERSION}",
        "--icon",
        r"C:\\Users\\zcm58\\OneDrive - Mississippi State University\\Office Desktop\\App Icon.ico",
        "--collect-all", "mne",
        "--hidden-import", "mne.io.bdf",
        "--hidden-import", "mne.io.eeglab",
        "--hidden-import", "scipy",
        "--hidden-import", "pandas",
        "--hidden-import", "numpy",
        "--paths", ".\\src",
        "-F",
        ".\\src\\main.py",
    ]
    subprocess.run(cmd, check=True)
