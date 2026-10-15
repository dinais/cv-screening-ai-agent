from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for

from src.agents.launch import evaluation_running, start_evaluation
from src.controllers.decorators import hr_required
from src.cv_pdf import PdfError, cv_pdf_exists, cv_pdf_path

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


@hr_bp.route("/")
@hr_required
def portal():
    query = current_app.extensions["queries"]["hr_portal"]
    view = query.execute(request.args.get("q", ""))
    return render_template("hr_portal.html", portal=view, evaluation_running=evaluation_running)


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
        return redirect(url_for("hr.portal", create=1))
    flash("Job created.", "info")
    return redirect(url_for("hr.job_detail", job_id=result.reference_id))


@hr_bp.route("/evaluate", methods=["POST"])
@hr_required
def evaluate_pending():
    portal = current_app.extensions["queries"]["hr_portal"].execute()
    if not any(_job_needs_evaluation(job) for job in portal.jobs):
        flash("Nothing is waiting for an assessment.", "error")
        return redirect(url_for("hr.portal"))
    started, message = start_evaluation()
    flash(message, "info" if started else "error")
    return redirect(url_for("hr.portal"))


@hr_bp.route("/jobs/<job_id>/evaluate", methods=["POST"])
@hr_required
def evaluate_job(job_id):
    job = current_app.extensions["queries"]["job_detail"].execute(job_id)
    if job is None:
        abort(404)
    if not _job_needs_evaluation(job):
        flash("This job has no application waiting for an assessment.", "error")
        return redirect(url_for("hr.job_detail", job_id=job_id))
    started, message = start_evaluation(job_id)
    flash(message, "info" if started else "error")
    return redirect(url_for("hr.job_detail", job_id=job_id))


def _job_needs_evaluation(job) -> bool:
    return job.status == "Open" and any(person.assessment is None for person in job.applicant_list)


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
    return render_template("job_detail.html", job=job, evaluation_running=evaluation_running)


@hr_bp.route("/applications/<application_id>")
@hr_required
def application_detail(application_id):
    query = current_app.extensions["queries"]["application_detail"]
    application = query.execute(application_id)
    if application is None:
        abort(404)
    return render_template("application_detail.html", application=application)


@hr_bp.route("/applications/<application_id>/cv")
@hr_required
def application_cv(application_id):
    if not cv_pdf_exists(application_id):
        abort(404)
    try:
        path = cv_pdf_path(application_id)
    except PdfError:
        abort(404)
    return send_file(path, mimetype="application/pdf", as_attachment=False, download_name="cv.pdf")


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
    application = current_app.extensions["queries"]["application_detail"].execute(application_id)
    if application is None:
        return redirect(url_for("hr.portal"))
    return_to = request.form.get("return_to", "")
    search = (request.form.get("q") or "").strip()
    if return_to == "portal":
        target = {"job": application.job_id, "application": application_id}
        if search:
            target["q"] = search
        return redirect(url_for("hr.portal", **target))
    if return_to == "job":
        return redirect(url_for("hr.job_detail", job_id=application.job_id, application=application_id))
    return redirect(url_for("hr.application_detail", application_id=application_id))
