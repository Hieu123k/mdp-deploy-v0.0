from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.services.procurement_staging_service import (
    get_procurement_staging_counts,
    seed_procurement_staging_data,
)


router = APIRouter(
    prefix="/admin/demo",
    tags=["admin-demo"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/seed-procurement-staging")
def seed_procurement_staging_endpoint(
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    counts = seed_procurement_staging_data(db)
    db.commit()
    return {
        "status": "success",
        "message": "Procurement staging data seeded successfully",
        "tables": counts,
    }


@router.get("/procurement-staging-summary")
def procurement_staging_summary_endpoint(
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return {
        "status": "success",
        "tables": get_procurement_staging_counts(db),
    }
