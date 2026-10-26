"""Non-GUI adapters for processing launch workflow tests."""

import pytest


@pytest.fixture
def inline_source_registration_work(monkeypatch):
    """Run real legacy discovery without the separately tested Qt worker shell."""
    from Main_App.gui import source_participant_registration
    from Main_App.projects import project_manager

    reviews = []

    def run(_host, operation, _label):
        result = operation()
        reviews.append(result)
        return result

    def unexpected_source_review(*_args, **_kwargs):
        pytest.fail("Collision-free legacy inputs must retain the participant review workflow.")

    monkeypatch.setattr(project_manager, "_run_source_registration_work", run)
    monkeypatch.setattr(
        source_participant_registration, "SourceParticipantRegistrationDialog",
        unexpected_source_review,
    )
    return reviews
