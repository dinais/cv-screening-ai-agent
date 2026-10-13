from src.commands.application_commands import SubmitApplicationCommand
from src.commands.job_commands import CreateJobCommand
from src.persistence.event_store import EventStore


class _Spy:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def load(self, aggregate_id: str):
        raise AssertionError("database was contacted")

    def append(self, **kwargs):
        raise AssertionError("database was contacted")


def _store() -> EventStore:
    store = EventStore("sqlite:///:memory:")
    store.ensure_schema()
    return store


def test_create_job_appends_job_created():
    store = _store()
    result = CreateJobCommand(store).execute(
        title="Backend engineer",
        requirements="Python and Flask",
        created_by="hr@example.com",
    )
    assert result.success is True
    events = store.load(result.reference_id)
    assert len(events) == 1
    assert events[0].aggregate_type == "Job"
    assert events[0].event_type == "JobCreated"
    assert events[0].payload == {
        "job_id": result.reference_id,
        "title": "Backend engineer",
        "requirements": "Python and Flask",
        "created_by": "hr@example.com",
    }
    assert events[0].version == 1


def test_create_job_rejects_missing_fields_before_the_database():
    result = CreateJobCommand(_Spy()).execute(title="  ", requirements="", created_by="hr@example.com")
    assert result.success is False
    assert result.reference_id is None


def test_submit_application_appends_application_submitted():
    store = _store()
    job = CreateJobCommand(store).execute(
        title="Backend engineer",
        requirements="Python and Flask",
        created_by="hr@example.com",
    )
    result = SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="Built analytical engines.",
    )
    assert result.success is True
    events = store.load(result.reference_id)
    assert len(events) == 1
    assert events[0].aggregate_type == "Application"
    assert events[0].event_type == "ApplicationSubmitted"
    assert events[0].payload["job_id"] == job.reference_id
    assert events[0].payload["cv_text"] == "Built analytical engines."
    assert store.load(job.reference_id)[0].event_type == "JobCreated"


def test_submit_application_rejects_missing_fields_before_the_database():
    result = SubmitApplicationCommand(_Spy()).execute(
        job_id="",
        full_name="",
        email="candidate@example.com",
        cv_text="CV",
    )
    assert result.success is False


def test_submit_application_rejects_an_unknown_job_without_appending():
    class ReadOnly:
        def load(self, aggregate_id: str):
            return []

        def append(self, **kwargs):
            raise AssertionError("database was written")

    result = SubmitApplicationCommand(ReadOnly()).execute(
        job_id="missing-job",
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="CV",
    )
    assert result.success is False
    assert result.message == "Unknown job."


def test_submit_application_rejects_a_duplicate_without_appending():
    store = _store()
    job = CreateJobCommand(store).execute(
        title="Backend engineer",
        requirements="Python and Flask",
        created_by="hr@example.com",
    )

    class Guard:
        def load(self, aggregate_id: str):
            return store.load(aggregate_id)

        def load_by_types(self, event_types):
            return store.load_by_types(event_types)

        def append(self, **kwargs):
            raise AssertionError("database was written")

    first = SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text="Built analytical engines.",
    )
    assert first.success is True
    duplicate = SubmitApplicationCommand(Guard()).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="Candidate@Example.com",
        cv_text="A second copy.",
    )
    assert duplicate.success is False
    assert duplicate.message == "You have already applied to this job."
    submitted = store.load_by_types(("ApplicationSubmitted",))
    assert len(submitted) == 1


def test_commands_are_registered_on_the_app():
    from src import create_app
    from tests.test_auth import TestConfig

    app = create_app(TestConfig)
    assert "create_job" in app.extensions["commands"]
    assert "submit_application" in app.extensions["commands"]
