import inspect
import pathlib

import pytest

from src import create_app
from src.agents.candidate_evaluation import CandidateEvaluationAgent
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.base import CommandResult
from src.commands.evaluation_commands import EvaluateCandidateCommand
from src.commands.job_commands import CreateJobCommand
from src.integrations.screening_mcp import McpError
from src.persistence.event_store import EventStore
from src.projections.cv_embeddings import CvEmbeddingProjector
from src.providers import MockLLMProvider
from src.providers.base import LLMError, LLMProvider
from src.queries.cv_match import CvMatchQuery, RagError
from src.queries.portal_queries import JobDetailQuery
from tests.test_auth import TestConfig

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _store() -> EventStore:
    store = EventStore("sqlite:///:memory:")
    store.ensure_schema()
    return store


def _seed(store: EventStore, cv_text: str = "Built Flask APIs."):
    job = CreateJobCommand(store).execute(
        title="Backend engineer",
        requirements="Python and Flask",
        created_by="hr@example.com",
    )
    application = SubmitApplicationCommand(store).execute(
        job_id=job.reference_id,
        full_name="Ada Lovelace",
        email="candidate@example.com",
        cv_text=cv_text,
    )
    return job.reference_id, application.reference_id


BREAKDOWN = [
    {"skill": "Python", "match": "met", "evidence": "Python services"},
    {"skill": "Flask", "match": "missing", "evidence": ""},
]


def _report(**overrides):
    payload = {
        "application_id": "app-1",
        "job_id": "job-1",
        "email": "candidate@example.com",
        "status": "recommended",
        "score": 82,
        "skill_breakdown": BREAKDOWN,
        "strengths": "Python and Flask project work",
        "weaknesses": "No mention of tests",
        "missing_information": "Years of experience are not stated",
        "recommendation": "The CV fits the backend role",
        "semantic_match": 0.91,
        "sources": ["https://example.com/standards"],
        "provider": "ollama",
    }
    payload.update(overrides)
    return payload


class _Spy:
    def load(self, aggregate_id: str):
        raise AssertionError("database was contacted")

    def append(self, **kwargs):
        raise AssertionError("database was contacted")


class _ReadOnly:
    def __init__(self, inner: EventStore) -> None:
        self._inner = inner

    def load(self, aggregate_id: str):
        return self._inner.load(aggregate_id)

    def load_by_types(self, event_types):
        return self._inner.load_by_types(event_types)

    def append(self, **kwargs):
        raise AssertionError("agent wrote to the event store")


class _Match:
    def __init__(self, score: float = 0.25) -> None:
        self.score = score

    def match(self, application_id: str, requirements: str) -> float:
        assert requirements == "Python and Flask"
        return self.score


class _Search:
    def research(self, title: str, requirements: str, cv_text: str) -> list[dict]:
        assert title == "Backend engineer"
        return [
            {
                "title": "Backend standards",
                "url": "https://example.com/standards",
                "content": "Flask APIs are common for Python services.",
            }
        ]


class _Provider(LLMProvider):
    name = "ollama"

    def embed(self, text: str) -> list[float]:
        raise AssertionError("the agent does not embed")

    def evaluate(self, evidence: dict) -> dict:
        assert evidence["tavily_results"][0]["url"] == "https://example.com/standards"
        assert "semantic_match" in evidence
        return {
            "status": "not_recommended",
            "score": 12,
            "skill_breakdown": BREAKDOWN,
            "strengths": "Clear writing",
            "weaknesses": "The CV does not show Flask or Python delivery",
            "missing_information": "No project dates",
            "recommendation": "Do not proceed",
            "sources": ["https://invented.example"],
        }


class _Command:
    def __init__(self) -> None:
        self.payloads = []

    def execute(self, **kwargs):
        self.payloads.append(kwargs)
        return CommandResult.ok(reference_id=kwargs["application_id"])


class _BrokenMatch:
    def match(self, application_id: str, requirements: str) -> float:
        raise RagError("vector missing")


class _BrokenSearch:
    def research(self, title: str, requirements: str, cv_text: str) -> list[dict]:
        raise McpError("mcp down")


class _BrokenProvider(_Provider):
    def evaluate(self, evidence: dict) -> dict:
        raise LLMError("model down")


class _NoBreakdownProvider(_Provider):
    def evaluate(self, evidence: dict) -> dict:
        return {**super().evaluate(evidence), "skill_breakdown": []}


def test_command_appends_candidate_evaluated_without_returning_the_report():
    store = _store()
    job_id, application_id = _seed(store)
    result = EvaluateCandidateCommand(store).execute(**_report(application_id=application_id, job_id=job_id))

    assert result.success is True
    assert result.reference_id == application_id
    assert result.message == ""
    events = store.load(application_id)
    assert [event.event_type for event in events] == ["ApplicationSubmitted", "CandidateEvaluated"]
    assert events[1].aggregate_type == "Application"
    assert events[1].version == 2
    assert events[1].payload["status"] == "recommended"
    assert events[1].payload["score"] == 82
    assert events[1].payload["skill_breakdown"] == BREAKDOWN
    assert events[1].payload["provider"] == "ollama"
    assert events[1].payload["sources"] == ["https://example.com/standards"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"score": 140, "status": "maybe"},
        {"skill_breakdown": []},
        {"skill_breakdown": [{"skill": "Python", "match": "sort of", "evidence": ""}]},
        {"provider": "openai"},
    ],
)
def test_command_rejects_a_bad_report_before_the_database(overrides):
    result = EvaluateCandidateCommand(_Spy()).execute(**_report(**overrides))
    assert result.success is False
    assert result.reference_id is None


def test_command_rejects_an_unknown_or_repeated_application():
    store = _store()
    missing = EvaluateCandidateCommand(store).execute(**_report())
    assert missing.success is False
    assert store.load_by_types(("CandidateEvaluated",)) == []

    job_id, application_id = _seed(store)
    command = EvaluateCandidateCommand(store)
    assert command.execute(**_report(application_id=application_id, job_id=job_id)).success is True
    again = command.execute(**_report(application_id=application_id, job_id=job_id))
    assert again.success is False
    evaluated = [event for event in store.load(application_id) if event.event_type == "CandidateEvaluated"]
    assert len(evaluated) == 1


def test_rag_ranks_a_related_cv_above_an_unrelated_cv_without_upsert(tmp_path):
    store = _store()
    _job, flask_id = _seed(store, cv_text="Python backend services with Flask API development.")
    _job, chef_id = _seed(store, cv_text="Restaurant kitchen work and menu planning.")
    path = str(tmp_path / "chroma")
    mock = MockLLMProvider()
    projector = CvEmbeddingProjector(store, path, mock)
    assert projector.project_missing() == 2

    matcher = CvMatchQuery(path, mock)
    before = list(matcher._collection().get(include=[])["ids"])
    flask_score = matcher.match(flask_id, "Python Backend")
    chef_score = matcher.match(chef_id, "Python Backend")

    assert flask_score > chef_score
    assert list(matcher._collection().get(include=[])["ids"]) == before
    assert "upsert" not in inspect.getsource(CvMatchQuery)


def test_rag_refuses_to_compare_vectors_from_another_provider(tmp_path):
    store = _store()
    _job, application_id = _seed(store)
    path = str(tmp_path / "chroma")
    CvEmbeddingProjector(store, path, MockLLMProvider()).project_application(application_id)

    class _OtherProvider(MockLLMProvider):
        name = "ollama"

    with pytest.raises(RagError, match="python -m src.projections"):
        CvMatchQuery(path, _OtherProvider()).match(application_id, "Python")


def test_missing_vector_fails_the_rag_read(tmp_path):
    with pytest.raises(RagError):
        CvMatchQuery(str(tmp_path / "chroma"), MockLLMProvider()).match("missing", "Python Backend")


def test_agent_issues_the_command_and_does_not_write_the_event_store():
    store = _store()
    _job_id, application_id = _seed(store)
    command = _Command()
    agent = CandidateEvaluationAgent(
        events=_ReadOnly(store),
        match=_Match(),
        search=_Search(),
        provider=_Provider(),
        command=command,
    )

    assert agent.run() == 1
    payload = command.payloads[0]
    assert payload["application_id"] == application_id
    assert payload["status"] == "not_recommended"
    assert payload["score"] == 12
    assert payload["skill_breakdown"] == BREAKDOWN
    assert payload["provider"] == "ollama"
    assert payload["semantic_match"] == 0.25
    assert payload["sources"] == ["https://example.com/standards"]


def test_failed_rag_tavily_model_or_report_appends_nothing():
    store = _store()
    _job_id, application_id = _seed(store)
    command = EvaluateCandidateCommand(store)
    failures = (
        CandidateEvaluationAgent(store, _BrokenMatch(), _Search(), _Provider(), command),
        CandidateEvaluationAgent(store, _Match(), _BrokenSearch(), _Provider(), command),
        CandidateEvaluationAgent(store, _Match(), _Search(), _BrokenProvider(), command),
        CandidateEvaluationAgent(store, _Match(), _Search(), _NoBreakdownProvider(), command),
    )
    for agent in failures:
        assert agent.run() == 0
    assert [event.event_type for event in store.load(application_id)] == ["ApplicationSubmitted"]


def test_successful_run_records_one_assessment_and_skips_it_next_time():
    store = _store()
    job_id, application_id = _seed(store)
    agent = CandidateEvaluationAgent(
        events=store,
        match=_Match(0.84),
        search=_Search(),
        provider=_Provider(),
        command=EvaluateCandidateCommand(store),
    )

    assert agent.run() == 1
    assert agent.run() == 0
    evaluated = [event for event in store.load(application_id) if event.event_type == "CandidateEvaluated"]
    assert len(evaluated) == 1
    assert evaluated[0].payload["job_id"] == job_id
    assert evaluated[0].payload["semantic_match"] == 0.84
    assert evaluated[0].payload["sources"] == ["https://example.com/standards"]
    assert "invented.example" not in evaluated[0].payload["sources"]


def test_mock_provider_runs_the_whole_pipeline_offline(tmp_path):
    store = _store()
    _job_id, application_id = _seed(store, cv_text="Five years of Python. Built Flask APIs.")
    path = str(tmp_path / "chroma")
    mock = MockLLMProvider()
    CvEmbeddingProjector(store, path, mock).project_application(application_id)
    agent = CandidateEvaluationAgent(store, CvMatchQuery(path, mock), _Search(), mock, EvaluateCandidateCommand(store))

    assert agent.run() == 1
    payload = store.load(application_id)[-1].payload
    assert payload["provider"] == "mock"
    assert {item["skill"] for item in payload["skill_breakdown"]} == {"python", "flask"}
    assert all(item["match"] == "met" for item in payload["skill_breakdown"])


def test_agent_code_never_calls_tavily_or_ollama_directly():
    agent_sources = [
        SRC / "agents" / "candidate_evaluation.py",
        SRC / "integrations" / "screening_mcp.py",
    ]
    for path in agent_sources:
        text = path.read_text(encoding="utf-8")
        assert "api.tavily.com" not in text
        assert "urllib" not in text
        assert "11434" not in text
    tavily_users = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "api.tavily.com" in path.read_text(encoding="utf-8")
    ]
    assert tavily_users == ["mcp_server/tavily.py"]
