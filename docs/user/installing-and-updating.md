# Installing and updating FPVS Toolbox

These instructions apply to Windows builds that include **FPVS Toolbox Update &
Repair**. Source execution on Linux does not use the Windows installer.

## First installation or an older Toolbox build

Download the full `FPVSToolbox-<version>-setup.exe` installer from the
[FPVS Toolbox releases page](https://github.com/zcm58/FPVS-Toolbox-Repo/releases).
Close Toolbox, run the installer, and retain the existing installation scope
when upgrading. All-users installations may require administrator approval.

Older builds without Update & Repair need this full installation once. It
installs the separate updater and establishes the application-file inventory
needed for future patch updates. A first installation cannot use a patch.

## Update from Toolbox

Toolbox checks for updates shortly after launch when its last successful check
was more than 24 hours ago. You can check immediately using **File > Check for
Updates**. A manual check takes priority over a pending startup check.

1. Review the available version and release notes. The dialog identifies a
   smaller **Patch** when one supports your installed version, or a **Full
   installer** otherwise.
2. Select **Download Update** and wait for verification to finish. Canceling a
   download discards the incomplete transfer; retry starts from the beginning.
3. Finish processing, QC, and exports, then select **Install and Restart**.
   Resolve any unsaved project changes before Toolbox hands over to the updater.
   Cancel leaves Toolbox open without starting installation.
4. Toolbox closes after the independent updater accepts the handoff. Its compact
   progress window shows the version being installed. Wait for installation and
   the automatic restart to finish.

Application updates preserve projects, settings, analysis results, and logs.
Other running Toolbox windows must be closed before installation can proceed.
If a release lacks trusted installer metadata, the dialog explains why in-app
installation is unavailable and provides its release-page link.

## Repair an installation

Open **FPVS Toolbox Update & Repair** from the Windows Start menu when Toolbox
cannot start or when a patch reports a failure. Select **Repair / Reinstall**
to obtain the full installer, then follow the download and installation steps.
This updater has its own runtime and can work when Toolbox's main runtime is
damaged. A failed installation shows the error and provides a repair action.

If the updater itself is unavailable, download the full installer from the
releases page. A full repair is also appropriate when the installed files no
longer match a supported patch baseline.
