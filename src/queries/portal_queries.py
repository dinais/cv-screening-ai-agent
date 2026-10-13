from __future__ import annotations

from dataclasses import dataclass

from src.persistence.event_store import EventStore, StoredEvent
from src.queries.base import QueryHandler

_PORTAL_EVENTS = ("JobCreated", "ApplicationSubmitted")


@dataclass(frozen=True)
class ApplicantView:
    full_name: str
    email: str
    cv_text: str


@dataclass(frozen=True)
class JobView:
    job_id: str
    title: str
    requirements: str
    status: str
    applicants: int
    applicant_list: tuple[ApplicantView, ...] = ()


@dataclass(frozen=True)
class CandidateJobView:
    job_id: str
    title: str
    requirements: str
    applied: bool


@dataclass(frozen=True)
class HrPortalView:
    open_jobs: int
    applicants: int
    jobs: tuple[JobView, ...]


@dataclass(frozen=True)
class CandidatePortalView:
    open_jobs: tuple[CandidateJobView, ...]


def project_jobs(events: list[StoredEvent]) -> tuple[JobView, ...]:
    """Replay events into the current job list. This function never writes."""
    jobs: dict[str, JobView] = {}
    for event in events:
        if event.event_type == "JobCreated":
            job_id = str(event.payload.get("job_id") or event.aggregate_id)
            jobs[job_id] = JobView(
                job_id=job_id,
                title=str(event.payload.get("title") or ""),
                requirements=str(event.payload.get("requirements") or ""),
                status="Open",
                applicants=0,
                applicant_list=(),
            )
        elif event.event_type == "ApplicationSubmitted":
            job_id = str(event.payload.get("job_id") or "")
            current = jobs.get(job_id)
            if current is None:
                continue
            applicant = ApplicantView(
                full_name=str(event.payload.get("full_name") or ""),
                email=str(event.payload.get("email") or ""),
                cv_text=str(event.payload.get("cv_text") or ""),
            )
            jobs[job_id] = JobView(
                job_id=current.job_id,
                title=current.title,
                requirements=current.requirements,
                status=current.status,
                applicants=current.applicants + 1,
                applicant_list=current.applicant_list + (applicant,),
            )
    return tuple(jobs.values())


class HrPortalQuery(QueryHandler):
    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self) -> HrPortalView:
        jobs = project_jobs(self._events.load_by_types(_PORTAL_EVENTS))
        open_jobs = tuple(job for job in jobs if job.status == "Open")
        return HrPortalView(
            open_jobs=len(open_jobs),
            applicants=sum(job.applicants for job in open_jobs),
            jobs=open_jobs,
        )


class JobDetailQuery(QueryHandler):
    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self, job_id: str) -> JobView | None:
        for job in project_jobs(self._events.load_by_types(_PORTAL_EVENTS)):
            if job.job_id == job_id:
                return job
        return None


class CandidatePortalQuery(QueryHandler):
    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self, email: str) -> CandidatePortalView:
        needle = (email or "").strip().lower()
        jobs = project_jobs(self._events.load_by_types(_PORTAL_EVENTS))
        open_jobs = tuple(
            CandidateJobView(
                job_id=job.job_id,
                title=job.title,
                requirements=job.requirements,
                applied=any(person.email.strip().lower() == needle for person in job.applicant_list),
            )
            for job in jobs
            if job.status == "Open"
        )
        return CandidatePortalView(open_jobs=open_jobs)
