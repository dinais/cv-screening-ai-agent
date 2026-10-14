import inspect
import json
import math
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from src.providers import MockLLMProvider, OllamaProvider, provider_from_config
from src.providers.base import LLMError
from src.providers.ollama import production_deep_agent
from src.providers.report import ReportError, parse_model_text, require_report


def _cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    return dot / (math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right)))


def _evidence(cv_text: str, semantic_match: float = 0.5) -> dict:
    return {
        "job_title": "Backend engineer",
        "requirements": "Python, Flask and Kubernetes",
        "full_name": "Ada Lovelace",
        "cv_text": cv_text,
        "semantic_match": semantic_match,
        "tavily_results": [],
    }


def _report(**overrides) -> dict:
    report = {
        "status": "recommended",
        "score": 80,
        "skill_breakdown": [{"skill": "Python", "match": "met", "evidence": "Flask APIs"}],
        "strengths": "Python",
        "weaknesses": "No tests",
        "missing_information": "Dates",
        "recommendation": "Proceed",
    }
    report.update(overrides)
    return report


class _Config:
    LLM_PROVIDER = "ollama"
    OLLAMA_BASE_URL = "http://localhost:11434"
    OLLAMA_EMBED_MODEL = "nomic-embed-text"
    OLLAMA_CHAT_MODEL = "llama3.2"


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_provider_is_chosen_by_config_with_no_fallback():
    assert isinstance(provider_from_config(_Config), OllamaProvider)

    class Mock(_Config):
        LLM_PROVIDER = " Mock "

    assert isinstance(provider_from_config(Mock), MockLLMProvider)

    class Unknown(_Config):
        LLM_PROVIDER = "openai"

    with pytest.raises(ValueError):
        provider_from_config(Unknown)


def test_mock_embedding_is_deterministic_and_rewards_shared_words():
    mock = MockLLMProvider()
    python_cv = mock.embed("Built Python Flask APIs.")
    assert len(python_cv) == 768
    assert python_cv == mock.embed("Built Python Flask APIs.")
    requirements = mock.embed("Python and Flask")
    chef_cv = mock.embed("Ran a restaurant kitchen.")
    assert _cosine(requirements, python_cv) > _cosine(requirements, chef_cv)
    with pytest.raises(LLMError):
        mock.embed("   ")


def test_mock_evaluation_builds_a_valid_report_from_the_evidence():
    mock = MockLLMProvider()
    report = require_report(mock.evaluate(_evidence("Five years of Python. Built Flask APIs.", 0.9)))
    skills = {item["skill"]: item for item in report["skill_breakdown"]}
    assert set(skills) == {"python", "flask", "kubernetes"}
    assert skills["python"]["match"] == "met"
    assert skills["python"]["evidence"] == "Five years of Python."
    assert skills["kubernetes"] == {"skill": "kubernetes", "match": "missing", "evidence": ""}
    assert report["status"] == "recommended"
    assert report["score"] == round(100 * (0.6 * 2 / 3 + 0.4 * 0.9))
    assert report["recommendation"].startswith("Mock evaluation.")

    chef = require_report(mock.evaluate(_evidence("Ran a restaurant kitchen.", 0.05)))
    assert chef["status"] == "not_recommended"
    assert chef["score"] < report["score"]


def test_mock_makes_no_network_call(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network was used")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    mock = MockLLMProvider()
    mock.embed("Python")
    mock.evaluate(_evidence("Python"))


def test_mock_rejects_requirements_with_no_skill():
    with pytest.raises(LLMError):
        MockLLMProvider().evaluate({"requirements": "and, or", "cv_text": "Python"})


def test_ollama_embedding_request_goes_to_local_ollama(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response({"embeddings": [[0.1, 0.2]]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert OllamaProvider().embed("plain cv") == [0.1, 0.2]
    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["body"] == {"model": "nomic-embed-text", "input": "plain cv"}


def test_ollama_evaluation_uses_the_deep_agent_first(monkeypatch):
    class _Agent:
        def invoke(self, request):
            evidence = json.loads(request["messages"][0]["content"])
            assert evidence["cv_text"] == "Flask"
            return {"messages": [SimpleNamespace(content="Here it is: " + json.dumps(_report(score=91.6)))]}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the fallback should not run")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    seen = {}

    def factory(base_url, model, prompt):
        seen.update(base_url=base_url, model=model, prompt=prompt)
        return _Agent()

    report = OllamaProvider(deep_agent_factory=factory).evaluate({"cv_text": "Flask"})
    assert report["score"] == 92
    assert seen["model"] == "llama3.2"
    assert "skill_breakdown" in seen["prompt"]


def test_ollama_retries_once_with_the_report_schema(monkeypatch):
    captured = {}

    def broken_agent(*_args):
        raise RuntimeError("deep agent failed")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response({"message": {"content": json.dumps(_report())}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    report = OllamaProvider(deep_agent_factory=broken_agent).evaluate({"cv_text": "Flask"})
    assert report["status"] == "recommended"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert "skill_breakdown" in captured["body"]["format"]["required"]


def test_ollama_down_raises_instead_of_falling_back_to_mock(monkeypatch):
    def down(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")

    def broken_agent(*_args):
        raise RuntimeError("deep agent failed")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    provider = OllamaProvider(deep_agent_factory=broken_agent)
    with pytest.raises(LLMError):
        provider.embed("Python")
    with pytest.raises(LLMError):
        provider.evaluate({"cv_text": "Python"})


def test_deep_agent_runtime_uses_local_ollama():
    source = inspect.getsource(production_deep_agent)
    assert "create_deep_agent" in source
    assert "ChatOllama" in source
    assert "openai" not in source.lower()


def test_report_requires_a_skill_breakdown():
    with pytest.raises(ReportError):
        require_report(_report(skill_breakdown=[]))
    with pytest.raises(ReportError):
        require_report(_report(skill_breakdown=[{"skill": "Python", "match": "maybe", "evidence": ""}]))


def test_report_clears_evidence_for_missing_skills_and_clamps_the_score():
    report = require_report(
        _report(score="about 140/100", skill_breakdown=[{"skill": "Go", "match": "Missing", "evidence": "invented"}])
    )
    assert report["score"] == 100
    assert report["skill_breakdown"] == [{"skill": "Go", "match": "missing", "evidence": ""}]


def test_report_json_is_read_when_the_model_adds_prose():
    text = "The candidate fits the role.\n" + json.dumps(_report(status="not recommended", score="81"))
    report = require_report(parse_model_text(text))
    assert report["status"] == "not_recommended"
    assert report["score"] == 81
