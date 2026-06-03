from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.services.jde_workflow_service import jde_procurement_workflow_status


router = APIRouter(
    prefix="/demo/jde-procurement",
    tags=["jde-demo-workflow"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/workflow-status")
def jde_procurement_workflow_status_endpoint(
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return jde_procurement_workflow_status(db)
