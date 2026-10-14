import inspect

from src import create_app
from src.agents.candidate_evaluation import (
    CandidateEvaluationAgent,
    DeepAgentJudge,
    _parse_model_text,
    _production_deep_agent,
    _require_report,
)
from src.commands.application_commands import SubmitApplicationCommand
from src.commands.base import CommandResult
from src.commands.evaluation_commands import EvaluateCandidateCommand
from src.commands.job_commands import CreateJobCommand
from src.integrations.tavily_mcp import McpError, TavilyMcpSearch, parse_tavily_results
from src.persistence.event_store import EventStore
from src.queries.cv_match import CvMatchQuery, RagError
from src.queries.portal_queries import JobDetailQuery
from tests.test_auth import TestConfig


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


def _report(**overrides):
    payload = {
        "application_id": "app-1",
        "job_id": "job-1",
        "email": "candidate@example.com",
        "status": "recommended",
        "score": 82,
        "strengths": "Python and Flask project work",
        "weaknesses": "No mention of tests",
        "missing_information": "Years of experience are not stated",
        "recommendation": "The CV fits the backend role",
        "semantic_match": 0.91,
        "sources": ["https://example.com/standards"],
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


class _Judge:
    def judge(self, evidence: dict) -> dict:
        assert evidence["tavily_results"][0]["url"] == "https://example.com/standards"
        assert "semantic_match" in evidence
        return {
            "status": "not_recommended",
            "score": 12,
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
    assert events[1].payload["sources"] == ["https://example.com/standards"]


def test_command_rejects_a_bad_report_before_the_database():
    result = EvaluateCandidateCommand(_Spy()).execute(**_report(score=140, status="maybe"))
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
    def embed(text: str) -> list[float]:
        if "python" in text.lower():
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]

    matcher = CvMatchQuery(str(tmp_path / "chroma"), embed=embed)
    collection = matcher._collection()
    collection.upsert(
        ids=["flask-cv", "chef-cv"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        documents=["Flask API development", "Restaurant kitchen work"],
        metadatas=[{"job_id": "job"}, {"job_id": "job"}],
    )
    before = list(collection.get(include=[])["ids"])

    flask_score = matcher.match("flask-cv", "Python Backend")
    chef_score = matcher.match("chef-cv", "Python Backend")

    assert flask_score == 1
    assert chef_score == 0
    assert flask_score > chef_score
    assert list(collection.get(include=[])["ids"]) == before
    assert "upsert" not in inspect.getsource(CvMatchQuery)


def test_missing_vector_fails_the_rag_read(tmp_path):
    matcher = CvMatchQuery(str(tmp_path / "chroma"), embed=lambda _text: [1.0, 0.0])
    try:
        matcher.match("missing", "Python Backend")
    except RagError:
        return
    raise AssertionError("missing vector should fail the read")


def test_tavily_search_uses_the_mcp_tool_name():
    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        return {"results": [{"title": "Standards", "url": "https://example.com/a", "content": "APIs"}]}

    search = TavilyMcpSearch("test-key", call_tool=call_tool)
    hits = search.research("Backend engineer", "Python and Flask", "Ada at Analytical Engines")

    assert [call[0] for call in calls] == ["tavily_search", "tavily_search"]
    assert "Python and Flask" in calls[0][1]["query"]
    assert hits == [{"title": "Standards", "url": "https://example.com/a", "content": "APIs"}]
    spec = search.server_spec()
    assert spec.args == ("-y", "tavily-mcp")
    assert "api.tavily.com" not in " ".join(spec.args)
    assert "api.tavily.com" not in inspect.getsource(TavilyMcpSearch)


def test_tavily_parser_reads_json_mixed_with_logs_or_plain_text():
    mixed = (
        "npm notice created a lockfile\n"
        '{"results": [{"title": "Standards", "url": "https://example.com/a", "content": "APIs"}]}'
    )
    assert parse_tavily_results(mixed)[0]["url"] == "https://example.com/a"
    plain = "Title: Standards\nURL: https://example.com/b\nContent: Flask services\n"
    assert parse_tavily_results(plain) == [
        {"title": "Standards", "url": "https://example.com/b", "content": "Flask services"}
    ]
    try:
        parse_tavily_results("Error: invalid API key")
    except McpError as exc:
        assert "invalid API key" in str(exc)
        return
    raise AssertionError("a plain tool error should be reported")


def test_tavily_without_a_key_fails_before_a_tool_call():
    def call_tool(_name, _arguments):
        raise AssertionError("tool was called")

    search = TavilyMcpSearch("", call_tool=call_tool)
    try:
        search.search("Python")
    except McpError:
        return
    raise AssertionError("missing key should fail")


def test_agent_issues_the_command_and_does_not_write_the_event_store():
    store = _store()
    _job_id, application_id = _seed(store)
    command = _Command()
    agent = CandidateEvaluationAgent(
        events=_ReadOnly(store),
        match=_Match(),
        search=_Search(),
        judge=_Judge(),
        command=command,
    )

    assert agent.run() == 1
    assert command.payloads[0]["application_id"] == application_id
    assert command.payloads[0]["status"] == "not_recommended"
    assert command.payloads[0]["score"] == 12
    assert command.payloads[0]["semantic_match"] == 0.25
    assert command.payloads[0]["sources"] == ["https://example.com/standards"]


def test_failed_rag_tavily_or_model_appends_nothing():
    store = _store()
    _job_id, application_id = _seed(store)
    command = EvaluateCandidateCommand(store)
    failures = (
        CandidateEvaluationAgent(store, _BrokenMatch(), _Search(), _Judge(), command),
        CandidateEvaluationAgent(store, _Match(), _BrokenSearch(), _Judge(), command),
        CandidateEvaluationAgent(store, _Match(), _Search(), _BrokenJudge(), command),
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
        judge=_Judge(),
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


def test_score_parser_reads_a_number_inside_the_model_text():
    report = _require_report({
        "status": "recommended",
        "score": "about 85/100",
        "strengths": "Python",
        "weaknesses": "No tests",
        "missing_information": "Dates",
        "recommendation": "Proceed",
    })
    assert report["score"] == 85

    missing = _require_report({
        "status": "not_recommended",
        "score": "unknown",
        "strengths": "Writing",
        "weaknesses": "No relevant work",
        "missing_information": "Tools",
        "recommendation": "Stop",
    })
    assert missing["score"] == 0


def test_report_json_is_read_when_the_model_adds_prose():
    text = (
        "The candidate fits the role.\n"
        '{"status": "not recommended", "score": "81", "strengths": "Python", '
        '"weaknesses": "No tests", "missing_information": "Dates", "recommendation": "Proceed"}'
    )
    report = _require_report(_parse_model_text(text))
    assert report["status"] == "not_recommended"
    assert report["score"] == 81
    assert report["strengths"] == "Python"


def test_deep_agent_runtime_uses_local_ollama():
    source = inspect.getsource(_production_deep_agent)
    assert "create_deep_agent" in source
    assert "ChatOllama" in source
    assert "openai" not in source.lower()

    judge = DeepAgentJudge("http://localhost:11434", "llama3.2", complete=lambda _evidence: {
        "status": "recommended",
        "score": 80.0,
        "strengths": "Flask APIs",
        "weaknesses": "Thin testing detail",
        "missing_information": "Team size",
        "recommendation": "Proceed to HR review",
    })
    report = judge.judge({"cv_text": "Flask"})
    assert report["score"] == 80
    assert report["status"] == "recommended"


def test_hr_drill_down_shows_the_assessment_beside_the_cv():
    app = create_app(TestConfig)
    store = app.extensions["event_store"]
    job_id, application_id = _seed(store, cv_text="Analytical engines.")
    EvaluateCandidateCommand(store).execute(
        **_report(
            application_id=application_id,
            job_id=job_id,
            strengths="Strong analytical work",
            semantic_match=0.5,
        )
    )
    detail = JobDetailQuery(store).execute(job_id)
    person = detail.applicant_list[0]
    assert person.full_name == "Ada Lovelace"
    assert person.cv_text == "Analytical engines."
    assert person.assessment.status == "recommended"
    assert person.assessment.strengths == "Strong analytical work"
    assert person.assessment.semantic_match == 0.5

    client = app.test_client()
    client.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    page = client.get(f"/hr/jobs/{job_id}")
    assert page.status_code == 200
    assert b"Analytical engines." in page.data
    assert b"Strong analytical work" in page.data
    assert b"recommended" in page.data
    assert b"https://example.com/standards" in page.data
    assert "CandidateEvaluationAgent" not in inspect.getsource(create_app)


class _BrokenMatch:
    def match(self, application_id: str, requirements: str) -> float:
        raise RagError("vector missing")


class _BrokenSearch:
    def research(self, title: str, requirements: str, cv_text: str) -> list[dict]:
        raise McpError("mcp down")


class _BrokenJudge:
    def judge(self, evidence: dict) -> dict:
        raise RuntimeError("model down")
