"""AppError exception hierarchy and error catalogue.
Governing spec: BE-13.
"""

from typing import Any


class AppError(Exception):
    """Base error for all application-level errors."""
    code: str = "INTERNAL_ERROR"
    message: str = "Something went wrong on our end."
    status: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status: int | None = None,
        retryable: bool | None = None,
    ):
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        if retryable is not None:
            self.retryable = retryable
        self.details: dict[str, Any] = details or {}


# ==============================================================================
# Client Errors (4xx)
# ==============================================================================

class ClientError(AppError):
    status: int = 400


class ValidationError(ClientError):
    code = "VALIDATION_ERROR"
    message = "Some of the information sent wasn't valid."
    status = 422


class IdentityRequiredError(ClientError):
    code = "IDENTITY_REQUIRED"
    message = "Sign in or start a session to upload documents."
    status = 401


class InvalidTokenError(ClientError):
    code = "INVALID_TOKEN"
    message = "Your session has expired. Please sign in again."
    status = 401


class NotFoundError(ClientError):
    code = "NOT_FOUND"
    message = "That document couldn't be found."
    status = 404


class DemoDocumentImmutableError(ClientError):
    code = "DEMO_DOCUMENT_IMMUTABLE"
    message = "Demo documents can't be changed or deleted."
    status = 403


class DocumentNotReadyError(ClientError):
    code = "DOCUMENT_NOT_READY"
    message = "That document is still being processed."
    status = 409


class PayloadTooLargeError(ClientError):
    code = "DOCUMENT_TOO_LARGE"
    message = "This file is larger than the 20 MB limit."
    status = 413


class UnsupportedMediaTypeError(ClientError):
    code = "UNSUPPORTED_MEDIA_TYPE"
    message = "Only PDF and Word (.docx) files are supported."
    status = 415


class EmptyFileError(ClientError):
    code = "EMPTY_FILE"
    message = "This file appears to be empty."
    status = 422


class QuestionTooShortError(ClientError):
    code = "QUESTION_TOO_SHORT"
    message = "Please ask a longer question."
    status = 422


class TooManyDocumentsError(ClientError):
    code = "TOO_MANY_DOCUMENTS"
    message = "You can search at most 50 documents at once."
    status = 422


class RateLimitedError(ClientError):
    code = "RATE_LIMITED"
    message = "You're going a bit fast. Try again in a moment."
    status = 429
    retryable = True

    def __init__(
        self,
        retry_after: int = 60,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, details=details)
        self.retry_after = retry_after


class StorageBudgetExceededError(ClientError):
    code = "STORAGE_BUDGET_EXCEEDED"
    message = "The demo has reached its storage limit."
    status = 507


# ==============================================================================
# Upstream Errors (5xx)
# ==============================================================================

class UpstreamError(AppError):
    status: int = 503
    retryable: bool = True


class ServiceUnavailableError(UpstreamError):
    code = "SERVICE_UNAVAILABLE"
    message = "Something's temporarily unavailable. Please try again."


class DatabaseUnavailableError(UpstreamError):
    code = "DATABASE_UNAVAILABLE"
    message = "We're having trouble reaching our database."


class StorageUnavailableError(UpstreamError):
    code = "STORAGE_UNAVAILABLE"
    message = "File storage is temporarily unavailable."


class GenerationFailedError(UpstreamError):
    code = "GENERATION_FAILED"
    message = "The answer service didn't respond. Please try again."


class UpstreamRateLimitedError(AppError):
    code = "UPSTREAM_RATE_LIMITED"
    message = "We've hit our AI provider's rate limit. Try again shortly."
    status = 429
    retryable = True

    def __init__(
        self,
        retry_after: int = 60,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, details=details)
        self.retry_after = retry_after


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    message = "Something went wrong on our end."
    status = 500
    retryable = False


# ==============================================================================
# Pipeline Errors (Recorded on Document row, never HTTP)
# ==============================================================================

class PipelineError(Exception):
    code: str
    status_detail: str

    def __init__(self, code: str, status_detail: str):
        super().__init__(status_detail)
        self.code = code
        self.status_detail = status_detail


class NoTextExtractedError(PipelineError):
    def __init__(self):
        super().__init__(
            "NO_TEXT_EXTRACTED",
            "No readable text was found. Scanned documents aren't supported yet."
        )


class DocumentEncryptedError(PipelineError):
    def __init__(self):
        super().__init__(
            "DOCUMENT_ENCRYPTED",
            "This PDF is password-protected."
        )


class DocumentCorruptError(PipelineError):
    def __init__(self):
        super().__init__(
            "DOCUMENT_CORRUPT",
            "This file couldn't be read. It may be damaged."
        )


class DocumentTooLongError(PipelineError):
    def __init__(self):
        super().__init__(
            "DOCUMENT_TOO_LONG",
            "Documents over 500 pages aren't supported yet."
        )


class NoContentAfterChunkingError(PipelineError):
    def __init__(self):
        super().__init__(
            "NO_CONTENT_AFTER_CHUNKING",
            "No usable content was found in this document."
        )


class EmbeddingFailedError(PipelineError):
    def __init__(self):
        super().__init__(
            "EMBEDDING_FAILED",
            "Processing failed while indexing this document."
        )


class IncompleteEmbeddingError(PipelineError):
    def __init__(self):
        super().__init__(
            "INCOMPLETE_EMBEDDING",
            "Processing didn't finish. Please try uploading again."
        )


class IngestionTimeoutError(PipelineError):
    def __init__(self):
        super().__init__(
            "INGESTION_TIMEOUT",
            "Processing took too long and was stopped."
        )
