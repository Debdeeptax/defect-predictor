import re

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import CompareForm
from app.models import Report, ReportStatus, Role
from app.routes.decorators import roles_required
from app.services.audit_service import audit
from app.services.report_service import ReportService

bp = Blueprint("reports", __name__, url_prefix="/reports")
PER_PAGE = 20


def _visible_query():
    q = db.select(Report)
    if not current_user.can_view_all_reports:
        q = q.where(Report.user_id == current_user.id)
    return q


def _get_visible(report_id: int) -> Report:
    report = db.session.get(Report, report_id)
    if report is None:
        abort(404)
    if not report.visible_to(current_user):
        abort(403)
    return report


def _filename(report: Report, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", report.title).strip("-")[:40] or "report"
    return f"report-{report.id}-{slug}.{ext}"


@bp.get("")
@login_required
def list_reports():
    page = max(1, request.args.get("page", 1, type=int))
    risk = request.args.get("risk", "")
    q = _visible_query()
    if risk == "high":
        q = q.where(Report.n_high > 0)
    elif risk == "medium":
        q = q.where(Report.n_medium > 0)
    pagination = db.paginate(q.order_by(Report.id.desc()), page=page, per_page=PER_PAGE,
                             error_out=False)
    return render_template("reports/list.html", pagination=pagination, risk=risk)


@bp.get("/<int:report_id>")
@login_required
def detail(report_id: int):
    report = _get_visible(report_id)
    return render_template("reports/detail.html", report=report, payload=report.payload)


def _require_done(report: Report) -> None:
    if report.status != ReportStatus.DONE:
        flash("This report has no results to export.", "error")
        abort(redirect(url_for("reports.detail", report_id=report.id)))


@bp.get("/<int:report_id>/export.csv")
@login_required
def export_csv(report_id: int):
    report = _get_visible(report_id)
    _require_done(report)
    granularity = "unit" if request.args.get("level") == "unit" else "file"
    audit("export_csv", f"report={report.id} granularity={granularity}")
    name = _filename(report, "csv" if granularity == "file" else "units.csv")
    return Response(ReportService.to_csv(report.payload, granularity), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.get("/<int:report_id>/export.pdf")
@login_required
def export_pdf(report_id: int):
    report = _get_visible(report_id)
    _require_done(report)
    audit("export_pdf", f"report={report.id}")
    pdf = ReportService.to_pdf(report.payload, title=f"Defect Prediction Report — {report.title}",
                               source=f"{report.submission.source_type}: {report.submission.source_name}",
                               author=report.user.email, report_id=report.id)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={_filename(report, 'pdf')}"})


@bp.get("/compare")
@roles_required(Role.QA, Role.ADMIN)
def compare():
    done = db.session.scalars(_visible_query().where(Report.status == ReportStatus.DONE)
                              .order_by(Report.id.desc()).limit(200)).all()
    form = CompareForm(request.args)
    choices = [(r.id, f"#{r.id} — {r.title} ({r.created_at:%Y-%m-%d %H:%M}, {r.user.email})")
               for r in done]
    form.a.choices = form.b.choices = choices
    result = a = b = None
    if "a" in request.args and "b" in request.args:
        a = db.session.get(Report, request.args.get("a", type=int))
        b = db.session.get(Report, request.args.get("b", type=int))
        if not a or not b or not a.is_done or not b.is_done:
            flash("Please choose two completed reports.", "error")
        elif a.id == b.id:
            flash("Please choose two different reports.", "error")
        else:
            result = ReportService.compare(a.payload, b.payload)
            audit("compare", f"a={a.id} b={b.id}")
    return render_template("reports/compare.html", form=form, result=result, a=a, b=b,
                           has_choices=len(choices) >= 2)
