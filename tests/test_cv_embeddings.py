from src import create_app
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.job_commands import CreateJobCommand
from src.persistence.event_store import EventStore
from src.projections.cv_embeddings import CvEmbeddingProjector
from src.providers.base import LLMProvider
from tests.pdf_samples import pdf_upload
from tests.test_auth import TestConfig


class _Provider(LLMProvider):
    def __init__(self, name: str = "mock", embed=None) -> None:
        self.name = name
        self._embed = embed or (lambda text: [float(len(text)), 0.5, 0.25])

    def embed(self, text: str) -> list[float]:
        return self._embed(text)

    def evaluate(self, evidence: dict) -> dict:
        raise AssertionError("the projector does not evaluate")


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


def _store() -> EventStore:
    store = EventStore("sqlite:///:memory:")
    store.ensure_schema()
    return store


def test_projector_stores_the_cv_vector_without_appending(tmp_path):
    store = _store()
    _job, application = _application(store)
    before = store.load_by_types(("JobCreated", "ApplicationSubmitted"))
    projector = CvEmbeddingProjector(store, str(tmp_path / "chroma"), _Provider())

    assert projector.project_application(application.reference_id) is True

    stored = projector.get(application.reference_id)
    assert stored["document"] == "Built analytical engines."
    assert stored["embedding"] == [25.0, 0.5, 0.25]
    assert stored["metadata"] == {
        "job_id": _job.reference_id,
        "email": "candidate@example.com",
        "full_name": "Ada Lovelace",
        "embedding_provider": "mock",
    }
    assert store.load_by_types(("JobCreated", "ApplicationSubmitted")) == before


def test_failed_embedding_keeps_the_application_event(tmp_path):
    store = _store()
    _job, application = _application(store)

    def explode(_text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")

    projector = CvEmbeddingProjector(store, str(tmp_path / "chroma"), _Provider(embed=explode))
    assert projector.project_application(application.reference_id) is False
    assert projector.get(application.reference_id) is None
    events = store.load(application.reference_id)
    assert len(events) == 1
    assert events[0].event_type == "ApplicationSubmitted"


def test_project_missing_embeds_only_applications_not_already_stored(tmp_path):
    store = _store()
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
    projector = CvEmbeddingProjector(store, str(tmp_path / "chroma"), _Provider())
    assert projector.project_application(first.reference_id) is True
    before = store.load_by_types(("ApplicationSubmitted",))

    assert projector.project_missing() == 1

    assert projector.get(first.reference_id)["metadata"]["full_name"] == "Ada Lovelace"
    assert projector.get(second.reference_id)["document"] == "Compilers and COBOL."
    assert store.load_by_types(("ApplicationSubmitted",)) == before


def test_switching_provider_re_embeds_vectors_from_the_old_provider(tmp_path):
    store = _store()
    _job, application = _application(store)
    path = str(tmp_path / "chroma")
    assert CvEmbeddingProjector(store, path, _Provider("ollama")).project_application(application.reference_id)

    mock = CvEmbeddingProjector(store, path, _Provider("mock", embed=lambda _text: [9.0, 9.0, 9.0]))
    assert mock.project_missing() == 1
    assert mock.project_missing() == 0
    stored = mock.get(application.reference_id)
    assert stored["metadata"]["embedding_provider"] == "mock"
    assert stored["embedding"] == [9.0, 9.0, 9.0]


def test_apply_route_projects_the_cv_after_the_event_is_saved(tmp_path):
    class Config(TestConfig):
        VECTOR_DB_PATH = str(tmp_path / "chroma")

    app = create_app(Config)
    store = app.extensions["event_store"]
    projector = CvEmbeddingProjector(store, Config.VECTOR_DB_PATH, _Provider())
    app.extensions["cv_embeddings"] = projector

    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    hr.post("/hr/jobs", data={"title": "Backend engineer", "requirements": "Python and Flask"})
    job_id = app.extensions["queries"]["hr_portal"].execute().jobs[0].job_id

    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    response = candidate.post(
        f"/apply/{job_id}",
        data={"full_name": "Ada Lovelace", **pdf_upload("Built analytical engines.")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Application submitted." in response.data

    applications = store.load_by_types(("ApplicationSubmitted",))
    assert len(applications) == 1
    stored = projector.get(applications[0].aggregate_id)
    assert stored["document"] == "Built analytical engines."
    assert stored["metadata"]["job_id"] == job_id
