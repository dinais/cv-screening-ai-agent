from flask import Blueprint, current_app, render_template

from src.controllers.decorators import hr_required

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


@hr_bp.route("/")
@hr_required
def portal():
    query = current_app.extensions["queries"]["hr_portal"]
    view = query.execute()
    return render_template("hr_portal.html", portal=view)
