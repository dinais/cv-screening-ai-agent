from src import create_app
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.job_commands import CreateJobCommand
from src.queries.portal_queries import HrPortalQuery, project_jobs
from tests.test_auth import TestConfig


def _app():
    app = create_app(TestConfig)
    return app, app.test_client()


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def test_projection_counts_applicants_per_open_job():
    app, _client = _app()
    store = app.extensions["event_store"]
    job = CreateJobCommand(store).execute(
        title="Backend engineer",
        requirements="Python and Flask",
        created_by="hr@example.com",
    )
    SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="Analytical engines.",
    )
    SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Grace Hopper",
        email="grace@example.com",
        cv_text="Compilers.",
    )

    before = store.load_by_types(("JobCreated", "ApplicationSubmitted"))
    view = HrPortalQuery(store).execute()
    after = store.load_by_types(("JobCreated", "ApplicationSubmitted"))

    assert before == after
    assert view.open_jobs == 1
    assert view.applicants == 2
    assert view.jobs[0].status == "Open"
    assert view.jobs[0].applicants == 2
    assert view.jobs[0].title == "Backend engineer"
    assert [(person.full_name, person.email, person.cv_text) for person in view.jobs[0].applicant_list] == [
        ("Ada Lovelace", "candidate@example.com", "Analytical engines."),
        ("Grace Hopper", "grace@example.com", "Compilers."),
    ]


def test_hr_dashboard_shows_status_and_applicant_count():
    app, hr = _app()
    _login(hr, "hr@example.com", "hr-pass")
    created = hr.post(
        "/hr/jobs",
        data={"title": "Backend engineer", "requirements": "Python and Flask"},
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert b"Backend engineer" in created.data
    assert b"Open" in created.data
    assert b"Python and Flask" in created.data

    candidate = app.test_client()
    _login(candidate, "candidate@example.com", "candidate-pass")
    jobs = app.extensions["queries"]["candidate_portal"].execute("candidate@example.com").open_jobs
    assert jobs[0].applied is False
    listing = candidate.get("/apply/")
    assert b'class="button primary"' in listing.data
    assert b"applied-mark" not in listing.data

    applied = candidate.post(
        f"/apply/{jobs[0].job_id}",
        data={"full_name": "Ada Lovelace", "cv_text": "Analytical engines."},
        follow_redirects=True,
    )
    assert applied.status_code == 200
    assert b"Application submitted." in applied.data
    assert b"Backend engineer" in applied.data
    assert b"Applied" in applied.data
    assert b"applied-mark" in applied.data
    assert b'class="button primary"' not in applied.data

    again = candidate.post(
        f"/apply/{jobs[0].job_id}",
        data={"full_name": "Ada Lovelace", "cv_text": "A second copy."},
        follow_redirects=True,
    )
    assert b"You have already applied to this job." in again.data
    assert app.extensions["queries"]["hr_portal"].execute().applicants == 1

    dashboard = hr.get("/hr/")
    assert dashboard.status_code == 200
    assert b"Backend engineer" in dashboard.data
    assert b"Open" in dashboard.data
    page = dashboard.get_data(as_text=True)
    assert ">1<" in page

    detail = hr.get(f"/hr/jobs/{jobs[0].job_id}")
    assert detail.status_code == 200
    assert b"Ada Lovelace" in detail.data
    assert b"candidate@example.com" in detail.data
    assert b"Analytical engines." in detail.data


def test_missing_job_title_does_not_append_an_event():
    app, hr = _app()
    _login(hr, "hr@example.com", "hr-pass")
    response = hr.post(
        "/hr/jobs",
        data={"title": "  ", "requirements": ""},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"A job needs a title" in response.data
    assert project_jobs(app.extensions["event_store"].load_by_types(("JobCreated",))) == ()


def test_candidate_cannot_create_a_job():
    _app_obj, candidate = _app()
    _login(candidate, "candidate@example.com", "candidate-pass")
    response = candidate.post("/hr/jobs", data={"title": "Role", "requirements": "Needs"})
    assert response.status_code == 403
