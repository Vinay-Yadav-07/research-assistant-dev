"""Domain exceptions. They carry no HTTP knowledge; `app/api/errors.py` maps them to responses."""

from typing import Any


class AppError(Exception):
    """Base class for all expected application errors."""

    code: str = "app_error"
    default_message: str = "An application error occurred."

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    """The requested resource does not exist (or is not visible to the caller)."""

    code = "not_found"
    default_message = "Resource not found."


class AuthenticationError(AppError):
    """The request carries no valid access token."""

    code = "unauthenticated"
    default_message = "A valid access token is required."


class PermissionDeniedError(AppError):
    """The caller is authenticated but not allowed to perform the action."""

    code = "permission_denied"
    default_message = "You do not have permission to perform this action."


class InvalidInputError(AppError):
    """The request is well-formed but violates a domain rule."""

    code = "invalid_input"
    default_message = "The request is invalid."


class FileTooLargeError(InvalidInputError):
    """An uploaded file exceeds the size limit."""

    code = "file_too_large"
    default_message = "The file is too large."


class UnsupportedFileTypeError(InvalidInputError):
    """An uploaded file is not of an accepted type."""

    code = "unsupported_file_type"
    default_message = "Only PDF files are accepted."


class NotOpenAccessError(InvalidInputError):
    """A discovered paper has no open-access PDF; only its metadata and link exist (FR-17)."""

    code = "not_open_access"
    default_message = "This paper has no open-access PDF. Open the source to read it."


class ConflictError(AppError):
    """The action conflicts with the current state (e.g. a duplicate)."""

    code = "conflict"
    default_message = "The request conflicts with the current state."


class CompatibilityWarningError(ConflictError):
    """The document does not match the workspace topic; the user must confirm (FR-22)."""

    code = "compatibility_warning"
    default_message = (
        "This document looks unrelated to the workspace. Import it anyway, move it to "
        "another workspace, or cancel."
    )


class NoReadyDocumentsError(ConflictError):
    """The workspace has no ready papers to build a knowledge graph from."""

    code = "no_ready_documents"
    default_message = "Add papers to this workspace and wait until they are ready."


class CallBudgetExceededError(AppError):
    """A knowledge graph job used all the LLM calls it is allowed (SRS §9.1)."""

    code = "budget_exceeded"
    default_message = "This run reached its limit of model calls."


class ExternalServiceError(AppError):
    """An external API or model provider failed."""

    code = "external_service_error"
    default_message = "An external service failed."


class PdfUnavailableError(ExternalServiceError):
    """No open-access PDF location of a paper could be downloaded safely as a PDF."""

    code = "pdf_unavailable"
    default_message = "The paper's PDF could not be downloaded. Open the source instead."


class SourceUnavailableError(ExternalServiceError):
    """A scholarly source (arXiv, OpenAlex) did not answer a paper lookup; retrying may help."""

    code = "source_unavailable"
    default_message = "The paper's source didn't respond. Try again in a moment."


class LLMOutputError(ExternalServiceError):
    """An LLM returned output that does not validate against the requested schema."""

    code = "llm_output_invalid"
    default_message = "The language model returned an invalid response."


class LLMProviderError(ExternalServiceError):
    """An LLM call failed after its retries (rate limit, timeout, provider outage)."""

    code = "llm_unavailable"
    default_message = "The language model is unavailable right now. Please try again shortly."


class LLMQuotaExceededError(LLMProviderError):
    """The model's daily request quota is used up; retrying today will not help."""

    code = "llm_quota_exhausted"
    default_message = (
        "The language model's daily request quota is used up. Try again later or configure "
        "another model."
    )


class DocumentParseError(InvalidInputError):
    """A document could not be read (corrupt file or unsupported content)."""

    code = "document_unreadable"
    default_message = "The document could not be read."


class ScannedDocumentError(DocumentParseError):
    """The PDF has no usable text layer (a scan); OCR is out of scope (SRS §4)."""

    code = "document_scanned"
    default_message = (
        "The PDF has no text layer (it looks scanned). Upload a PDF with selectable text."
    )


class ProviderConfigurationError(AppError):
    """Configuration selects a provider that is unknown or not implemented yet."""

    code = "provider_not_available"
    default_message = "The configured provider is not available."


class DependencyUnavailableError(AppError):
    """A required internal dependency (e.g. the database) is unavailable."""

    code = "dependency_unavailable"
    default_message = "A required service is temporarily unavailable."
