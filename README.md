# HelpFlow

HelpFlow 是一个可本地运行的 AI 客服与工单 SaaS 参考实现，覆盖从知识入库、检索增强回答、业务 Agent、人工审批到质量评测的完整闭环。

技术栈：Vue 3 + TypeScript + Vite、FastAPI、SQLAlchemy 2、PostgreSQL 16 + pgvector、Redis、LangChain、LangGraph、本地 BGE 向量模型，可选自托管 Langfuse。

## 架构

```
                         ┌────────────────────────────┐
  访客聊天组件  ───────▶ │ FastAPI /api/v1            │
  管理后台 SPA  ───────▶ │  公开问答 · 会话 · 工单     │
                         │  知识库 · Agent · 评测      │
                         └──────────────┬─────────────┘
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              ▼                         ▼                          ▼
    ┌──────────────────┐     ┌──────────────────┐      ┌──────────────────┐
    │ LangChain RAG    │     │ LangGraph Agent  │      │ 评测流水线        │
    │ Retriever        │     │ plan → tool      │      │ golden_qa.jsonl  │
    │ MultiQuery(可选)  │     │      → approval  │      │ hit@4 / 引用 /    │
    │ LCEL 流式生成     │     │      → respond   │      │ 拒答 / 忠实度     │
    └────────┬─────────┘     └────────┬─────────┘      └────────┬─────────┘
             │                        │                         │
             └──────────┬─────────────┴─────────────┬───────────┘
                        ▼                           ▼
              PostgreSQL + pgvector          Langfuse（可选）
              知识切片 / 会话 / 工单          自托管，默认关闭
              Agent 事件 / 审批 / 评测
```

设计取舍：

- **检索与生成解耦**：检索产出带分数的文档，生成只依据引用作答，低置信度直接拒答，避免模型编造。
- **业务动作走工具**：查订单、建工单、提交退款都封装为工具，Agent 只负责规划与串行执行。
- **高风险动作强制人工审批**：退款通过 LangGraph `interrupt()` 暂停，审批后 `Command(resume=...)` 继续执行。
- **全链路可观测、可评测**：每次 Agent 运行都有事件时间线；黄金集评测可离线重复执行并入库。

## 已实现能力

- 邮箱密码登录、访问/刷新 JWT、工作空间成员与 admin / agent / viewer 角色权限
- 知识库：Markdown / 纯文本 / PDF 上传、中文感知切片、BGE 向量化、发布/撤回、检索测试
- 公开 AI 问答：匿名访问、SSE 流式回答、引用溯源、低置信度拒答、敏感词拦截、人工诉求识别
- RAG：`BaseRetriever` 封装 + 混合打分（0.65 向量余弦 + 0.35 词法重合）+ 可选 MultiQuery 改写
- Agent：`plan → run_tool / request_refund → respond` 状态图，8 个业务工具，规则兜底规划
- HITL：退款审批卡片、通过/拒绝、备注、审计日志；PostgresSaver 持久化，失败自动回退 MemorySaver
- 评测：40+ 条黄金集，hit@4、引用准确率、拒答准确率、忠实度、pass rate，结果入库并可 API 查询
- 会话中心：待人工队列、接入、回复、内部备注、关闭、从会话创建工单
- 工单闭环：优先级与状态流转、指派、跨工作空间隔离
- 看板与日志：会话/工单/AI 回答/拒答率/平均置信度、近 7 天趋势、知识缺口、AI 调用日志、审计日志
- 限流：访客问答与登录的固定窗口限流，Redis 不可用时降级为进程内限流
- 前端登录页支持测试账号一键填入，另有 `/register` 注册页

## 快速开始

前置条件：Node.js 22+、Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)、Docker Desktop。

PostgreSQL 映射到宿主机 `5433`（容器内 5432），避免与本机已有实例冲突。

```bash
cp .env.example .env
make infra-up                      # PostgreSQL + Redis
cd backend && uv sync --all-groups
cd ../frontend && npm install
make migrate                       # alembic upgrade head
make seed                          # 幂等写入工作空间、文档、客户、订单与 Agent 样例
```

分别在两个终端启动：

```bash
make api    # http://localhost:8000/docs
make web    # http://localhost:5173
```

首次运行会下载 `BAAI/bge-small-zh-v1.5`（fastembed 缓存）；离线环境可设置 `EMBEDDING_BACKEND=hash` 使用 512 维哈希兜底。

账号：`admin@helpflow.com`（管理员）、`agent@helpflow.com`（客服），密码均为 `helpflow-demo`。

## 关键配置

完整配置见 `.env.example`，以下为影响核心行为的项：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` / `OPENROUTER_API_KEY` | 空 | 至少配置一个，否则服务启动提示缺少模型密钥 |
| `EMBEDDING_BACKEND` | `auto` | `auto` 优先 BGE，失败降级哈希；`bge` 强制 BGE；`hash` 用于测试 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地向量模型，输出 512 维 |
| `RAG_MULTI_QUERY_ENABLED` | `true` | 是否用 LLM 改写查询，异常自动回退基础检索 |
| `RAG_CANDIDATE_LIMIT` | `24` | 混合检索候选池大小 |
| `CHAT_CONFIDENCE_THRESHOLD` | `0.4` | 低于该分数直接拒答 |
| `AGENT_ENABLED` | `true` | 关闭后所有提问退回纯 RAG |
| `AGENT_USE_LLM` | `true` | 关闭后使用规则规划 |
| `AGENT_MAX_STEPS` | `4` | 单次运行最多工具步数 |
| `AGENT_CHECKPOINT_BACKEND` | `postgres` | 审批状态持久化；失败回退内存 |
| `LANGFUSE_ENABLED` | `false` | 开启后向自托管 Langfuse 上报 |
| `EVAL_JUDGE_ENABLED` | `false` | 评测默认使用启发式忠实度，不调用外部模型 |

## 核心流程

### 1. 检索增强回答（RAG）

1. 已发布文档按中文分隔符（`\n\n`、`\n`、`。`、`；`、`，`）切成 180 字、30 重叠的切片。
2. 切片用本地 BGE 向量化，写入 `knowledge_chunks.embedding vector(512)` 并建立 HNSW 索引。
3. 查询时 `HelpFlowRetriever` 召回候选池，按 `0.65 × 余弦 + 0.35 × 词法重合` 重排。
4. 可选 `MultiQueryRetriever` 用 LLM 生成多个查询，失败时静默回退单查询。
5. `docs_to_context()` 过滤低于阈值或明显弱于首条的文档，生成引用列表。
6. LCEL 链 `ChatPromptTemplate | ChatOpenAI | StrOutputParser` 流式输出，只依据参考资料作答并标注 `[编号]`。

SSE 事件：`meta` → 多条 `delta` → `citations` →（可选 `handoff`）→ `done`。

### 2. 业务 Agent 与人工审批

业务意图（退款、订单、投诉/工单、发票账单）进入 LangGraph Agent，其余问题仍走快速 RAG。

```
plan ──▶ run_tool ──▶ plan ──▶ ... ──▶ respond
  └────▶ request_refund ──▶ interrupt(等待审批) ──▶ respond
```

- `plan`：优先让 LLM 输出 JSON 计划，失败或无凭证时用正则规则；退款计划强制先查资格。
- `run_tool`：按顺序执行工具并累积上下文、引用与耗时。
- `request_refund`：调用 `interrupt()` 暂停，生成 `AgentApproval(pending)`。
- `respond`：把工具结果与知识摘录交给 LLM 综合回答，失败时用确定性模板兜底。

工具：`search_knowledge`、`get_customer`、`list_orders`、`get_order`、`check_refund_eligibility`、`create_ticket`、`request_refund`、`handoff_to_human`。

退款规则：订单状态须为 `paid/shipped/delivered`，下单或签收不超过 7 天，AI 使用量低于 100 次；任一不满足直接给结论，不进入审批。

SSE 额外事件：`agent_step`（工具调用/结果）、`approval_required`（审批卡片）；`done` 带 `agent_run_id` 与 `agent_status`。

审批接口：`POST /api/v1/agents/runs/{id}/approve|reject`，仅 admin/agent；通过后订单置为 `refunded`、写入会话消息与审计日志。

### 3. 评测流水线

`backend/evals/golden_qa.jsonl` 包含 40+ 条用例（可答 + 应拒答），字段：

```json
{"id":"q01","question":"专业版每月多少钱？","expected_documents":["价格方案与计费方式"],"must_include":["899"],"should_refuse":false}
```

`run_evaluation()` 对每条用例执行检索、预测模式并计算：

- `hit_rate`：期望文档是否出现在前 4 条召回中
- `citation_accuracy`：引用标题与期望文档是否有交集
- `refusal_accuracy`：应拒答用例是否真的拒答
- `faithfulness`：启发式校验 `must_include` 是否出现在上下文中且引用非空
- `pass_rate`：用例通过率；`avg_latency_ms`：平均检索耗时

结果写入 `eval_runs` / `eval_cases`，可通过 API 或前端「质量评测」标签查看。

```bash
make eval
# 或
cd backend && uv run python -m evals.run_eval --workspace helpflow --limit 20 --no-gate
```

`pass_rate < 0.8` 时 CLI 以非 0 退出，可直接接入 CI；`--no-gate` 仅观察不阻断。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/public/workspaces/{slug}` | 公开工作空间配置、欢迎语、预置问题 |
| `POST` | `/api/v1/public/workspaces/{slug}/chat` | 匿名问答，`text/event-stream` |
| `GET` | `/api/v1/public/workspaces/{slug}/conversations/{id}/messages` | 访客轮询人工回复 |
| `GET` | `/api/v1/conversations` | 会话列表，支持状态、负责人、关键词筛选 |
| `GET` | `/api/v1/conversations/{id}` | 会话详情、消息与最近 Agent 运行轨迹 |
| `POST` | `/api/v1/conversations/{id}/join` | 接入会话 |
| `POST` | `/api/v1/conversations/{id}/messages` | 回复访客；`internal=true` 为内部备注 |
| `POST` | `/api/v1/conversations/{id}/close` | 关闭会话 |
| `GET` / `POST` | `/api/v1/tickets` | 工单列表 / 创建工单 |
| `GET` / `PATCH` | `/api/v1/tickets/{id}` | 工单详情 / 指派、优先级与状态流转 |
| `GET` | `/api/v1/agents/runs` | Agent 运行列表 |
| `GET` | `/api/v1/agents/runs/{id}` | 运行详情（事件时间线 + 审批） |
| `POST` | `/api/v1/agents/runs/{id}/approve` | 通过退款审批 |
| `POST` | `/api/v1/agents/runs/{id}/reject` | 拒绝退款审批 |
| `GET` | `/api/v1/evals/runs` | 评测运行列表 |
| `GET` | `/api/v1/evals/runs/{id}` | 评测详情与逐条用例 |
| `GET` | `/api/v1/evals/summary` | 最近一次指标与历史趋势 |
| `GET` | `/api/v1/dashboard/summary` | 看板汇总 |
| `GET` | `/api/v1/ai-logs` / `/api/v1/audit-logs` | AI 调用日志 / 审计日志（后者仅管理员） |
| `GET` | `/api/v1/health` | 数据库健康检查 |

知识库接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` / `POST` | `/api/v1/knowledge/documents` | 文档列表 / 新建 FAQ |
| `POST` | `/api/v1/knowledge/documents/upload` | 上传 `.md` / `.txt` / `.pdf` |
| `GET` | `/api/v1/knowledge/documents/{id}` | 文档详情与正文 |
| `GET` | `/api/v1/knowledge/documents/{id}/chunks` | 查看切片 |
| `PATCH` | `/api/v1/knowledge/documents/{id}` | 修改标题、分类与内容 |
| `POST` | `/api/v1/knowledge/documents/{id}/publish` | 发布或重新发布 |
| `POST` | `/api/v1/knowledge/documents/{id}/archive` | 撤回后不再参与检索 |
| `POST` | `/api/v1/knowledge/test-query` | 检索测试（仅命中已发布文档） |

## 可观测（Langfuse，可选）

默认关闭，不引入任何外部依赖。需要时：

```bash
make infra-obs        # Langfuse + ClickHouse + MinIO，端口 3030
```

在 `.env` 中设置：

```bash
LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://localhost:3030
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

当前接入点：LCEL 生成链的 `callbacks`，以及每次 Agent 运行的摘要事件。任何上报异常都会被吞掉，不影响问答与审批。

## 常用命令

```bash
make infra-up     # 启动 PostgreSQL 和 Redis
make infra-obs    # 启动可选观测栈（Langfuse）
make infra-down   # 停止本地依赖
make migrate      # 数据库迁移
make seed         # 幂等写入基础数据
make reindex      # 重建已发布文档切片与向量
make eval         # 运行黄金集评测
make test         # 后端测试
```

## 本地数据

`make seed` 写入 17 篇已发布帮助文档，以及：

- 3 个客户与 5 个订单（可退款、超窗口、AI 超限、已退款）
- 8 个带完整对话的业务会话、3 张不同状态的工单
- 2 条 Agent 轨迹：一条已完成退款、一条等待审批
- AI 调用日志与审计日志

数据以 `metadata.seed` 标记，重复执行不会重复插入。发布文档缺少切片时，`seed` 会自动调用重建任务。

## 走查脚本

前提：已完成初始化，`make api` 与 `make web` 均在运行。

1. **知识回答**：打开 `http://localhost:5173`，问「专业版多少钱？」。确认流式输出、引用可展开且来自「价格方案与计费方式」。
2. **拒答**：问「你们有线下门店吗？」。确认明确说明知识库无可靠资料并建议转人工，不编造。
3. **Agent 与审批**：新开会话问「我的订单 HF-2026-0005 要退款」。确认出现工具时间线（资格检查）与审批提示。
4. **人工审批**：登录后台进入会话中心，打开该会话，在「Agent 工作台」查看事件与审批卡片，填写备注并通过审批。确认会话出现退款完成消息、订单状态变为已退款。
5. **评测**：执行 `make eval`，在「质量日志 → 质量评测」查看 pass_rate、hit_rate、引用准确率、拒答准确率与逐条用例。

## 已知限制

- **Intel macOS 向量依赖**：torch 无对应 wheel，改用 `fastembed 0.6.1` + `onnxruntime 1.18.1` 承载同一 BGE 模型。首次使用需联网下载模型；离线时 `EMBEDDING_BACKEND=hash` 仍可跑通全流程，但检索质量下降。
- **审批状态持久化**：`AGENT_CHECKPOINT_BACKEND=postgres` 时审批可跨进程恢复；PostgresSaver 不可用会回退进程内存储，重启后未决审批丢失。
- **评测忠实度**：默认启发式（关键词 + 引用存在性），不调用外部裁判模型；`EVAL_JUDGE_ENABLED=true` 预留 LLM 裁判扩展点。
- **Langfuse**：镜像拉取失败不影响主流程，观测默认 no-op。
- **限流**：Redis 不可用时降级为进程内固定窗口，多实例部署需恢复 Redis。
