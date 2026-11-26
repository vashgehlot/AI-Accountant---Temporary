"""Typed errors that map to clear HTTP responses: {"detail": {"code", "message"}}."""
from __future__ import annotations

from typing import Optional


class LedgerSyncError(Exception):
    """Base error. Subclasses set the HTTP status and a stable machine-readable code."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "status_code": self.status_code}


class FileTooLarge(LedgerSyncError):
    status_code = 413
    code = "file_too_large"


class UnsupportedFile(LedgerSyncError):
    status_code = 415
    code = "unsupported_file"


class UnreadableFile(LedgerSyncError):
    status_code = 422
    code = "unreadable_file"


class ModelError(LedgerSyncError):
    """The model answered, but not with something usable (HTTP error, truncated, not JSON)."""

    status_code = 502
    code = "ai_error"


class ModelUnavailable(LedgerSyncError):
    status_code = 503
    code = "ai_offline"


class ModelTimeout(LedgerSyncError):
    status_code = 504
    code = "ai_timeout"


class JobNotFound(LedgerSyncError):
    status_code = 404
    code = "job_not_found"


class InvalidTransactions(LedgerSyncError):
    status_code = 422
    code = "transactions_need_fixing"

    def __init__(self, message: str, problems=()):
        super().__init__(message)
        self.problems = list(problems)   # one line per problem, for a list such as the Excel export's


class ModelRateLimited(ModelUnavailable):
    """The hosted model's rate limit (e.g. a free plan's tokens per minute) is used up for now."""

    code = "ai_rate_limited"


class NotFound(LedgerSyncError):
    status_code = 404
    code = "not_found"


class ClientArchived(LedgerSyncError):
    """A change to an archived client: it can only be restored."""

    status_code = 409
    code = "client_archived"


class InvalidInput(LedgerSyncError):
    status_code = 422
    code = "invalid_input"


class SameFile(LedgerSyncError):
    """A file already saved for the client, or being read for it now: read again, its rows would be booked twice."""

    status_code = 409
    code = "same_file"


class RefusedRequest(LedgerSyncError):
    """A request any web page could have sent unasked: it lacks the header the LedgerSync pages send."""

    status_code = 403
    code = "refused_request"


class StorageError(LedgerSyncError):
    """The database could not be used, or its address is not set; the server log says why."""

    status_code = 500
    code = "storage_error"


class ChangedMeanwhile(LedgerSyncError):
    """A change lost the race with other writes to the same client every time it was tried."""

    status_code = 409
    code = "changed_meanwhile"



class YearClosed(LedgerSyncError):
    """A change to a closed year: it must be reopened first."""

    status_code = 409
    code = "year_closed"


class StillWorking(LedgerSyncError):
    """A message, an answer or a delete for a chat while its last message is still being worked on."""

    status_code = 409
    code = "still_working"
