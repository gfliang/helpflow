"""Evaluation pipeline: golden cases run offline and persist metrics."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    EvalCase,
    EvalRun,
    KnowledgeChunk,
    KnowledgeDocument,
    Membership,
    User,
    Workspace,
)
from app.services.evaluation import run_evaluation
from app.services.passwords import hash_password
from app.services.tokens import create_access_token

METRIC_KEYS = {
    "hit_rate",
    "citation_accuracy",
    "refusal_accuracy",
    "faithfulness",
    "pass_rate",
    "avg_latency_ms",
    "total_cases",
    "passed_cases",
}


@dataclass(frozen=True)
class EvalWorkspace:
    workspace_id: uuid.UUID
    slug: str
    headers: dict[str, str]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def eval_workspace() -> Iterator[EvalWorkspace]:
    suffix = uuid.uuid4().hex[:10]
    with SessionLocal() as db:
        user = User(
            email=f"eval-{suffix}@helpflow.test",
            name="Eval User",
            password_hash=hash_password("test-password"),
        )
        workspace = Workspace(name="Eval Test", slug=f"eval-{suffix}")
        db.add_all([user, workspace])
        db.flush()
        db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="admin"))
        db.commit()
        token, _ = create_access_token(user_id=user.id, workspace_id=workspace.id, role="admin")
        yield EvalWorkspace(
            workspace_id=workspace.id,
            slug=workspace.slug,
            headers={"Authorization": f"Bearer {token}"},
        )
        workspace_id, user_id = workspace.id, user.id

    with SessionLocal() as db:
        db.execute(delete(EvalCase).where(EvalCase.workspace_id == workspace_id))
        db.execute(delete(EvalRun).where(EvalRun.workspace_id == workspace_id))
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.workspace_id == workspace_id))
        db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.workspace_id == workspace_id))
        db.execute(delete(Membership).where(Membership.workspace_id == workspace_id))
        db.execute(delete(Workspace).where(Workspace.id == workspace_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def _publish(client: TestClient, workspace: EvalWorkspace, title: str, content: str) -> None:
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=workspace.headers,
        json={"title": title, "content": content},
    )
    assert created.status_code == 201
    document_id = created.json()["data"]["id"]
    published = client.post(
        f"/api/v1/knowledge/documents/{document_id}/publish", headers=workspace.headers
    )
    assert published.status_code == 200


def _golden_file(tmp_path, cases: list[dict[str, object]]) -> str:
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases), encoding="utf-8")
    return str(path)


def test_run_evaluation_persists_metrics(client, eval_workspace, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "chat_confidence_threshold", 0.0)
    _publish(
        client,
        eval_workspace,
        "退款政策",
        "年度订阅在首次购买后 7 天内且 AI 使用量低于 100 次时可以申请全额退款。",
    )
    golden = _golden_file(
        tmp_path,
        [
            {
                "id": "e01",
                "question": "年度订阅怎么退款？",
                "expected_documents": ["退款政策"],
                "must_include": ["7 天"],
                "should_refuse": False,
            },
            {
                "id": "e02",
                "question": "火星的天气怎么样？",
                "expected_documents": [],
                "must_include": [],
                "should_refuse": True,
            },
        ],
    )

    with SessionLocal() as db:
        workspace = db.get(Workspace, eval_workspace.workspace_id)
        assert workspace is not None
        run = run_evaluation(
            db,
            workspace,
            name="pytest-baseline",
            limit=None,
            cases_path=Path(golden),
        )

    assert run.status == "completed"
    assert run.total_cases == 2
    assert METRIC_KEYS <= set(run.metrics)
    assert run.metrics["hit_rate"] == 1.0
    assert run.metrics["total_cases"] == 2

    with SessionLocal() as db:
        cases = db.scalars(select(EvalCase).where(EvalCase.run_id == run.id)).all()
    assert len(cases) == 2
    assert {case.expected_mode for case in cases} == {"answer", "refused"}
    assert all(case.predicted_mode in {"answer", "refused"} for case in cases)


def test_eval_api_lists_runs_and_summary(client, eval_workspace, tmp_path) -> None:
    golden = _golden_file(
        tmp_path,
        [
            {
                "id": "e03",
                "question": "支持 Webhook 吗？",
                "expected_documents": [],
                "must_include": [],
                "should_refuse": True,
            }
        ],
    )
    with SessionLocal() as db:
        workspace = db.get(Workspace, eval_workspace.workspace_id)
        assert workspace is not None
        run_evaluation(db, workspace, name="api-check", cases_path=Path(golden))

    listed = client.get("/api/v1/evals/runs", headers=eval_workspace.headers)
    assert listed.status_code == 200
    runs = listed.json()["data"]
    assert runs and runs[0]["name"] == "api-check"

    detail = client.get(f"/api/v1/evals/runs/{runs[0]['id']}", headers=eval_workspace.headers)
    assert detail.status_code == 200
    assert len(detail.json()["data"]["cases"]) == 1

    summary = client.get("/api/v1/evals/summary", headers=eval_workspace.headers)
    assert summary.status_code == 200
    payload = summary.json()["data"]
    assert payload["latest"]["name"] == "api-check"
    assert "history" in payload
