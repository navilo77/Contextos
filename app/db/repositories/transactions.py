from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from app.db.repositories.errors import ActiveTransactionRequiredError


def require_explicit_transaction(session: AsyncSession) -> None:
    transaction = session.sync_session.get_transaction()
    if transaction is None or transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise ActiveTransactionRequiredError(
            "Repository operations require a caller-owned session.begin() transaction."
        )
