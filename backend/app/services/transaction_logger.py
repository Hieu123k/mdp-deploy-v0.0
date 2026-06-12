import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction


def log_transaction(
    db: Session,
    *,
    direction: str,
    protocol: str,
    status: str,
    data_model_id: uuid.UUID | None = None,
    endpoint: str | None = None,
    request_payload: dict[str, Any] | list[Any] | None = None,
    response_payload: dict[str, Any] | list[Any] | None = None,
    error_message: str | None = None,
    auth_type: str | None = None,
    api_key_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    source_system: str | None = None,
) -> Transaction:
    transaction = Transaction(
        direction=direction,
        protocol=protocol,
        data_model_id=data_model_id,
        endpoint=endpoint,
        status=status,
        request_payload=request_payload,
        response_payload=response_payload,
        error_message=error_message,
        auth_type=auth_type,
        api_key_id=api_key_id,
        user_id=user_id,
        source_system=source_system,
    )
    db.add(transaction)
    db.flush()
    return transaction


def get_transaction(db: Session, transaction_id: uuid.UUID) -> Transaction | None:
    return db.get(Transaction, transaction_id)


def get_transaction_stats(db: Session) -> dict[str, Any]:
    """All-time transaction counts grouped by status (NO limit/cap), so the Dashboard 'Failed' and
    total reflect every row rather than only the most recent page. Returns
    ``{"total": <int>, "by_status": {<status>: <int>, ...}}``."""
    rows = db.execute(
        select(Transaction.status, func.count()).group_by(Transaction.status)
    ).all()
    by_status = {str(row_status): int(count) for row_status, count in rows}
    return {"total": sum(by_status.values()), "by_status": by_status}


def list_transactions(
    db: Session,
    *,
    direction: str | None = None,
    protocol: str | None = None,
    status: str | None = None,
    data_model_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Transaction]:
    query = select(Transaction).order_by(Transaction.created_at.desc())
    if direction is not None:
        query = query.where(Transaction.direction == direction)
    if protocol is not None:
        query = query.where(Transaction.protocol == protocol)
    if status is not None:
        query = query.where(Transaction.status == status)
    if data_model_id is not None:
        query = query.where(Transaction.data_model_id == data_model_id)
    query = query.limit(limit).offset(offset)
    return list(db.scalars(query))
