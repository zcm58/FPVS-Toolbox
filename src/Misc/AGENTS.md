This Misc directory houses scripts that may not be needed for the main app to
function, but might be relevant from a software development perspective.

Before broad manual inspection, run `python .agents/scripts/audit/agent_audit.py` and use the result to decide what to read next.

Release builds should use `scripts/packaging/build_release.ps1`. Do not add
ad-hoc PyInstaller compiler helpers here; packaging changes belong under
`scripts/packaging/`.
