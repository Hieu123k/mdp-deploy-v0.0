import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionRead, TransactionStats
from app.services.transaction_logger import (
    get_transaction,
    get_transaction_stats,
    list_transactions,
)


router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[TransactionRead])
def list_transactions_endpoint(
    db: Annotated[Session, Depends(get_db)],
    direction: str | None = None,
    protocol: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    data_model_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Transaction]:
    return list_transactions(
        db,
        direction=direction,
        protocol=protocol,
        status=status_filter,
        data_model_id=data_model_id,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=TransactionStats)
def get_transaction_stats_endpoint(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    # Declared BEFORE /{transaction_id} so "stats" is not parsed as a UUID path param.
    return get_transaction_stats(db)


@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction_endpoint(
    transaction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Transaction:
    transaction = get_transaction(db, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )
    return transaction

