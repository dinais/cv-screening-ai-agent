from src import create_app
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.job_commands import CreateJobCommand
from src.persistence.event_store import EventStore
from src.projections.cv_embeddings import CvEmbeddingProjector
from tests.test_auth import TestConfig


def _embed(text: str) -> list[float]:
    return [float(len(text)), 0.5, 0.25]


def _application(store: EventStore, title: str = "Backend engineer"):
    job = CreateJobCommand(store).execute(
        title=title,
        requirements="Python and Flask",
        created_by="hr@example.com",
    )
    application = SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="Built analytical engines.",
    )
    return job, application


def test_projector_stores_the_cv_vector_without_appending(tmp_path):
    store = EventStore("sqlite:///:memory:")
    store.ensure_schema()
    _job, application = _application(store)
    before = store.load_by_types(("JobCreated", "ApplicationSubmitted"))
    projector = CvEmbeddingProjector(store, str(tmp_path / "chroma"), embed=_embed)

    assert projector.project_application(application.reference_id) is True

    stored = projector.get(application.reference_id)
    assert stored["document"] == "Built analytical engines."
    assert stored["embedding"] == [25.0, 0.5, 0.25]
    assert stored["metadata"] == {
        "job_id": _job.reference_id,
        "email": "candidate@example.com",
        "full_name": "Ada Lovelace",
    }
    assert store.load_by_types(("JobCreated", "ApplicationSubmitted")) == before


def test_failed_embedding_keeps_the_application_event(tmp_path):
    store = EventStore("sqlite:///:memory:")
    store.ensure_schema()
    _job, application = _application(store)

    def explode(_text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")

    projector = CvEmbeddingProjector(store, str(tmp_path / "chroma"), embed=explode)
    assert projector.project_application(application.reference_id) is False
    assert projector.get(application.reference_id) is None
    events = store.load(application.reference_id)
    assert len(events) == 1
    assert events[0].event_type == "ApplicationSubmitted"


def test_project_missing_embeds_only_applications_not_already_stored(tmp_path):
    store = EventStore("sqlite:///:memory:")
    store.ensure_schema()
    _first_job, first = _application(store, "Backend engineer")
    second_job = CreateJobCommand(store).execute(
        title="Data engineer",
        requirements="SQL",
        created_by="hr@example.com",
    )
    second = SubmitApplicationCommand(store).execute(
        job_id=second_job.reference_id,
        full_name="Grace Hopper",
        email="grace@example.com",
        cv_text="Compilers and COBOL.",
    )
    projector = CvEmbeddingProjector(store, str(tmp_path / "chroma"), embed=_embed)
    assert projector.project_application(first.reference_id) is True
    before = store.load_by_types(("ApplicationSubmitted",))

    assert projector.project_missing() == 1

    assert projector.get(first.reference_id)["metadata"]["full_name"] == "Ada Lovelace"
    assert projector.get(second.reference_id)["document"] == "Compilers and COBOL."
    assert store.load_by_types(("ApplicationSubmitted",)) == before


def test_apply_route_projects_the_cv_after_the_event_is_saved(tmp_path):
    class Config(TestConfig):
        VECTOR_DB_PATH = str(tmp_path / "chroma")

    app = create_app(Config)
    store = app.extensions["event_store"]
    projector = CvEmbeddingProjector(store, Config.VECTOR_DB_PATH, embed=_embed)
    app.extensions["cv_embeddings"] = projector

    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    hr.post("/hr/jobs", data={"title": "Backend engineer", "requirements": "Python and Flask"})
    job_id = app.extensions["queries"]["hr_portal"].execute().jobs[0].job_id

    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    response = candidate.post(
        f"/apply/{job_id}",
        data={"full_name": "Ada Lovelace", "cv_text": "Built analytical engines."},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Application submitted." in response.data

    applications = store.load_by_types(("ApplicationSubmitted",))
    assert len(applications) == 1
    stored = projector.get(applications[0].aggregate_id)
    assert stored["document"] == "Built analytical engines."
    assert stored["metadata"]["job_id"] == job_id


def test_embedding_request_goes_to_local_ollama(monkeypatch, tmp_path):
    import json
    import urllib.request

    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"embeddings": [[0.1, 0.2]]}'

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    store = EventStore("sqlite:///:memory:")
    projector = CvEmbeddingProjector(
        store,
        str(tmp_path / "chroma"),
        base_url="http://localhost:11434",
        model="nomic-embed-text",
    )
    assert projector._embed_text("plain cv") == [0.1, 0.2]
    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["body"] == {"model": "nomic-embed-text", "input": "plain cv"}
