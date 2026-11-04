"""Flask application factory."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

import click
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import RequestEntityTooLarge

from config import Config


def create_app(config: type | object = Config, **overrides) -> Flask:
    cfg = config() if isinstance(config, type) else config
    for key, value in overrides.items():
        setattr(cfg, key, value)

    app = Flask(__name__, instance_path=str(Path(cfg.INSTANCE_DIR).resolve()))
    app.config.from_object(cfg)
    app.config_obj = cfg  # typed access for services (paths, thresholds, limits)

    for d in (cfg.INSTANCE_DIR, cfg.UPLOAD_DIR, cfg.WORKSPACE_DIR, cfg.LOG_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)
    _configure_logging(app, cfg)

    from app.extensions import csrf, db, login_manager
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    from app.routes.admin import bp as admin_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.health import bp as health_bp
    from app.routes.main import bp as main_bp
    from app.routes.reports import bp as reports_bp
    from app.routes.upload import bp as upload_bp
    for bp in (health_bp, auth_bp, main_bp, upload_bp, reports_bp, admin_bp):
        app.register_blueprint(bp)

    _register_error_handlers(app)
    _register_template_helpers(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()
    return app


# ---------------------------------------------------------------------- logging
def _configure_logging(app: Flask, cfg) -> None:
    level = getattr(logging, str(cfg.LOG_LEVEL).upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    log_file = Path(cfg.LOG_DIR) / "app.log"
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_file.resolve()
               for h in root.handlers):
        fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    root.setLevel(level)
    for noisy in ("matplotlib", "numba", "PIL", "urllib3", "shap"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    app.logger.setLevel(level)


# ---------------------------------------------------------------------- errors
def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/error.html", code=403, title="Access denied",
                               message="Your role does not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="The page you requested does not exist."), 404

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_e):
        flash(f"File is larger than the {app.config['MAX_UPLOAD_MB']} MB limit.", "error")
        return redirect(request.referrer or url_for("upload.upload"))

    @app.errorhandler(CSRFError)
    def csrf_error(_e):
        flash("Your session expired. Please try again.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    @app.errorhandler(500)
    def server_error(_e):
        app.logger.exception("Unhandled error")
        return render_template("errors/error.html", code=500, title="Server error",
                               message="Something went wrong. The error has been logged."), 500


# ---------------------------------------------------------------------- templates
def _register_template_helpers(app: Flask) -> None:
    from app.models import Role

    @app.template_filter("testid")
    def testid(value: str) -> str:
        """Stable kebab-case token for data-testid / id attributes (e.g. file paths)."""
        return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "x"

    @app.template_filter("pct")
    def pct(value) -> str:
        return "–" if value is None else f"{100 * float(value):.1f}%"

    @app.template_filter("num")
    def num(value) -> str:
        """Metric values: integers without '.0', others to 2 decimals."""
        try:
            f = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{int(f)}" if f.is_integer() else f"{f:.2f}"

    @app.template_filter("dt")
    def dt(value) -> str:
        return value.strftime("%Y-%m-%d %H:%M") + " UTC" if value else "–"

    @app.context_processor
    def inject_globals():
        return {"Role": Role, "RISK_CLASSES": {"High": "danger", "Medium": "warning", "Low": "success"}}


# ---------------------------------------------------------------------- CLI
def _register_cli(app: Flask) -> None:
    from app.extensions import db

    @app.cli.command("init-db")
    def init_db():
        """Create tables (idempotent)."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("reset-db")
    @click.option("--seed/--no-seed", default=True, help="re-create seed users and sample report")
    def reset_db(seed: bool):
        """Drop and re-create all tables, then (by default) seed."""
        db.drop_all()
        db.create_all()
        click.echo("Database reset.")
        if seed:
            from app.seed import seed_all
            for line in seed_all():
                click.echo(line)

    @app.cli.command("seed")
    def seed():
        """Create one user per role (+ a sample report) if missing."""
        from app.seed import seed_all
        for line in seed_all():
            click.echo(line)
