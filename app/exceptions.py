"""Domain exceptions. Routes map these to user-facing flash messages."""


class SDPError(Exception):
    """Base class; `user_message` is safe to show in the UI."""

    user_message = "Something went wrong while processing your request."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.user_message)
        if message:
            self.user_message = message


class InvalidUploadError(SDPError):
    user_message = "The uploaded file is invalid."


class EmptyRepositoryError(SDPError):
    user_message = "No source files were found in the submission."


class UnsupportedLanguageError(SDPError):
    user_message = "None of the submitted files are in a supported language."


class GitCloneError(SDPError):
    user_message = "The Git repository could not be cloned."


# Re-exported so callers can catch every domain error from one module.
from app.ml.ml_model import ModelNotAvailableError  # noqa: E402,F401
from app.ml.data_preprocessor import DatasetSchemaError  # noqa: E402,F401
