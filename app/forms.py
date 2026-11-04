from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import BooleanField, EmailField, PasswordField, RadioField, SelectField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, URL

from app.models import Role


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")


class RegisterForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = EmailField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), EqualTo("password", "Passwords must match.")])


class UploadForm(FlaskForm):
    source = RadioField("Source", choices=[("file", "Upload file / ZIP"), ("git", "Git repository URL")],
                        default="file")
    title = StringField("Report title (optional)", validators=[Optional(), Length(max=200)])
    file = FileField("Source file or .zip")
    git_url = StringField("Git URL", validators=[Optional(), URL(require_tld=True)])


class RoleForm(FlaskForm):
    role = SelectField("Role", choices=[(r, Role.LABELS[r]) for r in Role.ALL])


class EmptyForm(FlaskForm):
    """CSRF-only form for POST buttons."""


class RetrainForm(FlaskForm):
    level = SelectField("Model level", choices=[("function", "Function level (NASA MDP)"),
                                                ("class", "Class level (PROMISE CK)")])
    preset = SelectField("Cross-validation", choices=[("quick", "Quick (3-fold × 1, ~1–3 min)"),
                                                      ("standard", "Standard (5-fold × 5, ~5–15 min)")])
    data = FileField("Training CSV (optional — default: built-in dataset)")
    activate = BooleanField("Activate the new model when training finishes", default=True)


class CompareForm(FlaskForm):
    class Meta:
        csrf = False  # GET form

    a = SelectField("Baseline report (A)", coerce=int)
    b = SelectField("Compared report (B)", coerce=int)
