from flask import Blueprint, current_app, render_template

from src.controllers.decorators import candidate_required

candidate_bp = Blueprint("candidate", __name__, url_prefix="/apply")


@candidate_bp.route("/")
@candidate_required
def apply():
    query = current_app.extensions["queries"]["candidate_portal"]
    view = query.execute()
    return render_template("candidate_form.html", portal=view)
