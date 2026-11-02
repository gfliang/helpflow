from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["system"])


@router.get("/health", summary="API and database health check")
def health_check(db: Session = Depends(get_db)) -> dict[str, object]:  # noqa: B008
    db.execute(text("SELECT 1"))
    return {"data": {"status": "ok", "database": "ok"}}
