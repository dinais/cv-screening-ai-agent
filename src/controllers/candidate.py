from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from src.controllers.decorators import candidate_required
from src.cv_pdf import PdfError, extract_pdf_text, save_pdf

candidate_bp = Blueprint("candidate", __name__, url_prefix="/apply")


@candidate_bp.route("/")
@candidate_required
def apply():
    query = current_app.extensions["queries"]["candidate_portal"]
    view = query.execute(g.current_user.email)
    return render_template("candidate_form.html", portal=view)


@candidate_bp.route("/<job_id>", methods=["GET", "POST"])
@candidate_required
def apply_to_job(job_id):
    portal = current_app.extensions["queries"]["candidate_portal"].execute(g.current_user.email)
    job = next((item for item in portal.open_jobs if item.job_id == job_id), None)
    if job is None:
        abort(404)

    if request.method == "POST":
        try:
            cv_text, pdf_bytes = extract_pdf_text(request.files.get("cv"))
        except PdfError as exc:
            flash(str(exc), "error")
            return render_template("apply_job.html", job=job)
        command = current_app.extensions["commands"]["submit_application"]
        result = command.execute(
            job_id=job_id,
            full_name=request.form.get("full_name", ""),
            email=g.current_user.email,
            cv_text=cv_text,
        )
        if result.success:
            save_pdf(result.reference_id, pdf_bytes)
            current_app.extensions["cv_embeddings"].project_application(result.reference_id)
            flash("Application submitted.", "info")
            return redirect(url_for("candidate.apply"))
        flash(result.message, "error")

    if job.applied and request.method == "GET":
        flash("You have already applied to this job.", "info")
        return redirect(url_for("candidate.apply"))

    return render_template("apply_job.html", job=job)
