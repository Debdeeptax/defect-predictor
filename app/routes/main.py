from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import Report, ReportStatus, User
from app.services.analysis_service import get_engine

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return redirect(url_for("main.dashboard" if current_user.is_authenticated else "auth.login"))


@bp.get("/dashboard")
@login_required
def dashboard():
    q = db.select(Report)
    if not current_user.can_view_all_reports:
        q = q.where(Report.user_id == current_user.id)
    recent = db.session.scalars(q.order_by(Report.id.desc()).limit(5)).all()

    done = q.where(Report.status == ReportStatus.DONE).subquery()
    totals = db.session.execute(db.select(
        func.count(done.c.id), func.coalesce(func.sum(done.c.n_files), 0),
        func.coalesce(func.sum(done.c.n_high), 0), func.coalesce(func.sum(done.c.n_medium), 0),
        func.coalesce(func.sum(done.c.n_low), 0))).one()
    stats = dict(zip(("reports", "files", "high", "medium", "low"), totals))
    stats["users"] = db.session.scalar(db.select(func.count(User.id))) if current_user.is_admin else None

    try:
        models = get_engine().model_info()
    except Exception:
        models = {"function": None, "class": None}
    return render_template("dashboard.html", recent=recent, stats=stats, models=models)
