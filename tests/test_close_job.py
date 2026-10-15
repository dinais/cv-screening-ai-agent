from src import create_app
from src.agents.candidate_evaluation import select_pending
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.job_commands import CloseJobCommand, CreateJobCommand
from src.queries.portal_queries import CandidatePortalQuery, HrPortalQuery, JobDetailQuery
from tests.test_auth import TestConfig


def _seed():
    app = create_app(TestConfig)
    store = app.extensions["event_store"]
    job = CreateJobCommand(store).execute(
        title="Backend engineer",
        requirements="Python and Flask",
        created_by="hr@example.com",
    )
    application = SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="Flask API development.",
    )
    return app, store, job.reference_id, application.reference_id


def test_close_appends_one_event_and_a_second_close_does_not():
    _app, store, job_id, _application_id = _seed()
    command = CloseJobCommand(store)
    before = len(store.load(job_id))

    result = command.execute(job_id=job_id, closed_by="hr@example.com")
    stream = store.load(job_id)
    closed = [event for event in stream if event.event_type == "JobClosed"]

    assert result.success
    assert result.reference_id == job_id
    assert len(stream) == before + 1
    assert closed[0].payload == {"job_id": job_id, "closed_by": "hr@example.com"}
    assert any(event.event_type == "JobCreated" for event in stream)

    again = command.execute(job_id=job_id, closed_by="hr@example.com")
    assert not again.success
    assert len(store.load(job_id)) == before + 1


def test_invalid_close_never_appends():
    _app, store, job_id, _application_id = _seed()
    command = CloseJobCommand(store)
    before = len(store.load_by_types(("JobClosed",)))

    assert not command.execute(job_id="", closed_by="hr@example.com").success
    assert not command.execute(job_id=job_id, closed_by="").success
    assert not command.execute(job_id="missing", closed_by="hr@example.com").success
    assert store.load_by_types(("JobClosed",)) == []
    assert len(store.load_by_types(("JobClosed",))) == before


def test_closed_job_leaves_the_open_lists_and_rejects_a_new_application():
    app, store, job_id, application_id = _seed()
    CloseJobCommand(store).execute(job_id=job_id, closed_by="hr@example.com")

    portal = HrPortalQuery(store).execute()
    assert portal.open_jobs == 0
    assert portal.applicants == 0
    assert portal.jobs == ()
    assert CandidatePortalQuery(store).execute("candidate@example.com").open_jobs == ()

    detail = JobDetailQuery(store).execute(job_id)
    assert detail is not None
    assert detail.status == "Closed"
    assert detail.applicants == 1

    rejected = SubmitApplicationCommand(store).execute(
        job_id=job_id,
        full_name="Grace Hopper",
        email="grace@example.com",
        cv_text="Compilers.",
    )
    assert not rejected.success
    assert select_pending(store) == []
    assert any(event.event_type == "ApplicationSubmitted" for event in store.load(application_id))


def test_hr_can_close_from_the_dashboard_and_a_candidate_cannot():
    app, _store, job_id, _application_id = _seed()
    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    page = hr.get(f"/hr/jobs/{job_id}")
    assert b"Close job" in page.data

    closed = hr.post(f"/hr/jobs/{job_id}/close", follow_redirects=True)
    assert closed.status_code == 200
    assert b"Backend engineer" not in closed.data
    detail = hr.get(f"/hr/jobs/{job_id}")
    assert b"Closed" in detail.data
    assert b"Close job" not in detail.data

    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    denied = candidate.post(f"/hr/jobs/{job_id}/close")
    assert denied.status_code == 403
    listing = candidate.get("/apply/")
    assert b"Backend engineer" not in listing.data
    assert candidate.get(f"/apply/{job_id}").status_code == 404
