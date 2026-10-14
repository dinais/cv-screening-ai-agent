"""Independent candidate evaluation process.

Run it with `py -3.14 -m src.agents`. Flask does not import or start this process.
The process reads events, queries Chroma, calls Tavily through MCP, asks a Deep Agent
backed by local Ollama to judge fit, and records the result only by issuing
EvaluateCandidateCommand.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from src.commands.evaluation_commands import EvaluateCandidateCommand
from src.integrations.tavily_mcp import TavilyMcpSearch
from src.persistence.event_store import EventStore, StoredEvent
from src.queries.cv_match import CvMatchQuery

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You judge whether one candidate fits one job.
Use only the CV text, the semantic match score, and the Tavily results in the user message.
Do not invent employers, skills, dates, or sources.
Return one JSON object and nothing else.
Keys:
- status: recommended or not_recommended
- score: integer from 0 to 100
- strengths: string
- weaknesses: string
- missing_information: string
- recommendation: string
recommended means the CV fits the requirements. not_recommended means it does not.
You do not accept or reject the candidate. That decision belongs to HR.
""".strip()


class EvaluationStepError(RuntimeError):
    """RAG, Tavily, or the model call failed. No event is recorded."""


@dataclass(frozen=True)
class PendingApplication:
    application_id: str
    job_id: str
    title: str
    requirements: str
    full_name: str
    email: str
    cv_text: str


class DeepAgentJudge:
    """Step 5. The live model is a Deep Agent using local Ollama."""

    def __init__(self, base_url: str, model: str, complete=None) -> None:
        self._base_url = (base_url or "http://localhost:11434").rstrip("/")
        self._model = model or "llama3.2"
        self._complete = complete

    def judge(self, evidence: dict) -> dict:
        if self._complete is not None:
            return _require_report(self._complete(evidence))
        try:
            agent = _production_deep_agent(self._base_url, self._model, SYSTEM_PROMPT)
            result = agent.invoke({"messages": [{"role": "user", "content": json.dumps(evidence)}]})
            return _require_report(_parse_model_text(_message_text(result)))
        except Exception:
            logger.warning(
                "Deep Agent did not return a JSON report. Asking local Ollama model %s for JSON.",
                self._model,
            )
            return _require_report(_direct_ollama_report(self._base_url, self._model, evidence))


class CandidateEvaluationAgent:
    def __init__(
        self,
        events: EventStore,
        match: CvMatchQuery,
        search: TavilyMcpSearch,
        judge: DeepAgentJudge,
        command: EvaluateCandidateCommand,
    ) -> None:
        self._events = events
        self._match = match
        self._search = search
        self._judge = judge
        self._command = command

    def run(self) -> int:
        recorded = 0
        for item in select_pending(self._events):
            try:
                semantic_match = self._match.match(item.application_id, item.requirements)
                hits = self._search.research(item.title, item.requirements, item.cv_text)
                report = self._judge.judge(_evidence(item, semantic_match, hits))
                payload = _payload(item, semantic_match, hits, report)
            except Exception:
                logger.exception("Evaluation stopped before a command for %s", item.application_id)
                continue
            result = self._command.execute(**payload)
            if result.success:
                recorded += 1
            else:
                logger.warning("EvaluateCandidateCommand rejected %s: %s", item.application_id, result.message)
        return recorded


def select_pending(events: EventStore) -> list[PendingApplication]:
    """Applications whose stream has no CandidateEvaluated event yet."""
    jobs: dict[str, dict] = {}
    for event in events.load_by_types(("JobCreated",)):
        job_id = str(event.payload.get("job_id") or event.aggregate_id)
        jobs[job_id] = event.payload
    pending: list[PendingApplication] = []
    for event in events.load_by_types(("ApplicationSubmitted",)):
        application_id = str(event.payload.get("application_id") or event.aggregate_id)
        if _already_evaluated(events.load(application_id)):
            continue
        job_id = str(event.payload.get("job_id") or "")
        job = jobs.get(job_id)
        if job is None:
            continue
        pending.append(
            PendingApplication(
                application_id=application_id,
                job_id=job_id,
                title=str(job.get("title") or ""),
                requirements=str(job.get("requirements") or ""),
                full_name=str(event.payload.get("full_name") or ""),
                email=str(event.payload.get("email") or ""),
                cv_text=str(event.payload.get("cv_text") or ""),
            )
        )
    return pending


def _already_evaluated(stream: list[StoredEvent]) -> bool:
    return any(event.event_type == "CandidateEvaluated" for event in stream)


def _evidence(item: PendingApplication, semantic_match: float, hits: list[dict]) -> dict:
    return {
        "job_title": item.title,
        "requirements": item.requirements,
        "full_name": item.full_name,
        "cv_text": item.cv_text,
        "semantic_match": semantic_match,
        "tavily_results": hits,
    }


def _payload(item: PendingApplication, semantic_match: float, hits: list[dict], report: dict) -> dict:
    return {
        "application_id": item.application_id,
        "job_id": item.job_id,
        "email": item.email,
        "status": report["status"],
        "score": report["score"],
        "strengths": report["strengths"],
        "weaknesses": report["weaknesses"],
        "missing_information": report["missing_information"],
        "recommendation": report["recommendation"],
        "semantic_match": semantic_match,
        "sources": [hit["url"] for hit in hits],
    }


def _production_deep_agent(base_url: str, model: str, system_prompt: str):
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        create_deep_agent,
        register_harness_profile,
    )
    from deepagents._models import get_model_identifier, get_model_provider
    from langchain_ollama import ChatOllama

    chat = ChatOllama(model=model, base_url=base_url, format="json", temperature=0)
    profile = HarnessProfile(
        excluded_tools=frozenset(
            {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute", "task"}
        ),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        system_prompt_suffix="Return one JSON object and no other text.",
    )
    provider = get_model_provider(chat)
    identifier = get_model_identifier(chat)
    keys = [f"{provider}:{identifier}"] if provider and identifier else []
    if identifier:
        keys.append(str(identifier))
    for key in keys:
        register_harness_profile(key, profile)
    return create_deep_agent(model=chat, system_prompt=system_prompt)


def _direct_ollama_report(base_url: str, model: str, evidence: dict) -> dict:
    """Ask local Ollama for one JSON report. This does not call any external API."""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(
            {
                "model": model,
                "stream": False,
                "format": _REPORT_SCHEMA,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(evidence)},
                ],
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise EvaluationStepError("Local Ollama did not return a report.") from exc
    content = str((payload.get("message") or {}).get("content") or "")
    return _parse_model_text(content)


_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "score": {"type": "integer"},
        "strengths": {"type": "string"},
        "weaknesses": {"type": "string"},
        "missing_information": {"type": "string"},
        "recommendation": {"type": "string"},
    },
    "required": [
        "status",
        "score",
        "strengths",
        "weaknesses",
        "missing_information",
        "recommendation",
    ],
}


def _message_text(result: dict) -> str:
    structured = result.get("structured_response")
    if hasattr(structured, "model_dump"):
        return json.dumps(structured.model_dump())
    if isinstance(structured, dict):
        return json.dumps(structured)
    messages = result.get("messages") or []
    if not messages:
        raise EvaluationStepError("The model returned nothing.")
    chunks = [_content_text(getattr(message, "content", message)) for message in messages]
    text = "\n".join(chunk for chunk in chunks if chunk.strip())
    if not text.strip():
        raise EvaluationStepError("The model returned nothing.")
    return text


def _content_text(content: object) -> str:
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", part) or ""))
        return "".join(parts)
    return str(content or "")


def _parse_model_text(text: str) -> dict:
    decoder = json.JSONDecoder()
    fallback = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if "status" in value and "score" in value:
            return value
        if fallback is None:
            fallback = value
    if fallback is not None:
        return fallback
    raise EvaluationStepError("The model did not return JSON.")


def _require_report(report: dict) -> dict:
    if not isinstance(report, dict):
        raise EvaluationStepError("The model report was empty.")
    status = str(report.get("status") or "").strip().lower().replace(" ", "_").replace("-", "_")
    score = _score_value(report.get("score"))
    if score is None:
        score = 0
        logger.warning("The model score was missing or invalid. The report will use 0.")
    fields = {
        "strengths": str(report.get("strengths") or "").strip(),
        "weaknesses": str(report.get("weaknesses") or "").strip(),
        "missing_information": str(report.get("missing_information") or "").strip(),
        "recommendation": str(report.get("recommendation") or "").strip(),
    }
    if status not in {"recommended", "not_recommended"} or not all(fields.values()):
        raise EvaluationStepError("The model report was incomplete.")
    return {"status": status, "score": score, **fields}


def _score_value(score: object) -> int | None:
    if isinstance(score, bool) or score is None:
        return None
    if isinstance(score, (int, float)):
        return _clamp_score(float(score))
    text = str(score).strip()
    if not text:
        return None
    try:
        return _clamp_score(float(text))
    except ValueError:
        pass
    match = re.search(r"\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return _clamp_score(float(match.group(0)))


def _clamp_score(number: float) -> int:
    rounded = int(round(number))
    if rounded < 0:
        return 0
    if rounded > 100:
        return 100
    return rounded


def main() -> int:
    from src.config import Config

    logging.basicConfig(level=logging.INFO)
    if not Config.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY is empty. No evaluation will be recorded.")
    events = EventStore(Config.DATABASE_URL)
    events.ensure_schema()
    agent = CandidateEvaluationAgent(
        events=events,
        match=CvMatchQuery(Config.VECTOR_DB_PATH, Config.OLLAMA_BASE_URL, Config.OLLAMA_EMBED_MODEL),
        search=TavilyMcpSearch(Config.TAVILY_API_KEY),
        judge=DeepAgentJudge(Config.OLLAMA_BASE_URL, Config.OLLAMA_CHAT_MODEL),
        command=EvaluateCandidateCommand(events),
    )
    recorded = agent.run()
    print(f"Recorded {recorded} CandidateEvaluated event(s).")
    return 0
