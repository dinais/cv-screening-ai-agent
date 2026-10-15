from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from src.controllers.decorators import hr_required

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


@hr_bp.route("/")
@hr_required
def portal():
    query = current_app.extensions["queries"]["hr_portal"]
    view = query.execute(request.args.get("q", ""))
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


@hr_bp.route("/jobs/<job_id>/close", methods=["POST"])
@hr_required
def close_job(job_id):
    command = current_app.extensions["commands"]["close_job"]
    result = command.execute(job_id=job_id, closed_by=g.current_user.email)
    flash(result.message if not result.success else "Job closed.", "error" if not result.success else "info")
    return redirect(url_for("hr.portal"))


@hr_bp.route("/jobs/<job_id>")
@hr_required
def job_detail(job_id):
    query = current_app.extensions["queries"]["job_detail"]
    job = query.execute(job_id)
    if job is None:
        abort(404)
    return render_template("job_detail.html", job=job)


@hr_bp.route("/applications/<application_id>")
@hr_required
def application_detail(application_id):
    query = current_app.extensions["queries"]["application_detail"]
    application = query.execute(application_id)
    if application is None:
        abort(404)
    return render_template("application_detail.html", application=application)


@hr_bp.route("/applications/<application_id>/decision", methods=["POST"])
@hr_required
def decide_application(application_id):
    command = current_app.extensions["commands"]["decide_candidate"]
    result = command.execute(
        application_id=application_id,
        decision=request.form.get("decision", ""),
        decided_by=g.current_user.email,
    )
    flash(result.message if not result.success else "Decision recorded.", "error" if not result.success else "info")
    if current_app.extensions["queries"]["application_detail"].execute(application_id) is None:
        return redirect(url_for("hr.portal"))
    return redirect(url_for("hr.application_detail", application_id=application_id))
