from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.exceptions import SDPError
from app.extensions import db
from app.forms import EmptyForm, RetrainForm, RoleForm
from app.ml.features import LEVELS
from app.ml.ml_model import ModelNotAvailableError
from app.models import AuditEvent, Role, TrainingJob, User
from app.routes.decorators import roles_required
from app.services import training_service, user_service
from app.services.audit_service import audit, tail_log

bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_only = roles_required(Role.ADMIN)


@bp.get("")
@admin_only
def index():
    return redirect(url_for("admin.models"))


# ---------------------------------------------------------------------- users
@bp.get("/users")
@admin_only
def users():
    rows = db.session.scalars(db.select(User).order_by(User.id)).all()
    return render_template("admin/users.html", users=rows, role_form=RoleForm(), form=EmptyForm())


def _user_or_404(user_id: int) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        from flask import abort
        abort(404)
    return user


@bp.post("/users/<int:user_id>/role")
@admin_only
def change_role(user_id: int):
    user = _user_or_404(user_id)
    form = RoleForm()
    if form.validate_on_submit():
        try:
            old = user.role
            user_service.set_role(current_user, user, form.role.data)
            audit("role_change", f"user={user.email} {old}->{user.role}")
            flash(f"{user.email} is now {user.role_label}.", "success")
        except SDPError as exc:
            flash(exc.user_message, "error")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/toggle")
@admin_only
def toggle_user(user_id: int):
    user = _user_or_404(user_id)
    if EmptyForm().validate_on_submit():
        try:
            user_service.set_active(current_user, user, not user.active)
            audit("user_toggle", f"user={user.email} active={user.active}")
            flash(f"{user.email} {'activated' if user.active else 'deactivated'}.", "success")
        except SDPError as exc:
            flash(exc.user_message, "error")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------- models
@bp.get("/models")
@admin_only
def models():
    reg = training_service.registry()
    levels = {lvl: {"active": reg.active_file(lvl), "versions": reg.list_versions(lvl)}
              for lvl in LEVELS}
    jobs = db.session.scalars(db.select(TrainingJob).order_by(TrainingJob.id.desc()).limit(10)).all()
    return render_template("admin/models.html", levels=levels, jobs=jobs, form=RetrainForm(),
                           action_form=EmptyForm(), running=training_service.active_job())


@bp.post("/models/activate")
@admin_only
def activate_model():
    if EmptyForm().validate_on_submit():
        level, file = request.form.get("level", ""), request.form.get("file", "")
        try:
            training_service.activate_model(current_user, level, file)
            flash(f"Activated {level}-level model {file}.", "success")
        except (SDPError, ModelNotAvailableError) as exc:
            flash(getattr(exc, "user_message", str(exc)), "error")
    return redirect(url_for("admin.models"))


@bp.post("/models/retrain")
@admin_only
def retrain():
    form = RetrainForm()
    if not form.validate_on_submit():
        flash("Invalid training request.", "error")
        return redirect(url_for("admin.models"))
    try:
        job = training_service.start_training(current_user, form.level.data, form.preset.data,
                                              form.activate.data, form.data.data)
    except SDPError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("admin.models"))
    flash(f"Training job #{job.id} started.", "success")
    return redirect(url_for("admin.job", job_id=job.id))


@bp.get("/models/jobs/<int:job_id>")
@admin_only
def job(job_id: int):
    j = db.session.get(TrainingJob, job_id)
    if j is None:
        from flask import abort
        abort(404)
    return render_template("admin/job.html", job=j)


# ---------------------------------------------------------------------- logs
@bp.get("/logs")
@admin_only
def logs():
    action = request.args.get("action", "")
    q = db.select(AuditEvent).order_by(AuditEvent.id.desc())
    if action:
        q = q.where(AuditEvent.action == action)
    events = db.session.scalars(q.limit(200)).all()
    actions = db.session.scalars(db.select(AuditEvent.action).distinct().order_by(AuditEvent.action)).all()
    lines = tail_log(Path(current_app.config_obj.LOG_DIR) / "app.log", 200)
    return render_template("admin/logs.html", events=events, actions=actions, action=action,
                           log_lines=lines)
