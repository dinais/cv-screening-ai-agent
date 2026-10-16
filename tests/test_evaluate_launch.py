import os
import subprocess
import sys

from src import create_app
from src.agents.candidate_evaluation import select_pending
from src.agents.launch import evaluation_running, start_evaluation
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.evaluation_commands import EvaluateCandidateCommand
from src.commands.job_commands import CreateJobCommand
from tests.test_auth import TestConfig


def _seed_two_jobs():
    app = create_app(TestConfig)
    store = app.extensions["event_store"]
    backend = CreateJobCommand(store).execute(
        title="Backend engineer", requirements="Python", created_by="hr@example.com"
    )
    chef = CreateJobCommand(store).execute(
        title="Head chef", requirements="Sauces", created_by="hr@example.com"
    )
    SubmitApplicationCommand(store).execute(
        job_id=backend.reference_id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        cv_text="Python services.",
    )
    SubmitApplicationCommand(store).execute(
        job_id=chef.reference_id,
        full_name="Auguste Escoffier",
        email="auguste@example.com",
        cv_text="Kitchen brigade.",
    )
    return app, store, backend.reference_id, chef.reference_id


def test_one_job_limits_the_pending_list():
    _app, store, backend_id, chef_id = _seed_two_jobs()
    assert {item.job_id for item in select_pending(store)} == {backend_id, chef_id}
    assert [item.job_id for item in select_pending(store, only_job_id=chef_id)] == [chef_id]
    assert select_pending(store, only_job_id="missing-job") == []


def test_start_evaluation_launches_the_agent_process(tmp_path):
    calls = []

    class _Process:
        pid = os.getpid()

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return _Process()

    pid_file = tmp_path / "evaluation.pid"
    started, message = start_evaluation(pid_file=pid_file, popen=popen)
    assert started
    assert "every application" in message
    assert calls[0][0] == [sys.executable, "-m", "src.agents"]
    assert pid_file.read_text(encoding="utf-8") == str(os.getpid())

    again, again_message = start_evaluation(job_id="job-1", pid_file=pid_file, popen=popen)
    assert again is False
    assert "already running" in again_message
    assert len(calls) == 1

    pid_file.write_text("0", encoding="utf-8")
    one_job, _message = start_evaluation(job_id="job-1", pid_file=pid_file, popen=popen)
    assert one_job
    assert calls[1][0] == [sys.executable, "-m", "src.agents", "--job-id", "job-1"]


def test_a_finished_evaluation_is_not_still_running(tmp_path):
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait(timeout=15)
    pid_file = tmp_path / "evaluation.pid"
    pid_file.write_text(str(finished.pid), encoding="utf-8")
    assert evaluation_running(pid_file) is False
    assert not pid_file.exists()


def test_hr_buttons_start_a_process_and_do_not_append(monkeypatch):
    app, store, backend_id, _chef_id = _seed_two_jobs()
    calls = []

    def fake(job_id=None):
        calls.append(job_id)
        return True, "Evaluation started."

    monkeypatch.setattr("src.controllers.hr.start_evaluation", fake)
    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    before = store.load_by_types(("CandidateEvaluated",))

    page = hr.get("/hr/")
    assert b"Evaluate pending" in page.data
    assert f"/hr/jobs/{backend_id}/evaluate".encode() in page.data

    started = hr.post("/hr/evaluate", follow_redirects=True)
    assert b"Evaluation started." in started.data
    assert calls == [None]
    one = hr.post(f"/hr/jobs/{backend_id}/evaluate", follow_redirects=True)
    assert b"Evaluation started." in one.data
    assert calls == [None, backend_id]
    assert store.load_by_types(("CandidateEvaluated",)) == before

    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    assert candidate.post("/hr/evaluate").status_code == 403


def test_evaluate_button_is_hidden_after_the_application_is_assessed():
    app, store, job_id, _chef_id = _seed_two_jobs()
    application_id = store.load_by_types(("ApplicationSubmitted",))[0].payload["application_id"]
    # The first submitted application belongs to whichever job was created first.
    first = next(event for event in store.load_by_types(("ApplicationSubmitted",)) if event.payload["job_id"] == job_id)
    EvaluateCandidateCommand(store).execute(
        application_id=first.payload["application_id"],
        job_id=job_id,
        email=first.payload["email"],
        status="recommended",
        score=80,
        skill_breakdown=[{"skill": "Python", "match": "met", "evidence": "Python services."}],
        strengths="Python",
        weaknesses="No kitchen work",
        missing_information="Years of experience",
        recommendation="Fits the backend role",
        semantic_match=0.5,
        sources=["https://example.com/standards"],
        provider="mock",
    )
    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    page = hr.get(f"/hr/jobs/{job_id}").get_data(as_text=True)
    assert "Evaluate this job" not in page
    assert application_id
