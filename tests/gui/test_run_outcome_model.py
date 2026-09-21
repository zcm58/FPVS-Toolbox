from Main_App.gui.run_outcome_model import RunOutcome, summarize_run


def test_final_ledger_failure_overrides_success_without_double_counting():
    result = summarize_run(
        results=[{"file": "a.bdf", "status": "ok"}, {"file": "b.bdf", "status": "ok"}],
        failures=[{"file": "b.bdf"}, {"file": "b.bdf"}],
        exclusions=[{"file": "c.bdf"}],
        reused_files=["d.bdf"], previously_excluded=["c.bdf", "e.bdf"],
        condition_warnings=[{"file": "a.bdf"}, {"file": "a.bdf"}],
    )
    assert result == RunOutcome(completed=1, failed=1, excluded=2, skipped=1, condition_warnings=1)
    assert result.text(cancelled=False, failure_reason="", success=True).startswith("Last run: Incomplete")


def test_cancelled_files_are_unfinished_not_failed_or_completed():
    result = summarize_run(results=[{"file": "a.bdf", "status": "ok"}],
                           failures=[{"file": "a.bdf"}], exclusions=[], interrupted_files=["a.bdf"])
    assert result.interrupted == 1
    assert result.failed == result.completed == 0
    assert "Cancelled" in result.text(cancelled=True, failure_reason="", success=False)


def test_post_processing_failure_never_claims_analysis_ready():
    text = RunOutcome(completed=4).text(cancelled=False, failure_reason="Review required", success=True)
    assert "Incomplete" in text
    assert "outputs are not ready" in text


def test_exclusions_and_condition_warnings_are_separate_from_failed_files():
    text = RunOutcome(completed=2, excluded=1, condition_warnings=1).text(
        cancelled=False, failure_reason="", success=True)
    assert "Finished with review notes" in text
    assert "1 excluded" in text and "0 failed" in text and "1 with missing conditions" in text
