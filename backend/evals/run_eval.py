"""Run the golden-set evaluation from the command line.

Usage:

    cd backend && uv run python -m evals.run_eval --workspace helpflow
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import EvalCase, Workspace
from app.services.evaluation import run_evaluation

PASS_THRESHOLD = 0.8


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the HelpFlow retrieval evaluation")
    parser.add_argument("--workspace", default="helpflow", help="Workspace slug")
    parser.add_argument("--name", default="baseline", help="Name stored on the eval run")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases")
    parser.add_argument("--judge", default="heuristic", help="Scoring strategy, default heuristic")
    parser.add_argument("--no-gate", action="store_true", help="Do not fail when pass_rate < 0.8")
    parser.add_argument("--cases", default=None, help="Optional golden JSONL file path")
    return parser.parse_args()


def _percent(value: object) -> str:
    return f"{float(value) * 100:.1f}%" if isinstance(value, (int, float)) else "0.0%"


def _print_metrics(run) -> None:
    metrics = run.metrics or {}
    print(f"评测完成：{run.name}（run_id={run.id}）")
    print(f"状态：{run.status}  判分方式：{metrics.get('judge', run.judge)}")
    print(
        f"用例数：{metrics.get('total_cases', 0)}  "
        f"通过：{metrics.get('passed_cases', 0)}  "
        f"通过率：{_percent(metrics.get('pass_rate'))}"
    )
    print(
        f"检索命中率 hit@4：{_percent(metrics.get('hit_rate'))}  "
        f"引用准确率：{_percent(metrics.get('citation_accuracy'))}"
    )
    print(
        f"拒答准确率：{_percent(metrics.get('refusal_accuracy'))}  "
        f"忠实度：{_percent(metrics.get('faithfulness'))}  "
        f"平均耗时：{metrics.get('avg_latency_ms', 0)} ms"
    )


def _print_failures(run_id) -> None:
    with SessionLocal() as db:
        failures = db.scalars(
            select(EvalCase)
            .where(EvalCase.run_id == run_id, EvalCase.passed.is_(False))
            .order_by(EvalCase.created_at)
            .limit(10)
        ).all()
    if not failures:
        print("没有失败用例。")
        return
    print(f"失败用例（前 {len(failures)} 条）：")
    for case in failures:
        expected = "、".join(case.expected_documents or []) or "（无，应拒答）"
        cited = "、".join(case.cited_documents or []) or "（无引用）"
        print(f"- [{case.expected_mode}] {case.question}")
        print(f"  期望文档：{expected}")
        print(f"  实际引用：{cited}")
        print(f"  预测/期望模式：{case.predicted_mode}/{case.expected_mode}")
        if case.error:
            print(f"  错误：{case.error}")


def main() -> None:
    args = _parse_args()
    cases_path = Path(args.cases) if args.cases else None
    with SessionLocal() as db:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == args.workspace))
        if workspace is None:
            print(f"工作空间 '{args.workspace}' 不存在，请先运行 make seed。")
            sys.exit(2)
        run = run_evaluation(
            db,
            workspace,
            name=args.name,
            judge=args.judge,
            limit=args.limit,
            cases_path=cases_path,
        )

    _print_metrics(run)
    _print_failures(run.id)

    pass_rate = (run.metrics or {}).get("pass_rate", 0.0)
    if isinstance(pass_rate, (int, float)) and pass_rate < PASS_THRESHOLD and not args.no_gate:
        print(f"通过率低于 {PASS_THRESHOLD:.0%}，评测未达标。")
        sys.exit(1)


if __name__ == "__main__":
    main()
