Instructions for Codex:

Inherit the repository environment, cross-platform, and audit policy from the
root `AGENTS.md`. Use `docs/agent/agent-index.md` to select the first executable
check, and do not scan unrelated source folders when that check already proves
the invariant.

If you are instructed to make edits in a specific directory that will not affect other directories, please review 
the AGENTS.md file in that directory for specific instructions. To save time, you do not have to review the AGENTS.md
file of other directories if your edits will not affect them. If your edits will affect other directories, please review 
the AGENTS.md file in each directory for specific instructions before making major edits. 

In general, the app GUI should not be altered significantly unless a new button or
toolbar option is needed when adding new features.

`src/main.py` is the launcher for the PySide6 application. Active Main App code
now belongs in purpose-based packages under `Main_App` such as `gui`,
`processing`, `projects`, `workers`, `io`, `diagnostics`, `settings`, and `exports`.
Do not add new `PySide6_App` or `Legacy_App` imports or files.
`Shared` and `Performance` are compatibility aliases; implementations and new
imports belong in those purpose-based packages.

For hardware, montage, processing-stage, or FPVS Studio integration work, read
the [hardware, pipeline, and Studio roadmap](../docs/agent/architecture/hardware-pipeline-studio-roadmap.md).
The processing pipeline is the primary product; FHC, scalp maps and other
analysis tools are optional downstream additions. Supported BioSemi and Brain
Products inputs now pass through the project-local BIDS/lossless-derivative
boundary in `Main_App.io.bids_import` and `bids_loader`, then shared MNE stages
in `Main_App.processing.preprocess`. Preserve the documented BVRF exception;
it is not standard raw EEG-BIDS.
Hardware interpretation and calibrated-profile metadata belong in
`Main_App.io.acquisition_metadata` / `geometry_metadata`. Pass the immutable
`io.recording_contract.RecordingContract` into the numerical engine; reference,
filtering and interpolation implementations stay in `processing` and consume
generic channel roles, geometry and project methods. The old
`processing.acquisition_policy` import surface is compatibility-only.

The target is modular support for different acquisition systems and montages,
with supported stages and parameters selected by the user and persisted per
project, plus complete FPVS Studio compatibility. These are development goals,
not a claim that every device, montage, or Studio workflow is supported today.
Keep format, acquisition, montage, and event semantics distinct; a montage alone
cannot establish reference, sample-rate, integrity, or trigger policy. Preserve
the locked BioSemi processing order and scientific profiles while adding
explicitly versioned, tested capabilities. Tool-specific restrictions remain
in force until that tool's new capability is qualified.


When adding new features, please try to keep the code modular and under 500 lines per file. You are allowed to import
functions from other files into the main window shell where needed, but please do not add new functions to the main_window.py file.
Do not add Tkinter, CustomTkinter, or CTkMessagebox imports; the active UI toolkit is PySide6 only.
