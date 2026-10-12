from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, render_template

from src.commands.auth_commands import LoginCommand, LogoutCommand
from src.config import Config
from src.controllers.auth import auth_bp
from src.controllers.candidate import candidate_bp
from src.controllers.decorators import load_session_user
from src.controllers.home import home_bp
from src.controllers.hr import hr_bp
from src.identity import AuthTicketStore, directory_from_config
from src.queries.auth_queries import CurrentSessionQuery
from src.queries.portal_queries import CandidatePortalQuery, HrPortalQuery

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
    tickets = AuthTicketStore()

    app.extensions["commands"] = {
        "login": LoginCommand(directory, tickets),
        "logout": LogoutCommand(tickets),
    }
    app.extensions["queries"] = {
        "current_session": CurrentSessionQuery(tickets),
        "hr_portal": HrPortalQuery(),
        "candidate_portal": CandidatePortalQuery(),
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
