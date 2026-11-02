import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import EvalCase, EvalRun
from app.schemas.eval import (
    EvalCaseResponse,
    EvalRunDetail,
    EvalRunSummary,
    EvalSummaryResponse,
    EvalTrendPoint,
)
from app.services.evaluation import load_golden_cases

router = APIRouter(prefix="/evals", tags=["evals"])


def _pass_rate(run: EvalRun) -> float:
    value = (run.metrics or {}).get("pass_rate", 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


@router.get("/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[EvalRunSummary]]:
    runs = db.scalars(
        select(EvalRun)
        .where(EvalRun.workspace_id == current.workspace.id)
        .order_by(EvalRun.created_at.desc())
        .limit(limit)
    ).all()
    return {"data": [EvalRunSummary.model_validate(run, from_attributes=True) for run in runs]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, EvalRunDetail]:
    run = db.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id, EvalRun.workspace_id == current.workspace.id
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval run not found")
    cases = db.scalars(
        select(EvalCase)
        .where(EvalCase.run_id == run.id)
        .order_by(EvalCase.created_at, EvalCase.id)
    ).all()
    summary = EvalRunSummary.model_validate(run, from_attributes=True)
    return {
        "data": EvalRunDetail(
            **summary.model_dump(),
            cases=[
                EvalCaseResponse.model_validate(case, from_attributes=True) for case in cases
            ],
        )
    }


@router.get("/summary")
def eval_summary(
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, EvalSummaryResponse]:
    runs = db.scalars(
        select(EvalRun)
        .where(EvalRun.workspace_id == current.workspace.id)
        .order_by(EvalRun.created_at.desc())
        .limit(10)
    ).all()
    latest = EvalRunSummary.model_validate(runs[0], from_attributes=True) if runs else None
    history = [
        EvalTrendPoint(
            id=run.id,
            name=run.name,
            created_at=run.created_at,
            pass_rate=_pass_rate(run),
        )
        for run in runs
    ]
    try:
        golden_total = len(load_golden_cases())
    except (OSError, ValueError):
        golden_total = 0
    return {
        "data": EvalSummaryResponse(
            latest=latest,
            history=history,
            golden_total=golden_total,
        )
    }
