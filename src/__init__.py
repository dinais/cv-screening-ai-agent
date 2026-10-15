from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, render_template

from src.commands.application_commands import SubmitApplicationCommand
from src.commands.auth_commands import LoginCommand, LogoutCommand
from src.commands.decision_commands import DecideCandidateCommand
from src.commands.job_commands import CloseJobCommand, CreateJobCommand
from src.config import Config
from src.controllers.auth import auth_bp
from src.controllers.candidate import candidate_bp
from src.controllers.decorators import load_session_user
from src.controllers.home import home_bp
from src.controllers.hr import hr_bp
from src.identity import directory_from_config
from src.persistence.event_store import EventStore
from src.projections.cv_embeddings import CvEmbeddingProjector
from src.providers import provider_from_config
from src.queries.auth_queries import CurrentSessionQuery
from src.queries.portal_queries import (
    ApplicationDetailQuery,
    CandidatePortalQuery,
    HrPortalQuery,
    JobDetailQuery,
)

load_dotenv()

PACKAGE_DIR = Path(__file__).resolve().parent


def create_app(config_class=Config) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PACKAGE_DIR / "templates"),
        static_folder=str(PACKAGE_DIR / "static"),
    )
    app.config.from_object(config_class)

    directory = directory_from_config(config_class)
    event_store = EventStore(getattr(config_class, "DATABASE_URL", ""))
    event_store.ensure_schema()
    if event_store.local_fallback:
        app.logger.warning(
            "DATABASE_URL is empty. Event Store is using local SQLite at %s. "
            "Set DATABASE_URL to the Somee ODBC connection string for the course database.",
            event_store.sqlite_path,
        )

    app.extensions["event_store"] = event_store
    app.extensions["cv_embeddings"] = CvEmbeddingProjector(
        event_store,
        getattr(config_class, "VECTOR_DB_PATH", "./data/vector_store"),
        provider_from_config(config_class),
    )
    app.extensions["commands"] = {
        "login": LoginCommand(directory, event_store),
        "logout": LogoutCommand(event_store),
        "create_job": CreateJobCommand(event_store),
        "close_job": CloseJobCommand(event_store),
        "submit_application": SubmitApplicationCommand(event_store),
        "decide_candidate": DecideCandidateCommand(event_store),
    }
    app.extensions["queries"] = {
        "current_session": CurrentSessionQuery(event_store),
        "hr_portal": HrPortalQuery(event_store),
        "job_detail": JobDetailQuery(event_store),
        "application_detail": ApplicationDetailQuery(event_store),
        "candidate_portal": CandidatePortalQuery(event_store),
    }

    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(hr_bp)
    app.register_blueprint(candidate_bp)

    @app.before_request
    def _bind_user():
        load_session_user()

    @app.context_processor
    def _inject_user():
        return {"current_user": getattr(g, "current_user", None)}

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403

    return app
