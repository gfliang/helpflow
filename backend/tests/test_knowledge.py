import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models import KnowledgeChunk, KnowledgeDocument, Membership, User, Workspace
from app.services.documents import parse_document, split_text
from app.services.passwords import hash_password
from app.services.tokens import create_access_token


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: uuid.UUID
    headers: dict[str, str]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def workspace_factory() -> Iterator[Callable[[str], WorkspaceContext]]:
    created: list[tuple[uuid.UUID, uuid.UUID]] = []

    def make(role: str = "admin") -> WorkspaceContext:
        suffix = uuid.uuid4().hex[:10]
        with SessionLocal() as db:
            user = User(
                email=f"knowledge-{suffix}@helpflow.test",
                name="Knowledge Test User",
                password_hash=hash_password("test-password"),
            )
            workspace = Workspace(name="Knowledge Test", slug=f"knowledge-{suffix}")
            db.add_all([user, workspace])
            db.flush()
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
            db.commit()
            token, _ = create_access_token(
                user_id=user.id, workspace_id=workspace.id, role=role
            )
            created.append((workspace.id, user.id))
            return WorkspaceContext(
                workspace_id=workspace.id,
                headers={"Authorization": f"Bearer {token}"},
            )

    yield make

    with SessionLocal() as db:
        for workspace_id, user_id in created:
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.workspace_id == workspace_id))
            db.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.workspace_id == workspace_id)
            )
            db.execute(delete(Membership).where(Membership.workspace_id == workspace_id))
            db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            db.execute(delete(User).where(User.id == user_id))
        db.commit()


def test_split_text_and_parse_markdown(tmp_path) -> None:
    content = "退款政策说明。" * 40
    chunks = split_text(content, chunk_size=50, overlap=10)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)

    path = tmp_path / "guide.md"
    path.write_text("# 标题\n\n正文内容", encoding="utf-8")
    assert parse_document(path, "markdown") == "# 标题\n\n正文内容"


def test_publish_and_archive_control_retrieval(client, workspace_factory) -> None:
    workspace = workspace_factory("admin")
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=workspace.headers,
        json={
            "title": "退款申请流程",
            "category": "退款",
            "content": "年度订阅在首次购买后 7 天内可以申请全额退款，管理员在账单页面提交申请。",
        },
    )
    assert created.status_code == 201
    document_id = created.json()["data"]["id"]

    documents = client.get("/api/v1/knowledge/documents", headers=workspace.headers).json()["data"]
    document = next(item for item in documents if item["id"] == document_id)
    assert document["status"] == "ready"
    assert document["chunk_count"] > 0

    before_publish = client.post(
        "/api/v1/knowledge/test-query",
        headers=workspace.headers,
        json={"query": "退款怎么申请"},
    ).json()["data"]
    assert before_publish["matches"] == []

    published = client.post(
        f"/api/v1/knowledge/documents/{document_id}/publish", headers=workspace.headers
    )
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"

    after_publish = client.post(
        "/api/v1/knowledge/test-query",
        headers=workspace.headers,
        json={"query": "退款怎么申请"},
    ).json()["data"]
    assert after_publish["matches"][0]["document_id"] == document_id
    assert "全额退款" in after_publish["matches"][0]["content"]

    archived = client.post(
        f"/api/v1/knowledge/documents/{document_id}/archive", headers=workspace.headers
    )
    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"

    after_archive = client.post(
        "/api/v1/knowledge/test-query",
        headers=workspace.headers,
        json={"query": "退款怎么申请"},
    ).json()["data"]
    assert after_archive["matches"] == []
    assert "没有找到" in after_archive["answer_preview"]

    republished = client.post(
        f"/api/v1/knowledge/documents/{document_id}/publish", headers=workspace.headers
    )
    assert republished.status_code == 200
    assert republished.json()["data"]["status"] == "published"


def test_markdown_upload_is_indexed_and_workspace_isolated(client, workspace_factory) -> None:
    workspace = workspace_factory("admin")
    other_workspace = workspace_factory("admin")
    uploaded = client.post(
        "/api/v1/knowledge/documents/upload",
        headers=workspace.headers,
        files={
            "file": (
                "integration.md",
                "# 接入指南\n\n把 widget.js 放到页面的 body 之前即可完成网站嵌入。",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["data"]["id"]

    detail = client.get(
        f"/api/v1/knowledge/documents/{document_id}", headers=workspace.headers
    ).json()["data"]
    assert detail["status"] == "ready"
    assert detail["source_filename"] == "integration.md"

    client.post(f"/api/v1/knowledge/documents/{document_id}/publish", headers=workspace.headers)
    own_result = client.post(
        "/api/v1/knowledge/test-query",
        headers=workspace.headers,
        json={"query": "怎么嵌入网站"},
    ).json()["data"]
    assert own_result["matches"][0]["document_id"] == document_id

    other_result = client.post(
        "/api/v1/knowledge/test-query",
        headers=other_workspace.headers,
        json={"query": "怎么嵌入网站"},
    ).json()["data"]
    assert other_result["matches"] == []
    assert (
        client.get(
            f"/api/v1/knowledge/documents/{document_id}", headers=other_workspace.headers
        ).status_code
        == 404
    )


def test_viewer_cannot_modify_knowledge(client, workspace_factory) -> None:
    viewer = workspace_factory("viewer")
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=viewer.headers,
        json={"title": "只读测试", "content": "只读用户不能创建知识。"},
    )
    assert response.status_code == 403
