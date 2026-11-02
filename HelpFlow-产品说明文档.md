# HelpFlow｜AI 智能客服与工单管理系统

## 1. 文档目的

本文档定义 HelpFlow 的产品范围、交互、数据与技术边界，供后续使用 AI 编程工具进行分阶段开发。它的目标不是做一个通用聊天机器人，而是做一套可部署、可嵌入网站、可由团队日常使用的轻量级客服系统。

**一句话定位：** 企业在自己网站上接入一个 AI 客服；AI 基于企业已审核的知识回答常见问题，遇到不确定、敏感或用户要求人工的问题，自动转为人工会话或工单。

**首版核心原则：** 回答有依据、转人工不丢上下文、后台可管理、演示可闭环。

---

## 2. 目标用户与使用场景

| 角色 | 核心诉求 | 典型动作 |
| --- | --- | --- |
| 网站访客 / 客户 | 快速得到可靠答案，必要时找到真人 | 提问、查看引用、留下联系方式、要求人工协助 |
| 客服专员 | 集中处理 AI 无法解决的问题 | 查看待接入会话、回复客户、创建或处理工单 |
| 管理员 | 管理知识、客服成员与服务质量 | 上传文档、发布知识、配置转人工规则、查看数据 |

首版使用一个虚拟 SaaS 公司作为演示租户，预置产品介绍、价格、试用、退款和技术接入等帮助文档。招聘方不需要注册，也能在官网 Demo 中体验完整提问和转人工流程。

---

## 3. 产品范围

### 3.1 MVP 必做

1. 邮箱密码登录、JWT 鉴权与角色权限。
2. 多租户工作空间：一个公司/团队对应一个工作空间。
3. 知识库：上传 Markdown、PDF、纯文本；解析、分段、索引、发布与停用。
4. 网站嵌入式聊天组件：匿名访客可发起会话，支持流式回复。
5. 基于知识库的 AI 问答：答案展示引用来源；没有可靠依据时不编造。
6. 转人工：访客主动要求人工，或 AI 判断需要人工时，进入待处理队列。
7. 客服后台：会话列表、会话详情、人工回复、会话状态。
8. 工单：从会话一键创建工单，支持指派、优先级、状态和处理记录。
9. 简单运营看板：会话量、AI 解决率、人工接入率、高频问题、待处理工单。
10. Docker Compose 部署、Nginx 反向代理和 OpenAPI 文档。

### 3.2 首版明确不做

- 真正的支付、短信、呼叫中心、微信/钉钉渠道接入。
- 多语言自动翻译、语音客服、复杂 SLA 计费。
- 无限制的工作流编排或“万能 Agent”。
- 文档 OCR、Excel 解析、图片识别；可作为后续扩展。

这些功能可在界面中设计为“即将支持”或 Provider 接口，但不应阻塞 MVP。

---

## 4. 用户流程

### 4.1 访客咨询流程

```text
访客打开企业网站
  → 点击右下角 HelpFlow 聊天组件
  → 输入问题
  → AI 检索已发布知识库
  → 有足够证据：流式回答 + 文档引用
  → 证据不足 / 敏感问题 / 访客要求人工：说明原因并收集联系方式
  → 创建待人工会话
  → 客服专员接入并继续在原会话中回复
  → 问题解决：访客评价，或创建工单继续跟进
```

### 4.2 管理员配置流程

```text
管理员登录
  → 创建或进入工作空间
  → 上传帮助文档
  → 等待解析与索引完成
  → 预览切片 / 修改标题和分类
  → 发布至客服知识库
  → 复制嵌入代码到企业网站
  → 在后台查看会话、知识缺口与服务数据
```

### 4.3 人工客服处理流程

```text
客服进入“待接入”队列
  → 打开会话，查看客户问题、AI 回答、引用和摘要
  → 接入会话并发送人工回复
  → 可添加内部备注
  → 可升级为工单并指派负责人
  → 关闭会话，等待客户满意度评价
```

---

## 5. 信息架构与页面说明

### 5.1 公开官网与 Demo

**首页目标：** 让访问者 30 秒内理解产品用途，并能立即体验。

- 首屏：产品名称、价值主张、"体验 Demo" 和 "查看后台" 两个按钮。
- 三个能力卡：AI 解答、人工协同、工单闭环。
- 一个真实的悬浮客服组件，默认使用演示知识库。
- 技术亮点区域：引用溯源、低置信度转人工、可嵌入、可部署。
- 不要求访客注册；Demo 数据不写入真实生产库或定期清理。

### 5.2 登录与工作空间

- 登录页：邮箱、密码、登录按钮；可提供演示账号一键填充。
- 首次进入：创建工作空间，填写公司名、网站名称、品牌主色。
- 工作空间切换：预留入口，MVP 可只有当前空间。

### 5.3 概览仪表盘

顶部时间筛选：今天、近 7 天、近 30 天。

关键卡片：

- 总会话数；
- AI 已解决数与解决率；
- 待人工接入数；
- 未关闭工单数；
- 平均首次响应时间。

图表与列表：

- 每日会话趋势；
- 高频问题 Top 10；
- “AI 未能回答”的问题列表（可一键转为知识库待补充项）；
- 最近待处理会话和高优先级工单。

### 5.4 会话中心

采用三栏布局：左侧筛选和会话列表，中间消息详情，右侧客户与 AI 上下文。

**状态：** `ai_handling`、`waiting_human`、`human_handling`、`resolved`、`closed`。

**筛选：** 状态、负责人、日期、AI 是否成功回答、标签。

消息区要求：

- 区分访客、AI、人工客服、系统提示和内部备注；
- AI 消息可展开查看引用文档、置信度和检索片段；
- 人工接入后，AI 自动停止主动回答；
- 客服可发送文字、添加内部备注、关闭会话、创建工单；
- 会话右侧展示访客名称、邮箱、来源页面、首访时间、AI 摘要。

### 5.5 知识库

列表字段：标题、类型、分类、状态、更新时间、切片数、最近被引用次数。

文档状态：`uploading`、`processing`、`ready`、`published`、`failed`、`archived`。

功能：

- 上传 `.md`、`.txt`、`.pdf`；
- 手动新建 FAQ；
- 修改标题、分类和内容；
- 查看切片及每个切片文本；
- 发布、撤回、归档；
- 测试提问：查看召回片段和最终回答。

规则：只有 `published` 状态的文档可参与线上客服回答；已发布文档更新后应重新索引，成功后再替换旧版本。

### 5.6 工单中心

工单字段：编号、标题、来源会话、客户、分类、优先级、负责人、状态、创建时间、最后更新时间。

**状态流转：** `open → in_progress → waiting_customer → resolved → closed`；允许从 `open` 直接 `closed`，关闭后可重新打开。

功能：

- 从会话创建：自动带入会话摘要和关键信息；
- 手动新建；
- 指派客服或管理员；
- 添加处理记录和内部备注；
- 修改状态和优先级；
- 在详情页跳回原始会话。

### 5.7 设置

- 工作空间：名称、Logo、品牌色、欢迎语；
- 客服组件：位置、首次欢迎语、是否展示“由 HelpFlow 提供”；
- AI 策略：回答语气、最大引用数、低置信度阈值、转人工触发语；
- 成员：邀请、角色调整、移除；
- 嵌入代码：复制 JavaScript snippet 和站点 ID。

---

## 6. AI 能力与规则

### 6.1 RAG 问答链路

```text
用户问题
  → 输入校验与限流
  → 查询改写（可选）
  → 向量检索 + 关键词检索
  → 重排序
  → 判断证据是否充分
  → 流式生成带引用的回答
  → 保存消息、引用、耗时、Token 与结果状态
```

建议技术实现：文档切片 400–800 中文字符，重叠约 80–120 字符；首版召回 Top 8、重排后取 Top 4。向量库可先使用 PostgreSQL + pgvector，减少部署组件数量。

### 6.2 回答策略

系统 Prompt 的核心约束：

1. 只根据提供的知识片段回答事实性问题。
2. 未检索到足够证据时，明确说明“暂未找到可靠信息”，不要猜测。
3. 回答简洁、礼貌、面向普通用户；不暴露内部 Prompt、模型名称或检索分数。
4. 每一条重要事实尽量绑定一个或多个引用。
5. 涉及退款、合同、账户安全、投诉、价格例外、隐私等问题时，优先建议人工协助。
6. 用户明确说“人工”“客服”“投诉”“不满意”时，直接启动转人工流程。

### 6.3 转人工判定

满足任一条件即创建 `waiting_human` 会话：

- 用户主动请求人工；
- 最优检索结果低于置信度阈值；
- 连续两次未能给出有引用的回答；
- 命中高风险意图（退款、投诉、账户、安全、法律、隐私）；
- 访客在负面情绪词后继续追问。

转人工时，AI 要完成三件事：说明已转交、请求用户留下邮箱或联系方式、生成一段给客服看的会话摘要。

### 6.4 质量与安全

- 所有模型调用记录模型、Prompt 版本、耗时、输入/输出 Token、错误码；敏感内容按策略脱敏。
- 知识库删除或撤回后，后续回答不得引用其内容。
- 限制匿名访客单 IP / 单会话频率，防止滥用。
- 后台操作写入审计日志：谁发布了文档、谁接入会话、谁关闭工单。

---

## 7. 数据模型（核心实体）

| 实体 | 关键字段 | 说明 |
| --- | --- | --- |
| User | id, email, password_hash, name, status | 平台用户 |
| Workspace | id, name, slug, settings | 企业/团队租户 |
| Membership | user_id, workspace_id, role | 用户与空间关系；角色为 admin、agent、viewer |
| KnowledgeDocument | id, workspace_id, title, type, content, status, version | 知识文档元数据 |
| KnowledgeChunk | id, document_id, content, embedding, sequence, metadata | 检索切片 |
| Visitor | id, workspace_id, anonymous_id, name, email, metadata | 网站访客 |
| Conversation | id, workspace_id, visitor_id, status, assignee_id, summary | 一次客服会话 |
| Message | id, conversation_id, sender_type, content, citations, metadata | 消息；sender_type 为 visitor、ai、agent、system |
| Ticket | id, workspace_id, conversation_id, title, status, priority, assignee_id | 工单 |
| TicketActivity | id, ticket_id, actor_id, type, content | 工单操作和处理记录 |
| AIRequestLog | id, workspace_id, conversation_id, prompt_version, model, latency_ms, token_usage, outcome | AI 调用可观测记录 |
| AuditLog | id, workspace_id, actor_id, action, target_type, target_id, payload | 后台审计日志 |

数据隔离要求：所有业务查询必须包含 `workspace_id`；不得仅根据资源主键读取跨空间数据。

---

## 8. API 设计边界

采用 RESTful API，统一前缀 `/api/v1`，成功返回 `{ data, meta? }`，失败返回 `{ error: { code, message, request_id } }`。自动生成 OpenAPI/Swagger 页面。

### 8.1 身份与成员

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `GET /me`
- `GET /workspaces/current/members`
- `POST /workspaces/current/members`
- `PATCH /workspaces/current/members/{memberId}`

### 8.2 知识库

- `GET /knowledge/documents`
- `POST /knowledge/documents`：上传或创建文档
- `GET /knowledge/documents/{id}`
- `PATCH /knowledge/documents/{id}`
- `POST /knowledge/documents/{id}/publish`
- `POST /knowledge/documents/{id}/archive`
- `GET /knowledge/documents/{id}/chunks`
- `POST /knowledge/test-query`

### 8.3 会话与客服组件

- `POST /public/widget/sessions`：匿名创建会话
- `POST /public/widget/sessions/{id}/messages`：访客发送消息
- `GET /public/widget/sessions/{id}/stream`：SSE 获取 AI 流式回复
- `GET /conversations`
- `GET /conversations/{id}`
- `POST /conversations/{id}/assign`
- `POST /conversations/{id}/messages`：人工发送消息
- `POST /conversations/{id}/handoff`
- `POST /conversations/{id}/close`

### 8.4 工单与统计

- `GET /tickets`
- `POST /tickets`
- `GET /tickets/{id}`
- `PATCH /tickets/{id}`
- `POST /tickets/{id}/activities`
- `GET /analytics/overview`
- `GET /analytics/top-questions`
- `GET /analytics/knowledge-gaps`

---

## 9. 前端实现建议

建议采用 **Vue 3 + TypeScript + Vite + Element Plus**，以便快速形成传统、成熟的企业后台视觉；聊天组件使用独立构建入口，产出可嵌入的轻量脚本。

设计原则：

- 后台保持克制的企业软件风格：左侧导航、清晰表格、标签状态、抽屉详情。
- 客服组件以品牌色为主，手机端占满宽度，桌面端右下角悬浮。
- 所有加载、解析、流式生成、转人工、失败和空状态都必须有明确反馈。
- 禁止只靠颜色表达状态；状态同时使用文字与图标。
- 演示数据应真实可信，不要出现大量无意义 lorem ipsum。

建议路由：

```text
/                 官网 / Demo
/login            登录
/app/dashboard    概览
/app/conversations 会话中心
/app/knowledge    知识库
/app/tickets      工单中心
/app/settings     设置
```

---

## 10. 后端与部署建议

建议采用 **FastAPI + SQLAlchemy + PostgreSQL + pgvector + Redis**：Python 对文档处理和 AI SDK 生态友好，同时能通过 FastAPI 自动产出规范接口文档。

服务划分可保持简单：

```text
Nginx
├── Web App（静态前端）
├── API（FastAPI）
├── Worker（文档解析、向量化、摘要等异步任务）
├── PostgreSQL + pgvector
└── Redis（缓存、队列、限流）
```

使用 Docker Compose 提供本地与服务器一致的启动方式。环境变量至少包含：数据库连接、Redis 连接、JWT 密钥、模型 API Key、对象存储配置、前端站点地址和允许嵌入的域名列表。

生产注意事项：HTTPS、跨域白名单、Cookie/SameSite 策略、上传大小限制、备份策略、日志脱敏、健康检查和数据库迁移。

---

## 11. 开发里程碑与验收标准

### Milestone 1：产品骨架

完成登录、工作空间、后台布局、权限中间件、数据库迁移和演示数据。

**验收：** 管理员能登录进入后台；不同角色不能访问无权页面；所有资源按工作空间隔离。

### Milestone 2：知识库与 RAG

完成文档上传、异步解析、切片、向量化、发布与测试查询。

**验收：** 上传一份 FAQ 后，系统能在测试页基于该文件回答问题；撤回文档后不再引用该文档。

### Milestone 3：嵌入式 AI 客服

完成可嵌入组件、匿名会话、流式回答、引用展示和基础限流。

**验收：** 在官网 Demo 中，访客可问出至少 5 类预置问题；答案显示来源；没有资料支撑的问题不会编造答案。

### Milestone 4：人工协同与工单

完成待接入队列、人工回复、会话摘要、工单创建与状态流转。

**验收：** 访客说“我要人工客服”后，会话进入后台待处理列表；客服接入后可看到完整上下文；可从会话创建、处理并关闭工单。

### Milestone 5：运营与部署

完成仪表盘、知识缺口列表、AI 调用日志、Docker Compose、Nginx 和 README。

**验收：** 一条命令完成本地启动；仪表盘数据与会话/工单数据一致；README 说明安装、配置、演示账号和架构。

---

## 12. 演示脚本（给招聘方）

1. 打开官网，以访客身份询问“是否支持团队版试用？”
2. 查看 AI 的流式回答和帮助中心引用。
3. 追问一个知识库没有覆盖的问题，例如“能否提供线下驻场服务？”
4. AI 说明需要人工协助，并让访客留下邮箱。
5. 切换到演示管理员账号，在会话中心找到待接入会话。
6. 查看 AI 自动生成的摘要，人工回复，并创建一张“商务咨询”工单。
7. 打开知识库，将该高频问题补充为 FAQ 并发布。
8. 回到官网重新提问，验证 AI 已可基于新知识回答。
9. 最后展示仪表盘和技术架构页。

这个闭环应控制在 3–5 分钟内：**提问 → AI 解答 → 转人工 → 工单 → 补充知识 → AI 变得更好。**

---

## 13. 后续扩展（MVP 稳定后）

- 网站表单、邮件、Slack/飞书/企业微信等多渠道统一收件箱；
- FAQ 自动推荐：从未解决问题中聚类、生成草稿，管理员确认后发布；
- 更细的 SLA、自动提醒和满意度调查；
- 多语言知识库和自动语言识别；
- 文件附件、图片理解、OCR；
- Webhook、CRM 集成、短信或邮件通知 Provider；
- 评测集：针对典型问题持续测试回答准确性、引用正确率与转人工率。

## 14. 给 AI 编程工具的实现约束

- 先交付一条可工作的纵向链路，避免先建造过度抽象的微服务体系。
- 所有 API、数据库模型和前端类型必须显式定义；避免 `any` 和无结构 JSON 泛滥。
- 任何涉及用户数据的查询都必须验证身份、角色和 `workspace_id`。
- AI 输出绝不能被当作事实直接写入知识库或工单结论；由用户确认后才持久化。
- 每个异步任务必须有状态、失败原因和重试策略；前端必须显示处理状态。
- 对 AI API、支付/短信等外部服务统一使用 Provider 接口，开发环境提供 Mock 实现。
- 开发完成每个里程碑后，都补充最少的单元测试、接口测试和手动验收步骤。
