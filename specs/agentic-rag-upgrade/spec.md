# HelpFlow Agentic RAG 升级规格（Spec）

## 1. 背景与目标

HelpFlow 目前具备：知识库上传/切片/发布、pgvector 手写余弦检索、SSE 流式问答、引用溯源、会话中心、工单、看板与日志。当前实现更接近“可运行示例”，本轮要把以下能力做成可演示、可解释、可运营的闭环：

1. **真实语义向量**：本地 BGE 中文模型替换哈希向量。
2. **LangChain RAG**：真实向量检索 + MultiQuery 查询改写 + LCEL 生成链，保持 workspace 隔离与引用映射。
3. **LangGraph Agent**：业务意图路由、工具调用、退款人工审批（HITL）、运行轨迹可追溯。
4. **评测流水线**：≥40 条黄金集，离线可跑，产出 hit@k、引用准确率、拒答正确率、忠实度。
5. **可观测**：可选 Langfuse 自托管，默认 no-op 不阻塞主流程。
6. **前端工作台**：审批卡片 + 工具调用时间线 + 质量评测页，且不出现“演示/demo”字样。

非目标（本轮不做）：结构化分诊、知识缺口自动草稿、多专家协同、真实支付/退款对接、生产级鉴权改造。

## 2. 已确定的决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| Embedding | `fastembed 0.6.1` + `BAAI/bge-small-zh-v1.5`（512 维） | 本机为 Intel macOS，`torch` 无可用 wheel；fastembed 与用户选定的 BGE 模型一致，已验证可下载推理 |
| 向量维度 | 512 | 与 BGE small zh 一致；哈希兜底也输出 512 维，避免迁移后维度不一致 |
| RAG 检索 | 自定义 `BaseRetriever` 包住现有 pgvector SQL + `MultiQueryRetriever` | 保留 `workspace_id`/`published` 过滤与混合打分，不被 `langchain-postgres` 表结构绑死 |
| 文本切片 | `RecursiveCharacterTextSplitter`，180/30，中文分隔符 | LangChain 原生、可解释；保留 `split_text()` 对外签名 |
| 生成 | `ChatOpenAI` + `ChatPromptTemplate` + `StrOutputParser`，`astream` | 与现有 SSE 兼容；OpenRouter/OpenAI-compatible 共用 |
| Agent | LangGraph `StateGraph`（plan → tool → respond），PostgresSaver | 状态可持久化；审批可在重启后恢复；MemorySaver 兜底 |
| HITL | `interrupt()` + `Command(resume=...)` | LangGraph 原生人工审批语义，而非自造暂停逻辑 |
| 可观测 | Langfuse 自托管，`profiles: [observability]` | 默认 `make infra-up` 不受影响；无 Key 时 no-op |
| Embedding 不可用时 | 自动降级 512 维哈希向量并告警 | 离线测试/无模型环境仍可跑通，不伪造“真实向量”结论 |

## 3. 总体架构

```
访客 ──POST /public/.../chat──> ChatService
                                   ├─ 风控 / 转人工 / 等待人工（规则）
                                   ├─ 业务意图? ──是──> AgentService(LangGraph)
                                   │                        ├─ search_knowledge ──> HelpFlowRetriever ──> pgvector
                                   │                        ├─ get_customer/list_orders/get_order
                                   │                        ├─ check_refund_eligibility
                                   │                        ├─ create_ticket / handoff_to_human
                                   │                        └─ request_refund ──interrupt──> 审批
                                   └─ 否 ──> RAG 问答（LangChain LCEL 流式）
后台 ──GET /conversations/{id}──> 会话详情（含 agent_runs / events / approvals）
     ──POST /agents/runs/{id}/approve|reject──> 恢复图执行
     ──GET /evals/*──> 评测结果页
```

## 4. 配置与基础设施

### 4.1 `backend/app/core/config.py` 新增

```python
embedding_backend: str = "auto"          # auto | bge | hash
embedding_model: str = "BAAI/bge-small-zh-v1.5"
embedding_dimensions: int = 512
embedding_batch_size: int = 32
embedding_cache_dir: str = ""
rag_multi_query_enabled: bool = True
rag_multi_query_count: int = 3
rag_candidate_limit: int = 24
agent_enabled: bool = True
agent_use_llm: bool = True
agent_max_steps: int = 4
agent_checkpoint_backend: str = "postgres"   # postgres | memory
langfuse_enabled: bool = False
langfuse_public_key: str = ""
langfuse_secret_key: str = ""
langfuse_host: str = "http://localhost:3030"
eval_judge_enabled: bool = False
```

新增属性：

- `langgraph_database_url`：把 `postgresql+psycopg://` 转为 `postgresql://`。
- `psycopg_database_url` 可复用同一属性。

### 4.2 `.env.example`

追加 `EMBEDDING_*`、`RAG_*`、`AGENT_*`、`LANGFUSE_*`、`EVAL_*` 注释块，默认值与上表一致。

### 4.3 `docker-compose.yml`

新增 `observability` profile：

- `langfuse-db`：`postgres:16-alpine`，独立库 `langfuse`。
- `clickhouse`：`clickhouse/clickhouse-server:24-alpine`。
- `minio`：`minio/minio`，创建 `langfuse` bucket（可用 init 容器或 `mc`）。
- `langfuse`：`langfuse/langfuse:3`，暴露 `3030:3000`，依赖上述服务。

默认不启动；`make infra-obs` 启动。主流程未配置 Key 时 `tracing.py` 返回空回调。

### 4.4 `Makefile`

新增：

```
reindex: cd backend && uv run python -m app.tasks.reindex
eval:    cd backend && uv run python -m evals.run_eval --workspace helpflow
infra-obs: docker compose --profile observability up -d
```

## 5. Embedding 与切片

### 5.1 `backend/app/providers/embeddings.py`

保留 `tokenize()` 供混合检索复用。新增：

- `EmbeddingProvider`（Protocol）：`name`、`dimensions`、`embed(text)->list[float]`、`embed_many(texts)->list[list[float]]`。
- `BGEEmbeddingProvider`：
  - 懒加载 `fastembed.TextEmbedding(model_name=settings.embedding_model, cache_dir=...)`。
  - 输出转 `list[float]` 并做 L2 归一化。
  - 批量走 `model.embed(texts, batch_size=...)`。
- `LocalHashEmbeddingProvider`：维度改为 `settings.embedding_dimensions`（512）。
- `LazyEmbeddingProvider` 单例 `embedding_provider`：
  - `auto`：优先 BGE；初始化异常则降级 hash，`logger.warning` 一次。
  - `bge`：强制 BGE，失败时抛错（用于生产自检）。
  - `hash`：测试/离线。
  - 懒初始化，避免 import 时下载模型。

### 5.2 `backend/app/services/documents.py`

`split_text()` 改为调用 `RecursiveCharacterTextSplitter`：

```python
splitter = RecursiveCharacterTextSplitter(
    chunk_size=chunk_size,
    chunk_overlap=overlap,
    separators=["\n\n", "\n", "。", "；", "，", " ", ""],
)
```

保持空内容报错行为。

### 5.3 `backend/app/tasks/knowledge.py`

- `embedding_provider.embed_many(chunks)` 一次批量嵌入，避免逐条模型调用。
- 其余状态机不变。

### 5.4 `backend/app/tasks/reindex.py`（新增）

- `reindex_documents(workspace_id: UUID | None = None)`：删除并重建所有 `published/ready` 文档的 chunks。
- `if __name__ == "__main__"` 支持 `python -m app.tasks.reindex`，打印处理数量。
- 供迁移后与 `make reindex` 使用。

### 5.5 迁移 `20261028_0007_bge_embeddings.py`

- `DELETE FROM knowledge_chunks`。
- `DROP INDEX ix_knowledge_chunks_embedding_cosine`。
- `ALTER TABLE knowledge_chunks DROP COLUMN embedding`，再 `ADD COLUMN embedding vector(512) NOT NULL`。
- 重建 HNSW 索引（`vector_cosine_ops`, `m=16`, `ef_construction=64`）。
- downgrade 反向恢复 `vector(256)`（同样清空表）。
- 迁移后由 `make seed`/`make reindex` 重嵌入。

## 6. LangChain RAG

### 6.1 `backend/app/services/retrieval.py`

- 保留 `RetrievedChunk`、`retrieve_published_chunks`（混合打分：0.65 向量 + 0.35 词法）。
- 新增 `HelpFlowRetriever(BaseRetriever)`：
  - 字段：`db: Session`、`workspace_id: UUID`、`limit: int`。
  - `_get_relevant_documents(query)`：调用混合检索，返回 `Document`，metadata 含：
    `document_id, document_title, chunk_id, score, vector_score, lexical_score, rank`。
- 新增 `build_retriever(db, workspace_id, limit)`：
  - 默认返回 `HelpFlowRetriever`。
  - 若 `rag_multi_query_enabled` 且有 LLM 凭证，用 `MultiQueryRetriever.from_llm(..., include_original=True)` 包装。
  - 构造失败记录 warning 并回退基础 retriever。

### 6.2 `backend/app/services/rag.py`（新增）

- `build_chat_model(temperature=0.2, streaming=True) -> ChatOpenAI`：复用 `_llm_credentials()`，无凭证抛 `ProviderError`。
- `format_context(items)` / `docs_to_context(docs)`：按 `score` 去重取前 3，生成 `ContextItem` + citations。
- `stream_answer(question, context, history) -> AsyncIterator[str]`：
  - LCEL：`ChatPromptTemplate | ChatOpenAI | StrOutputParser`。
  - system prompt 沿用现有 5 条约束；`MessagesPlaceholder("history")`。
  - `.astream` 输出文本片段。
- `answer_with_tools(question, observations, history) -> str`：Agent `respond` 节点用；无 LLM 时返回确定性模板。

### 6.3 `backend/app/providers/chat.py`

- 新增 `LangChainChatProvider`：`name`/`model` 与凭证一致，`stream_answer` 调 `services.rag.stream_answer`。
- `build_chat_provider()` 默认返回 `LangChainChatProvider`；构造失败回退现有 `OpenAICompatibleChatProvider`。
- 保留 `OpenAICompatibleChatProvider` 作为兜底与兼容测试。
- 不重新引入任何 Mock provider。

## 7. LangGraph Agent

### 7.1 数据模型（`backend/app/models/core.py` + `models/__init__.py`）

- `Customer`：id, workspace_id, name, email, phone, company, metadata, timestamps；`(workspace_id,email)` 唯一。
- `Order`：id, workspace_id, customer_id, order_no, product_name, plan, amount(Float), currency, status(`paid|shipped|delivered|refunded|cancelled`), purchased_at, delivered_at, refunded_at, metadata(JSONB，含 `ai_usage`), timestamps；`(workspace_id,order_no)` 唯一。
- `AgentRun`：id, workspace_id, conversation_id(FK), thread_id(unique), question, intent, status(`running|waiting_approval|completed|rejected|failed`), answer, citations(JSONB), error, latency_ms, created_at, updated_at, finished_at。
- `AgentEvent`：id, run_id(FK cascade), workspace_id, seq, type(`tool_call|tool_result|approval_required|approval_decided|error`), name, status, summary, payload(JSONB), created_at；`(run_id,seq)` 唯一。
- `AgentApproval`：id, run_id(FK cascade), workspace_id, tool_name, arguments(JSONB), status(`pending|approved|rejected`), note, requested_at, decided_by_user_id(FK users, SET NULL), decided_at。
- `EvalRun`：id, workspace_id, name, status, total_cases, passed_cases, metrics(JSONB), created_by_user_id, started_at, finished_at。
- `EvalCase`：id, run_id(FK cascade), workspace_id, question, expected_documents(JSONB), cited_documents(JSONB), predicted_mode, expected_mode, passed(Boolean), metrics(JSONB), latency_ms, error, created_at。

### 7.2 迁移 `20261028_0008_agent_workbench.py`

创建上述 7 张表、索引与唯一约束；`agent_events`/`agent_approvals` 对 `agent_runs.id` 级联删除。downgrade 逆序删除。

### 7.3 `backend/app/agents/state.py`

`AgentState(TypedDict, total=False)`：

```
workspace_id, conversation_id, visitor_id, question, history,
plan: list[ToolCall], plan_index: int, steps: list[dict],
context: list[dict], citations: list[dict], answer: str,
intent: str, outcome: str, error: str
```

### 7.4 `backend/app/agents/tools.py`

工具签名统一 `(db, workspace_id, **kwargs) -> dict`，返回 `summary` + 结构化数据：

- `search_knowledge(question, limit)` → docs/citations/confidence。
- `get_customer(email=None, visitor_id=None)`。
- `list_orders(customer_id=None, email=None)`。
- `get_order(order_no)`。
- `check_refund_eligibility(order_no)`：`status ∈ delivered/paid` 且 `delivered_at` 在 7 天内且 `metadata.ai_usage < 100` 且未退款。
- `create_ticket(title, description, priority)`：写 `Ticket`，关联 conversation。
- `request_refund(order_no, reason)`：仅在审批通过后调用；置 `refunded`、写 `refunded_at`、写系统消息。
- `handoff_to_human(reason)`：会话置 `waiting_human`。

### 7.5 `backend/app/agents/graph.py`

节点：

1. `plan`：首轮生成计划（LLM function-calling；`agent_use_llm=false` 或失败时用规则计划）。规则：
   - 含订单号 + 退款 → `[check_refund_eligibility, request_refund]`
   - 仅退款无订单号 → `[search_knowledge("退款政策")]`，回答中要求补充订单号
   - 含“订单/物流/发货” → `[list_orders]` 或 `[get_order]`
   - 含“工单” → `[create_ticket]`
   - 其余 → `[search_knowledge(question)]`
   - 每次最多 1 个只读工具 + 1 个写操作，`agent_max_steps` 兜底。
2. `run_tool`：执行当前只读工具，追加 `steps`、`context`、`citations`。
3. `request_refund`：调用 `interrupt({...})`；resume 值 `{approved, note, decided_by}`；通过则执行退款，拒绝则记录结果。
4. `respond`：根据 steps/context 生成答案（LLM 优先，规则模板兜底），写 `answer`。

边：

```
plan -> run_tool | request_refund | respond
run_tool -> plan
request_refund -> respond
respond -> END
```

### 7.6 `backend/app/agents/runtime.py`

- `get_graph()` 懒编译。
- Checkpointer：
  - `agent_checkpoint_backend=postgres`：`ConnectionPool(settings.langgraph_database_url, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0})` + `PostgresSaver(pool)` + `setup()`。
  - 失败：warning + `MemorySaver`。
- `thread_config(run.thread_id)`。

### 7.7 `backend/app/agents/service.py`

- `detect_agent_intent(question) -> str | None`：业务关键词集合（订单/物流/发货/退款/退货/工单/投诉/发票/账户）。
- `create_run(db, workspace_id, conversation, question)`：写 `AgentRun`，thread_id=run.id。
- `async def astream_run(run_id)`：`graph.astream(..., stream_mode="updates")`：
  - `run_tool` 更新 → 写 `AgentEvent`，yield `step`。
  - `__interrupt__` → 写 `AgentApproval`(pending) + `AgentEvent`，run 置 `waiting_approval`，yield `approval_required`。
  - `respond` 更新 → yield `delta`（分片）。
  - 完成 → 更新 run、写 assistant `Message`、写 `AiCallLog(provider="langgraph", mode="agent")`。
- `resume_run(db, run_id, approved, note, decided_by)`：校验 pending → 更新审批 → `graph.astream(Command(resume=...))` → 完成/拒绝落库。
- 失败统一 `status=failed` + error，不抛到 API 外。

### 7.8 `backend/app/services/chat.py`

- 新增 `MODE_AGENT = "agent"`。
- `prepare_chat`：通过风控/转人工/等待人工后，若 `detect_agent_intent(question)` 命中且 `agent_enabled` → `mode=agent`；否则走原 RAG。
- `stream_chat` 的 agent 分支：
  - `meta` 带 `agent_run_id`。
  - 转发 `agent_step` / `approval_required` 事件。
  - 文本以 `delta` 输出；`citations` 来自 run。
  - `done` 带 `agent_run_id`、`status`。
- 原 mock 固定文案仅保留拒答/转人工等规则分支；不新增 mock provider。

### 7.9 API

`backend/app/api/v1/agents.py`：

- `GET /agents/runs?status=&conversation_id=&limit=`
- `GET /agents/runs/{run_id}`（含 events/approvals）
- `POST /agents/runs/{run_id}/approve`（body `{note?}`，角色 admin/agent）
- `POST /agents/runs/{run_id}/reject`（同上）
- 审批写 `AuditLog`：`agent.approval.approve|reject`。

`conversations.py`：详情响应增加 `agent_runs`（最近 5 条，含 events/approvals）。

### 7.10 Schema

`app/schemas/agent.py`：`AgentEventResponse`、`AgentApprovalResponse`、`AgentRunSummary`、`AgentRunDetail`、`AgentDecisionRequest`。

## 8. 评测流水线

### 8.1 黄金集 `backend/evals/golden_qa.jsonl`

≥40 条，字段：

```json
{"id":"q01","question":"专业版每月多少钱？","expected_documents":["价格方案与计费方式"],"must_include":["899"],"should_refuse":false}
```

覆盖：价格/试用/退款/发票/权限/安全/限流/导出/Webhook/SLA/工单/钉钉/私有化/接入/联系人/删除账号/备份等约 32 条 + 8 条知识库外问题（应拒答）。

### 8.2 `backend/app/services/evaluation.py`

- `run_evaluation(db, workspace, name, judge)`：
  - 逐条：`retrieve_published_chunks` → 预测 mode（answer/refused）。
  - `hit@4`：期望文档出现在前 4。
  - `citation_accuracy`：引用文档标题与期望有交集。
  - `refusal_accuracy`：应拒答与实际拒答一致。
  - `faithfulness`：LLM judge 可用时打分；否则用“引用非空 + must_include 命中”启发式，并在 metrics 标注 `judge="heuristic"`。
  - 写 `EvalRun`/`EvalCase`。
- 指标聚合：`hit_rate, citation_accuracy, refusal_accuracy, faithfulness, pass_rate, avg_latency_ms`。

### 8.3 `backend/evals/run_eval.py`

CLI：`--workspace helpflow`、`--name baseline`、`--limit`、`--judge`；打印逐条失败摘要与聚合指标；退出码非 0 当 `pass_rate < 0.8`（可 `--no-gate` 关闭）。

### 8.4 API `backend/app/api/v1/evals.py`

- `GET /evals/runs?limit=`
- `GET /evals/runs/{run_id}`（含 cases）
- `GET /evals/summary`（最近一次 + 历史趋势）

## 9. 前端

### 9.1 `frontend/src/lib/api.ts`

新增类型与函数：

- `AgentEvent`, `AgentApproval`, `AgentRun`, `AgentRunDetail`
- `approveAgentRun(runId, note?)`, `rejectAgentRun(runId, note?)`
- `fetchAgentRuns(params)`, `fetchAgentRun(id)`
- `EvalRun`, `EvalCase`, `fetchEvalRuns()`, `fetchEvalRun(id)`, `fetchEvalSummary()`
- `ConversationDetail` 增加 `agent_runs`。

### 9.2 `frontend/src/views/ConversationView.vue`

- 会话详情右侧/消息上方新增“Agent 工作台”折叠面板：
  - 工具时间线（tool_call/tool_result，名称、状态、摘要、耗时）。
  - 审批卡片：pending 时展示订单号、金额、理由，提供“通过/拒绝”+ 可选备注。
  - 审批后刷新详情，展示审批结果与执行摘要。
- 保持现有队列、回复、内部备注、建单功能不回退。

### 9.3 `frontend/src/views/LogsView.vue`

- 新增“评测”tab：
  - 最近运行卡片：名称、时间、pass_rate、hit_rate、citation_accuracy、refusal_accuracy、faithfulness。
  - 用例表格：问题、期望文档、命中、引用、是否拒答、耗时。
  - 空状态提示运行 `make eval`。

### 9.4 `frontend/src/views/DashboardView.vue`（可选，低优先）

- 增加“最近评测 pass_rate / 拒答率”小卡片；若时间不足可略过，不阻塞验收。

## 10. Seed 数据

`backend/app/seed.py` 追加：

- 客户 3 个、订单 5 个（含可退款/不可退款/已退款），绑定 `workspace_id`。
- 一个已完成 Agent 会话（工具调用 + 审批通过轨迹）。
- 一个 `waiting_approval` 的退款会话（用于前端演示审批卡片，措辞不使用“演示”）。
- 幂等键 `metadata.seed = "agent_phase7"`。
- 若发布文档没有 chunks，调用 `reindex_documents(workspace.id)`（兼容 0007 迁移后）。

## 11. 测试与可观测

### 11.1 `backend/tests/conftest.py`

- `settings.embedding_backend = "hash"`。
- `settings.rag_multi_query_enabled = False`。
- `settings.agent_use_llm = False`。
- `settings.agent_checkpoint_backend = "memory"`（避免测试写 checkpoint 表）。
- monkeypatch `LangChainChatProvider.stream_answer` 为确定性假流。
- 保持 `test_chat.py` 现有断言不回退。

### 11.2 新增测试

`tests/test_agent.py`：

- 业务意图 → `mode=agent`，含工具事件。
- 退款 → `waiting_approval`，审批通过后订单 `refunded`，拒绝后不变。
- 无权角色（viewer）审批 403。

`tests/test_evals.py`：

- 评测 runner 能写入 `EvalRun`/`EvalCase`，指标键完整（用例数可裁剪）。

### 11.3 `backend/app/services/tracing.py`

- `get_langchain_callbacks()`：`langfuse_enabled` 且 Key 存在时返回 `[CallbackHandler()]`，任何异常返回 `[]`。
- `trace_agent_run(...)`：可选记录 trace；失败静默。
- 不引入阻塞启动的外部依赖。

## 12. 验收标准（Definition of Done）

1. `cd backend && uv run alembic upgrade head` 成功，0007/0008 生效。
2. `make seed` 成功，22+ 文档全部以 BGE 512 维重建；重复执行不重复插入。
3. `make eval` 产出 `EvalRun`，40+ 用例，`pass_rate ≥ 0.8`；控制台打印指标。
4. `uv run ruff check app tests evals` 通过。
5. `uv run pytest` 全绿且**不访问真实模型/网络**。
6. `cd frontend && npm run build` 通过。
7. 浏览器全链路：访客提问（价格）→ 流式引用回答；提问“我的订单 HF-2026-0001 要退款” → 工具时间线 → 审批卡片；后台通过审批 → 会话出现退款完成消息；日志页评测 tab 可见指标。
8. 页面与文案不出现“演示/demo”；既有登录测试账号、注册页、知识库上传不回退。

## 13. 风险与回退

- **Intel macOS wheel**：已用 fastembed + onnxruntime 1.18.1 解决；若换机种仍失败，`auto` 降级 512 维哈希并在日志明确标注，不静默伪装。
- **LangGraph checkpointer**：PostgresSaver 初始化失败时回退 MemorySaver；审批在单进程内可用，重启恢复能力在 README 中注明。
- **MultiQuery LLM 调用**：测试与 `agent_use_llm=false`/无凭证时禁用；运行异常回退基础检索。
- **Langfuse 镜像拉取失败**：observability profile 默认不启动；应用 no-op，不影响验收。
- **BGE 首次下载**：模型已在本机缓存；新环境需联网，README 说明离线时使用 `EMBEDDING_BACKEND=hash`。

## 14. 需要确认

请确认是否按本规格实施。确认后我将按 `tasks.md` 的顺序执行，并在每个阶段完成后跑迁移、ruff、pytest、前端 build 与关键接口冒烟。
