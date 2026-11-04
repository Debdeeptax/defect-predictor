from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.forms import LoginForm, RegisterForm
from app.services import user_service
from app.services.audit_service import audit

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str:
    if target and not urlparse(target).netloc and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = user_service.authenticate(form.email.data, form.password.data)
        if user is None:
            audit("login_failed", f"email={form.email.data}")
            flash("Invalid email or password.", "error")
        elif not user.active:
            audit("login_blocked", f"email={user.email}", user_id=user.id)
            flash("This account has been deactivated. Contact an administrator.", "error")
        else:
            login_user(user, remember=form.remember.data)
            user_service.mark_login(user)
            audit("login", f"email={user.email}")
            flash(f"Welcome back, {user.name}!", "success")
            return redirect(_safe_next(request.args.get("next")))
    elif request.method == "POST":
        flash("Please enter a valid email and password.", "error")
    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            user = user_service.register(form.email.data, form.name.data, form.password.data)
        except user_service.UserError as exc:
            flash(exc.user_message, "error")
        else:
            audit("register", f"email={user.email}", user_id=user.id)
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("auth.login"))
    elif request.method == "POST":
        for errors in form.errors.values():
            for e in errors:
                flash(e, "error")
    return render_template("auth/register.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    audit("logout", f"email={current_user.email}")
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
