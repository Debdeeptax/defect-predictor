from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.exceptions import SDPError
from app.forms import UploadForm
from app.metrics.languages import SUPPORTED_LANGUAGES
from app.ml.ml_model import ModelNotAvailableError
from app.models import Role
from app.routes.decorators import roles_required
from app.services import analysis_service

bp = Blueprint("upload", __name__)


@bp.route("/upload", methods=["GET", "POST"])
@roles_required(Role.DEVELOPER, Role.ADMIN)
def upload():
    form = UploadForm()
    cfg = current_app.config_obj
    if request.method == "POST":
        if not form.validate():
            for errors in form.errors.values():
                for e in errors:
                    flash(e, "error")
        else:
            try:
                if form.source.data == "git":
                    if not form.git_url.data:
                        raise SDPError("Please enter a Git repository URL.")
                    report = analysis_service.analyse_git(current_user, form.git_url.data,
                                                          form.title.data)
                else:
                    f = form.file.data
                    if f is None or not f.filename:
                        raise SDPError("Please choose a file to upload.")
                    report = analysis_service.analyse_upload(current_user, f.filename, f.stream,
                                                             form.title.data)
            except ModelNotAvailableError as exc:
                flash(f"Prediction model unavailable: {exc}", "error")
            except SDPError as exc:
                flash(exc.user_message, "error")
            else:
                flash(f"Analysis complete: {report.n_files} file(s) analysed.", "success")
                return redirect(url_for("reports.detail", report_id=report.id))
    return render_template("upload.html", form=form, languages=SUPPORTED_LANGUAGES,
                           max_mb=cfg.MAX_UPLOAD_MB, git_hosts=cfg.ALLOWED_GIT_HOSTS)
