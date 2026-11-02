"""Golden-set evaluation for retrieval hit rate, citations and refusal behaviour."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import EvalCase, EvalRun, Workspace
from app.services.rag import docs_to_context
from app.services.retrieval import HelpFlowRetriever

logger = logging.getLogger(__name__)

GOLDEN_CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "golden_qa.jsonl"


def load_golden_cases(path: Path | None = None) -> list[dict[str, object]]:
    """Read the JSONL golden set, one question per non-empty line."""
    target = path or GOLDEN_CASES_PATH
    cases: list[dict[str, object]] = []
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            cases.append(json.loads(stripped))
    return cases


def _normalize_title(title: object) -> str:
    return "".join(str(title).lower().split())


def _top_titles(documents: list[Document], limit: int = 4) -> set[str]:
    """Multi-query retrieval can return more than `limit` docs, so rank by score first."""
    scored = sorted(
        documents,
        key=lambda document: float(document.metadata.get("score", 0.0)),
        reverse=True,
    )
    return {
        _normalize_title(document.metadata.get("document_title", "")) for document in scored[:limit]
    }


def _rate(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


def run_evaluation(
    db: Session,
    workspace: Workspace,
    *,
    name: str = "baseline",
    judge: str = "heuristic",
    limit: int | None = None,
    created_by_user_id: uuid.UUID | None = None,
    cases_path: Path | None = None,
) -> EvalRun:
    """Retrieve answers for every golden case and persist one EvalRun plus its cases."""
    cases = load_golden_cases(cases_path)
    if limit is not None:
        cases = cases[:limit]

    run = EvalRun(
        workspace_id=workspace.id,
        name=name,
        status="running",
        judge=judge,
        total_cases=len(cases),
        created_by_user_id=created_by_user_id,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    records: list[EvalCase] = []
    hit_values: list[bool] = []
    citation_values: list[bool] = []
    refusal_values: list[bool] = []
    faithfulness_values: list[bool] = []
    latencies: list[int] = []
    error_count = 0
    # 评测固定使用基础混合检索：MultiQuery 依赖外部模型，会让指标不可复现。
    retriever = HelpFlowRetriever(db=db, workspace_id=workspace.id, limit=4)

    for case in cases:
        started = time.perf_counter()
        question = str(case.get("question", ""))
        expected_documents = [str(item) for item in case.get("expected_documents") or []]
        must_include = [str(item) for item in case.get("must_include") or []]
        should_refuse = bool(case.get("should_refuse", False))
        expected_mode = "refused" if should_refuse else "answer"

        hit = False
        citation_ok = False
        faithful = False
        predicted_mode = "refused"
        confidence = 0.0
        cited_titles: list[str] = []
        error: str | None = None

        try:
            documents = retriever.invoke(question)
            context, citations, confidence = docs_to_context(
                documents, limit=settings.chat_context_limit
            )
            if not context or confidence < settings.chat_confidence_threshold:
                predicted_mode = "refused"
            else:
                predicted_mode = "answer"
            cited_titles = [str(item.get("document_title", "")) for item in citations]
            retrieved_titles = _top_titles(documents, limit=4)
            hit = any(
                _normalize_title(title) in retrieved_titles for title in expected_documents
            )
            if should_refuse:
                citation_ok = predicted_mode == "refused" or not cited_titles
                faithful = not cited_titles
            else:
                expected_titles = {_normalize_title(title) for title in expected_documents}
                citation_ok = any(
                    _normalize_title(title) in expected_titles for title in cited_titles
                )
                context_text = "\n".join(item.content for item in context)
                faithful = bool(citations) and all(
                    token in context_text for token in must_include
                )
        except Exception as exc:  # one bad case must not abort the run
            error = str(exc)[:2000]
            error_count += 1
            logger.exception("Eval case failed: %s", question)

        latency_ms = int((time.perf_counter() - started) * 1000)
        refusal_ok = predicted_mode == expected_mode
        passed = error is None and (
            predicted_mode == "refused" if should_refuse else hit and citation_ok and faithful
        )

        if not should_refuse:
            hit_values.append(hit)
        citation_values.append(citation_ok)
        refusal_values.append(refusal_ok)
        faithfulness_values.append(faithful)
        latencies.append(latency_ms)

        records.append(
            EvalCase(
                run_id=run.id,
                workspace_id=workspace.id,
                question=question,
                expected_documents=expected_documents,
                cited_documents=cited_titles,
                predicted_mode=predicted_mode,
                expected_mode=expected_mode,
                passed=passed,
                metrics={
                    "hit": hit,
                    "citation_accuracy": citation_ok,
                    "faithfulness": faithful,
                    "confidence": round(float(confidence), 4),
                },
                latency_ms=latency_ms,
                error=error,
            )
        )

    total = len(cases)
    passed_cases = sum(1 for record in records if record.passed)
    metrics: dict[str, object] = {
        "hit_rate": _rate(hit_values),
        "citation_accuracy": _rate(citation_values),
        "refusal_accuracy": _rate(refusal_values),
        "faithfulness": _rate(faithfulness_values),
        "pass_rate": round(passed_cases / total, 4) if total else 0.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "total_cases": total,
        "passed_cases": passed_cases,
        "judge": judge,
    }

    run.status = "failed" if error_count else "completed"
    run.total_cases = total
    run.passed_cases = passed_cases
    run.metrics = metrics
    run.finished_at = datetime.now(UTC)
    db.add_all(records)
    db.commit()
    db.refresh(run)
    return run
