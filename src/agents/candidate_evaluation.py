"""Independent candidate evaluation process.

Run it with `python -m src.agents`. Flask does not import or start this process.
The process reads events, gets the RAG match and Tavily results from the
screening-mcp server, asks the configured LLMProvider for a report, and records
the result only by issuing EvaluateCandidateCommand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from src.commands.evaluation_commands import EvaluateCandidateCommand
from src.persistence.event_store import EventStore, StoredEvent
from src.providers.base import LLMProvider
from src.providers.report import require_report

logger = logging.getLogger(__name__)


class SemanticMatch(Protocol):
    def match(self, application_id: str, requirements: str) -> float: ...


class WebResearch(Protocol):
    def research(self, title: str, requirements: str, cv_text: str) -> list[dict]: ...


@dataclass(frozen=True)
class PendingApplication:
    application_id: str
    job_id: str
    title: str
    requirements: str
    full_name: str
    email: str
    cv_text: str


class CandidateEvaluationAgent:
    def __init__(
        self,
        events: EventStore,
        match: SemanticMatch,
        search: WebResearch,
        provider: LLMProvider,
        command: EvaluateCandidateCommand,
    ) -> None:
        self._events = events
        self._match = match
        self._search = search
        self._provider = provider
        self._command = command

    def run(self) -> int:
        recorded = 0
        for item in select_pending(self._events):
            try:
                semantic_match = self._match.match(item.application_id, item.requirements)
                hits = self._search.research(item.title, item.requirements, item.cv_text)
                report = require_report(self._provider.evaluate(_evidence(item, semantic_match, hits)))
                payload = _payload(item, semantic_match, hits, report, self._provider.name)
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


def _payload(
    item: PendingApplication,
    semantic_match: float,
    hits: list[dict],
    report: dict,
    provider: str,
) -> dict:
    return {
        "application_id": item.application_id,
        "job_id": item.job_id,
        "email": item.email,
        "status": report["status"],
        "score": report["score"],
        "skill_breakdown": report["skill_breakdown"],
        "strengths": report["strengths"],
        "weaknesses": report["weaknesses"],
        "missing_information": report["missing_information"],
        "recommendation": report["recommendation"],
        "semantic_match": semantic_match,
        "sources": [hit["url"] for hit in hits],
        "provider": provider,
    }


def main() -> int:
    from src.config import Config
    from src.integrations.screening_mcp import ScreeningMcpClient
    from src.providers import provider_from_config

    logging.basicConfig(level=logging.INFO)
    provider = provider_from_config(Config)
    logger.info("Evaluating with the %s provider.", provider.name)
    events = EventStore(Config.DATABASE_URL)
    events.ensure_schema()
    with ScreeningMcpClient() as tools:
        agent = CandidateEvaluationAgent(
            events=events,
            match=tools,
            search=tools,
            provider=provider,
            command=EvaluateCandidateCommand(events),
        )
        recorded = agent.run()
    print(f"Recorded {recorded} CandidateEvaluated event(s).")
    return 0
