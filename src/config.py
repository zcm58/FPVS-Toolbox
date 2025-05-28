import numpy as np
import customtkinter as ctk

# — FPVS Toolbox version & update API —
FPVS_TOOLBOX_VERSION       = "0.9.1"
FPVS_TOOLBOX_UPDATE_API    = "https://api.github.com/repos/zcm58/FPVS-Toolbox-Repo/releases/latest"
FPVS_TOOLBOX_REPO_PAGE     = "https://github.com/zcm58/FPVS-Toolbox-Repo/releases"

# — metrics —
TARGET_FREQUENCIES = np.arange(1.2, 16.8 + 1.2, 1.2)
DEFAULT_ELECTRODE_NAMES_64 = [
    'Fp1','AF7','AF3','F1','F3','F5','F7','FT7','FC5','FC3','FC1','C1','C3','C5','T7','TP7',
    'CP5','CP3','CP1','P1','P3','P5','P7','P9','PO7','PO3','O1','Iz','Oz','POz','Pz','CPz',
    'Fpz','Fp2','AF8','AF4','AFz','Fz','F2','F4','F6','F8','FT8','FC6','FC4','FC2','FCz','Cz',
    'C2','C4','C6','T8','TP8','CP6','CP4','CP2','P2','P4','P6','P8','P10','PO8','PO4','O2'
]
DEFAULT_STIM_CHANNEL = 'Status'

# — GUI defaults —
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")
CORNER_RADIUS         = 8
PAD_X                 = 5
PAD_Y                 = 5
ENTRY_WIDTH           = 100
LABEL_ID_ENTRY_WIDTH  = 120
