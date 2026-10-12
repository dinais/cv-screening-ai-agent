from __future__ import annotations

from functools import wraps

from flask import abort, current_app, g, redirect, session, url_for

from src.identity import ROLE_CANDIDATE, ROLE_HR
from src.queries.auth_queries import CurrentSessionQuery


def load_session_user():
    query: CurrentSessionQuery = current_app.extensions["queries"]["current_session"]
    g.current_user = query.execute(session.get("ticket_id"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.current_user is None:
                return redirect(url_for("auth.login"))
            if g.current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


hr_required = role_required(ROLE_HR)
candidate_required = role_required(ROLE_CANDIDATE)
