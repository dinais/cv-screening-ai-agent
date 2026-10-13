from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from src.controllers.decorators import hr_required

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


@hr_bp.route("/")
@hr_required
def portal():
    query = current_app.extensions["queries"]["hr_portal"]
    view = query.execute()
    return render_template("hr_portal.html", portal=view)


@hr_bp.route("/jobs", methods=["POST"])
@hr_required
def create_job():
    command = current_app.extensions["commands"]["create_job"]
    result = command.execute(
        title=request.form.get("title", ""),
        requirements=request.form.get("requirements", ""),
        created_by=g.current_user.email,
    )
    if not result.success:
        flash(result.message, "error")
        return redirect(url_for("hr.portal"))
    flash("Job created.", "info")
    return redirect(url_for("hr.job_detail", job_id=result.reference_id))


@hr_bp.route("/jobs/<job_id>")
@hr_required
def job_detail(job_id):
    query = current_app.extensions["queries"]["job_detail"]
    job = query.execute(job_id)
    if job is None:
        abort(404)
    return render_template("job_detail.html", job=job)
