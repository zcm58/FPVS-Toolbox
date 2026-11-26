# Private study results

Use `publish.py` for a user-requested upload and `Main_App.exports.reporting_csv`
for the full-audit workbook and release checks. `provenance.py` and
`electrode_exclusions.py` match the reviewed Studio visits to released CSV
recordings and the current processing ledger. `snapshots.py` owns the
project-local dataset, immutable request bytes and accepted parent.
`client.py` talks to the fixed OpenFPVS analysis API. `credentials.py` uses
Windows Credential Manager or the Linux Secret Service. The Qt dialog owns
consent, status and background execution.

The operator decides when to send. Preserve scientific values, exact visit
coverage, pseudonymous identifiers, explicit exclusions and unknown electrode
evidence. A project must have an imported verified website link. Preserve a
pending upload for exact retry and expose service conflicts.
Before reading a retry credential, match the destination shown to the operator
to the live project, saved reporting scope and immutable snapshot. Match the
snapshot dataset ID to the outbox. For analyzed Brain Products visits, require
the approved component SHA-256 values to match the local processing ledger and
the reviewed component metadata to match the recording plan. Old results
without admitted checksums require reprocessing. Keep the paths and digests local.

Run `tests/project_io/test_study_result_sharing.py` offline. In an approved
visible smoke, use a synthetic linked project to open **File → Share study
results…**, check the destination, connect with the synthetic lab, share an
accepted result and retry after a simulated outage. Check quitting during a
transfer and ordinary closing afterward.
