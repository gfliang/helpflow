# HelpFlow Agentic RAG 升级任务清单（Tasks）

> 依赖顺序执行。每个阶段结束必须运行对应验证命令；失败先修复再进入下一阶段。

## 阶段 0：基线与依赖（已完成部分）

- [x] 安装 `langchain 0.3.30`、`langchain-openai 0.3.35`、`langchain-text-splitters 0.3.11`、`langgraph 0.6.11`、`langgraph-checkpoint-postgres 2.0.25`、`langfuse 3.15.0`、`psycopg-pool 3.3.3`。
- [x] 安装 `fastembed 0.6.1` + `onnxruntime 1.18.1`（Intel macOS 兼容）。
- [x] 验证 `BAAI/bge-small-zh-v1.5` 可推理，输出 512 维。
- [x] 记录基线：`uv run pytest` 当前 20 passed；`alembic current = 20261026_0006`。

## 阶段 1：配置与基础设施

- [x] `backend/app/core/config.py`：新增 §4.1 全部字段与 `langgraph_database_url` 属性。
- [x] `.env.example`：新增 EMBEDDING/RAG/AGENT/LANGFUSE/EVAL 注释块。
- [x] `docker-compose.yml`：新增 `observability` profile（langfuse-db/clickhouse/minio/langfuse）。
- [x] `Makefile`：新增 `reindex`、`eval`、`infra-obs`；保留现有 target。
- 验证：`uv run python -c "from app.core.config import settings; print(settings.langgraph_database_url)"`。

## 阶段 2：真实向量与切片

- [x] `backend/app/providers/embeddings.py`：实现 `EmbeddingProvider`、`BGEEmbeddingProvider`、512 维哈希兜底、懒加载单例与降级日志。
- [x] `backend/app/services/documents.py`：`split_text()` 改用 `RecursiveCharacterTextSplitter`（180/30，中文分隔符）。
- [x] `backend/app/tasks/knowledge.py`：`embed_many` 批量嵌入。
- [x] 新建 `backend/app/tasks/reindex.py`：重建已发布文档 chunks，支持 CLI。
- [x] 新建迁移 `backend/alembic/versions/20261028_0007_bge_embeddings.py`：清空 chunks、embedding 改 `vector(512)`、重建 HNSW。
- [x] `backend/app/models/core.py`：`KnowledgeChunk.embedding` 改 `Vector(settings.embedding_dimensions)`。
- 验证：
  - `uv run alembic upgrade head`
  - `uv run python -m app.tasks.reindex`
  - SQL 抽查 `vector_dims(embedding)=512` 且已发布文档 chunk 数 > 0。

## 阶段 3：LangChain RAG 接入

- [x] `backend/app/services/retrieval.py`：新增 `HelpFlowRetriever(BaseRetriever)` 与 `build_retriever()`（MultiQuery 可选，异常回退）。
- [x] 新建 `backend/app/services/rag.py`：`build_chat_model()`、`docs_to_context()`、`stream_answer()`、`answer_with_tools()`。
- [x] `backend/app/providers/chat.py`：新增 `LangChainChatProvider`，`build_chat_provider()` 默认走 LangChain，失败回退 httpx provider。
- [x] `backend/app/services/chat.py`：RAG 分支改走 LangChain provider；保留 citations/拒答/转人工逻辑。
- 验证：
  - `uv run python -c` 使用测试 workspace 检索“退款政策”，确认返回文档与分数。
  - `uv run pytest tests/test_chat.py` 通过（conftest 已禁用 LLM 与 MultiQuery）。

## 阶段 4：Agent 数据模型与工具

- [x] `backend/app/models/core.py` + `models/__init__.py`：新增 Customer/Order/AgentRun/AgentEvent/AgentApproval/EvalRun/EvalCase。
- [x] 新建迁移 `backend/alembic/versions/20261028_0008_agent_workbench.py`：建表、索引、唯一约束、级联删除。
- [x] 新建 `backend/app/agents/__init__.py`、`state.py`、`tools.py`：实现 8 个工具与退款资格规则。
- [x] `backend/app/seed.py`：新增 3 客户、5 订单、Agent 会话与审批样例；chunks 为空时自动 reindex。
- [x] 验证：迁移升级、seed 幂等、工具单测（`test_agent.py`）。

## 阶段 5：LangGraph 图、HITL 与 API

- [x] 新建 `backend/app/agents/graph.py`：plan/run_tool/request_refund/respond 四节点与条件边。
- [x] 新建 `backend/app/agents/runtime.py`：PostgresSaver（ConnectionPool）+ MemorySaver 兜底 + 懒编译。
- [x] 新建 `backend/app/agents/service.py`：`detect_agent_intent`、`create_run`、`astream_run`、`resume_run`。
- [x] 新建 `backend/app/schemas/agent.py`。
- [x] 新建 `backend/app/api/v1/agents.py`：runs 列表/详情/approve/reject；写审计日志。
- [x] `backend/app/api/v1/router.py` 注册 agents router。
- [x] `backend/app/services/chat.py`：新增 `MODE_AGENT`，SSE 转发 `agent_step`/`approval_required`，`done` 带 `agent_run_id`。
- [x] `backend/app/schemas/conversation.py` + `conversations.py`：详情返回 `agent_runs`。
- [x] 验证：
  - [x] curl 公开聊天“我的订单 HF-2026-0001 要退款”，SSE 出现 `agent_step` 与 `approval_required`。
  - [x] approve 后订单状态 `refunded`，会话新增消息，run `completed`。
  - [x] viewer 审批返回 403。

## 阶段 6：评测流水线

- [x] 新建 `backend/evals/__init__.py`。
- [x] 新建 `backend/evals/golden_qa.jsonl`：≥40 条（≥32 可答 + 8 拒答）。
- [x] 新建 `backend/app/services/evaluation.py`：检索命中、引用、拒答、忠实度、落库。
- [x] 新建 `backend/evals/run_eval.py`：CLI、控制台报告、`pass_rate < 0.8` 非 0 退出（`--no-gate` 可关）。
- [x] 新建 `backend/app/schemas/eval.py`、`backend/app/api/v1/evals.py`，注册路由。
- [x] `Makefile eval` 可用。
- [x] 验证：`make eval` 生成 run，指标完整，42 用例。

## 阶段 7：可观测（Langfuse，可选）

- [x] 新建 `backend/app/services/tracing.py`：`get_langchain_callbacks()`、`trace_agent_run()`，默认 no-op。
- [x] `backend/app/services/rag.py` 与 `agents/service.py` 接入回调（无 Key 时零开销）。
- [x] README 写清 `make infra-obs` 与端口/账号。
- [x] 验证：未启用时 pytest 不受影响；启用时 Langfuse UI 可见 trace（需镜像可拉取）。

## 阶段 8：前端工作台

- [x] `frontend/src/lib/api.ts`：新增 Agent/Eval 类型与请求函数；`ConversationDetail` 加 `agent_runs`。
- [x] `frontend/src/views/ConversationView.vue`：Agent 时间线面板 + 审批卡片（通过/拒绝 + 备注），操作后刷新。
- [x] `frontend/src/views/LogsView.vue`：新增“评测”tab（最新 run 指标 + 用例表 + 空状态）。
- [x] 现有登录测试账号、注册页、知识库上传、会话回复/备注/建单保持可用。
- [x] 验证：`npm run build` 通过；浏览器走通审批与评测页。

## 阶段 9：测试、文档与验收

- [x] `backend/tests/conftest.py`：hash embedding、禁用 MultiQuery/Agent LLM/Postgres checkpointer、monkeypatch LangChain provider 流式。
- [x] 新建 `backend/tests/test_agent.py`、`backend/tests/test_evals.py`；修复受影响旧测试。
- [x] `README.md`：架构图、RAG/Agent/HITL/Eval 说明、命令、指标、已知限制（Intel macOS/fastembed、MemorySaver 兜底）。
- [x] 全量验证：
  - [x] `cd backend && uv run alembic upgrade head`
  - [x] `make seed`
  - [x] `uv run ruff check app tests evals`
  - [x] `uv run pytest`（28 passed）
  - [x] `cd frontend && npm run build`
  - [x] `make eval`（42 用例，pass_rate 88.1%）
  - [x] 浏览器全链路冒烟（访客问答、退款审批、评测页）。
- [x] 输出验收摘要与评测指标到对话。

## 回滚策略

- 迁移逐条 downgrade（0008 → 0007 → 0006）；0007 downgrade 会清空 chunks，回滚后需 `make reindex`。
- Agent 功能可通过 `AGENT_ENABLED=false` 关闭，聊天自动退回纯 RAG。
- LangChain 生成失败自动回退 httpx provider；MultiQuery 失败回退基础检索。
- Langfuse 关闭即 no-op。
