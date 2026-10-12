from __future__ import annotations

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from src.controllers.decorators import login_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user is not None:
        return redirect(_home_for_role(g.current_user.role))

    if request.method == "POST":
        command = current_app.extensions["commands"]["login"]
        result = command.execute(
            email=request.form.get("email", ""),
            password=request.form.get("password", ""),
        )
        if not result.success:
            flash(result.message, "error")
            return render_template("login.html"), 401

        session["ticket_id"] = result.ticket_id
        query = current_app.extensions["queries"]["current_session"]
        user = query.execute(result.ticket_id)
        role = user.role if user else None
        return redirect(_home_for_role(role))

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    command = current_app.extensions["commands"]["logout"]
    command.execute(session.get("ticket_id"))
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


def _home_for_role(role: str | None) -> str:
    if role == "hr":
        return url_for("hr.portal")
    if role == "candidate":
        return url_for("candidate.apply")
    return url_for("home.index")
