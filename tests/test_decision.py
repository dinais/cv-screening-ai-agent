from pathlib import Path

from src import create_app
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.decision_commands import DecideCandidateCommand
from src.commands.job_commands import CreateJobCommand
from src.queries.portal_queries import ApplicationDetailQuery, CandidatePortalQuery, JobDetailQuery
from tests.test_auth import TestConfig

SRC = Path(__file__).resolve().parents[1] / "src"


def _seed():
    app = create_app(TestConfig)
    store = app.extensions["event_store"]
    job = CreateJobCommand(store).execute(
        title="Backend engineer", requirements="Python and Flask", created_by="hr@example.com"
    )
    application = SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="Flask API development.",
    )
    return app, store, job.reference_id, application.reference_id


def test_accept_appends_one_event_and_a_second_decision_does_not():
    app, store, job_id, application_id = _seed()
    command = DecideCandidateCommand(store)
    before = len(store.load(application_id))

    result = command.execute(application_id=application_id, decision="accepted", decided_by="hr@example.com")
    stream = store.load(application_id)
    decided = [event for event in stream if event.event_type == "CandidateDecided"]

    assert result.success
    assert result.reference_id == application_id
    assert len(stream) == before + 1
    assert decided[0].payload == {
        "application_id": application_id,
        "job_id": job_id,
        "decision": "accepted",
        "decided_by": "hr@example.com",
    }
    again = command.execute(application_id=application_id, decision="rejected", decided_by="hr@example.com")
    assert not again.success
    assert len(store.load(application_id)) == before + 1

    view = ApplicationDetailQuery(store).execute(application_id)
    assert view.applicant.decision == "accepted"
    assert view.applicant.decided_by == "hr@example.com"
    assert JobDetailQuery(store).execute(job_id).applicant_list[0].decision == "accepted"
    assert CandidatePortalQuery(store).execute("candidate@example.com").open_jobs[0].applied is True


def test_invalid_decision_never_appends():
    _app, store, _job_id, application_id = _seed()
    command = DecideCandidateCommand(store)
    before = store.load(application_id)
    for decision, actor in (("", "hr@example.com"), ("maybe", "hr@example.com"), ("accepted", "  ")):
        result = command.execute(application_id=application_id, decision=decision, decided_by=actor)
        assert not result.success
    missing = command.execute(application_id="missing", decision="accepted", decided_by="hr@example.com")
    assert not missing.success
    assert store.load(application_id) == before
    assert store.load("missing") == []


def test_hr_can_accept_from_the_candidate_page_and_a_candidate_cannot():
    app, _store, job_id, application_id = _seed()
    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    page = hr.get(f"/hr/applications/{application_id}")
    assert b'value="accepted"' in page.data
    assert b'value="rejected"' in page.data
    assert b"Pending" in hr.get(f"/hr/jobs/{job_id}").data

    decided = hr.post(
        f"/hr/applications/{application_id}/decision",
        data={"decision": "rejected"},
        follow_redirects=True,
    )
    text = decided.get_data(as_text=True)
    assert decided.status_code == 200
    assert "rejected" in text
    assert "Decided by hr@example.com" in text
    assert 'value="accepted"' not in text
    assert "decision-rejected" in hr.get(f"/hr/jobs/{job_id}").get_data(as_text=True)
    assert "decision-rejected" in hr.get("/hr/?q=Ada").get_data(as_text=True)

    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    denied = candidate.post(f"/hr/applications/{application_id}/decision", data={"decision": "accepted"})
    assert denied.status_code == 403
    listing = candidate.get("/apply/")
    assert b"Applied" in listing.data


def test_evaluation_agent_does_not_decide():
    text = (SRC / "agents" / "candidate_evaluation.py").read_text(encoding="utf-8")
    assert "DecideCandidateCommand" not in text
    assert "CandidateDecided" not in text
