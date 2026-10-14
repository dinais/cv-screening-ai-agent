import json
from types import SimpleNamespace

import pytest

from src.integrations.screening_mcp import McpError, ScreeningMcpClient, _tool_payload
from src.mcp_server.server import semantic_cv_match_tool, web_search_tool
from src.mcp_server.tavily import TAVILY_SEARCH_URL, TavilyError, tavily_search
from src.persistence.event_store import EventStore
from src.projections.cv_embeddings import CvEmbeddingProjector
from src.providers import MockLLMProvider
from src.queries.cv_match import CvMatchQuery, RagError
from tests.test_evaluation import _seed, _store


class _Response:
    def __init__(self, body) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_tavily_search_posts_the_query_with_the_api_key():
    captured = {}

    def urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {"results": [{"title": "Standards", "url": "https://example.com/a", "content": "APIs"}, {"title": "no url"}]}
        )

    hits = tavily_search("tvly-key", "Python backend", 3, urlopen=urlopen)
    assert captured == {
        "url": TAVILY_SEARCH_URL,
        "auth": "Bearer tvly-key",
        "body": {"query": "Python backend", "max_results": 3},
    }
    assert hits == [{"title": "Standards", "url": "https://example.com/a", "content": "APIs"}]


@pytest.mark.parametrize(
    ("api_key", "query", "max_results"),
    [("", "Python", 5), ("key", "  ", 5), ("key", "Python", 0), ("key", "Python", 11)],
)
def test_tavily_search_rejects_bad_input_before_any_request(api_key, query, max_results):
    def urlopen(*_args, **_kwargs):
        raise AssertionError("request was sent")

    with pytest.raises(TavilyError):
        tavily_search(api_key, query, max_results, urlopen=urlopen)


def test_web_search_tool_needs_the_key():
    with pytest.raises(TavilyError, match="TAVILY_API_KEY"):
        web_search_tool("Python", 5, SimpleNamespace(TAVILY_API_KEY=""))


def test_semantic_cv_match_tool_reads_without_writing(tmp_path):
    store = _store()
    _job, application_id = _seed(store, cv_text="Python and Flask services.")
    path = str(tmp_path / "chroma")
    mock = MockLLMProvider()
    CvEmbeddingProjector(store, path, mock).project_application(application_id)
    events_before = store.load_by_types(("ApplicationSubmitted", "CandidateEvaluated"))
    matcher = CvMatchQuery(path, mock)

    result = semantic_cv_match_tool(application_id, "Python and Flask", matcher)
    assert result["application_id"] == application_id
    assert 0 < result["semantic_match"] <= 1
    assert store.load_by_types(("ApplicationSubmitted", "CandidateEvaluated")) == events_before
    with pytest.raises(RagError):
        semantic_cv_match_tool("unknown", "Python", matcher)


def test_client_reads_structured_results_and_reports_tool_errors():
    structured = SimpleNamespace(content=[], structured_content={"semantic_match": 0.7}, is_error=False)
    assert _tool_payload(structured) == {"semantic_match": 0.7}
    wrapped = SimpleNamespace(content=[], structured_content={"result": {"results": []}}, is_error=False)
    assert _tool_payload(wrapped) == {"results": []}
    text = SimpleNamespace(content=[SimpleNamespace(text='{"results": []}')], structured_content=None, is_error=False)
    assert _tool_payload(text) == {"results": []}
    failed = SimpleNamespace(content=[SimpleNamespace(text="TAVILY_API_KEY is missing.")], is_error=True)
    with pytest.raises(McpError, match="TAVILY_API_KEY"):
        _tool_payload(failed)


def test_client_research_calls_web_search_twice_and_dedupes():
    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        return {"results": [{"title": "A", "url": "https://example.com/a", "content": ""}]}

    client = ScreeningMcpClient(call_tool=call_tool)
    hits = client.research("Backend engineer", "Python and Flask", "Ada at Analytical Engines")
    assert [name for name, _args in calls] == ["web_search", "web_search"]
    assert "Python and Flask" in calls[0][1]["query"]
    assert hits == [{"title": "A", "url": "https://example.com/a", "content": ""}]


def test_client_match_rejects_a_reply_without_a_score():
    client = ScreeningMcpClient(call_tool=lambda _name, _args: {"application_id": "a"})
    with pytest.raises(McpError):
        client.match("a", "Python")


def test_screening_mcp_runs_over_stdio(tmp_path, monkeypatch):
    database = tmp_path / "events.sqlite"
    vectors = str(tmp_path / "chroma")
    store = EventStore(f"sqlite:///{database.as_posix()}")
    store.ensure_schema()
    _job, application_id = _seed(store, cv_text="Python and Flask services.")
    CvEmbeddingProjector(store, vectors, MockLLMProvider()).project_application(application_id)
    store.close()

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("VECTOR_DB_PATH", vectors)
    monkeypatch.setenv("TAVILY_API_KEY", "")

    with ScreeningMcpClient() as client:
        score = client.match(application_id, "Python and Flask")
        assert 0 < score <= 1
        with pytest.raises(McpError, match="TAVILY_API_KEY"):
            client.web_search("Python")
        with pytest.raises(McpError):
            client.match("unknown", "Python")
