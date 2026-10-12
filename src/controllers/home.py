from flask import Blueprint, g, redirect, render_template, url_for

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    if g.current_user is not None:
        if g.current_user.role == "hr":
            return redirect(url_for("hr.portal"))
        if g.current_user.role == "candidate":
            return redirect(url_for("candidate.apply"))
    return render_template("home.html")
