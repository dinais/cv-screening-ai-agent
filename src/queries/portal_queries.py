from __future__ import annotations

from dataclasses import dataclass

from src.queries.base import QueryHandler


@dataclass(frozen=True)
class HrPortalView:
    open_jobs: int
    applicants: int
    jobs: tuple[dict, ...]


@dataclass(frozen=True)
class CandidatePortalView:
    open_jobs: tuple[dict, ...]


class HrPortalQuery(QueryHandler):
    def execute(self) -> HrPortalView:
        # Feature 5 will reconstruct this from the Event Store.
        return HrPortalView(open_jobs=0, applicants=0, jobs=())


class CandidatePortalQuery(QueryHandler):
    def execute(self) -> CandidatePortalView:
        # Feature 4 will list jobs reconstructed from JobCreated events.
        return CandidatePortalView(open_jobs=())
