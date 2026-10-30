from __future__ import annotations


class RepositoryError(RuntimeError):
    """Base error for a rejected repository operation."""


class RepositoryInputError(RepositoryError, ValueError):
    """Raised when a repository input violates the storage contract."""


class ProjectNotFoundError(RepositoryError):
    """Raised when a project is absent from the requested workspace scope."""


class RevisionConflictError(RepositoryError):
    """Raised when a caller attempts to update a stale project revision."""

    def __init__(self, expected_revision: int, actual_revision: int) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"Project revision conflict: expected {expected_revision}, "
            f"current revision is {actual_revision}."
        )


class IdempotencyConflictError(RepositoryError):
    """Raised when an idempotency key is reused for a different request."""


class ActiveTransactionRequiredError(RepositoryError):
    """Raised when a write/read repository call is made outside an explicit transaction."""
