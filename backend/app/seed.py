"""Idempotently create the local demo workspace, administrator and knowledge base."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.agents.service import INTERIM_REFUND_ANSWER
from app.db.session import SessionLocal
from app.models import (
    AgentApproval,
    AgentEvent,
    AgentRun,
    AiCallLog,
    AuditLog,
    Conversation,
    Customer,
    KnowledgeChunk,
    KnowledgeDocument,
    Membership,
    Message,
    Order,
    Ticket,
    User,
    Workspace,
)
from app.services.passwords import hash_password
from app.tasks.knowledge import process_document
from app.tasks.reindex import reindex_documents

DEMO_EMAIL = "admin@helpflow.com"
DEMO_AGENT_EMAIL = "agent@helpflow.com"
DEMO_PASSWORD = "helpflow-demo"

DEMO_DOCUMENTS = [
    {
        "title": "HelpFlow 产品介绍",
        "type": "text",
        "category": "产品",
        "content": (
            "HelpFlow 是一款面向中小团队的 AI 智能客服与工单管理系统。它把企业帮助文档变成可检索的知识库，"
            "由 AI 在官网聊天组件中回答访客问题，并在需要时无缝转接人工客服。\n\n"
            "核心能力包括：基于已发布知识库的引用溯源回答、低置信度自动转人工、会话中心、"
            "从会话一键创建工单，以及知识缺口和服务质量看板。\n\n"
            "HelpFlow 适合 SaaS 产品、电商和在线服务团队。访客无需注册即可在官网直接提问，"
            "客服团队则通过后台统一处理会话与工单。"
        ),
    },
    {
        "title": "价格方案与计费方式",
        "type": "text",
        "category": "价格",
        "content": (
            "HelpFlow 提供三种方案。基础版每月 299 元，包含 1 个工作空间、3 个客服席位和每月 2,000 次 AI 回答。"
            "专业版每月 899 元，包含 3 个工作空间、10 个客服席位和每月 10,000 次 AI 回答，并支持工单 SLA。"
            "企业版按需报价，提供私有化部署、单点登录和专属客户成功经理。\n\n"
            "所有付费方案均按自然月计费，超出套餐的 AI 回答按每 1,000 次 60 元结算。"
            "年付可享受 9 折优惠。价格调整会提前 30 天通过邮件通知。"
        ),
    },
    {
        "title": "免费试用说明",
        "type": "text",
        "category": "试用",
        "content": (
            "新客户可以免费试用 HelpFlow 专业版 14 天，无需绑定信用卡。试用期间可以使用全部功能，"
            "但 AI 回答总量上限为 500 次，工作空间上限为 1 个。\n\n"
            "试用到期后，工作空间会进入只读状态，数据保留 30 天。你可以随时在后台升级为付费方案，"
            "升级后所有历史会话、知识文档和工单都会保留。若需要延长试用，请联系客户成功团队。"
        ),
    },
    {
        "title": "退款与取消政策",
        "type": "text",
        "category": "退款",
        "content": (
            "月度订阅可以在当前计费周期结束前取消，取消后不再续费，已产生的费用不退还。"
            "年度订阅在首次购买后 7 天内且 AI 使用量低于 100 次时，可以申请全额退款。\n\n"
            "退款申请需要由工作空间管理员在账单页面提交，财务团队会在 5 个工作日内审核。"
            "退款将原路退回，到账时间取决于支付渠道，通常为 3 到 10 个工作日。"
            "涉及合同、发票或价格例外的退款，请转人工客服处理。"
        ),
    },
    {
        "title": "技术接入与聊天组件",
        "type": "markdown",
        "category": "技术",
        "content": (
            "# 技术接入\n\n"
            "HelpFlow 提供一段可嵌入企业网站的 JavaScript 代码。把下面的代码放到 `</body>` 之前即可：\n\n"
            "```html\n<script src=\"https://cdn.helpflow.com/widget.js\" data-workspace=\"helpflow\" async></script>\n```\n\n"
            "## 配置项\n\n"
            "- `data-workspace`：工作空间标识，必填。\n"
            "- `data-theme`：聊天组件主题，可选 `light` 或 `dark`。\n"
            "- `data-greeting`：首次打开时的欢迎语。\n\n"
            "## API 接入\n\n"
            "后端服务提供 REST API，默认地址为 `https://api.helpflow.com`，使用工作空间 API Key 鉴权。"
            "知识库同步接口支持批量导入 Markdown 与纯文本，单次请求最大 10 MB。"
        ),
    },
    {
        "title": "如何联系人工客服",
        "type": "faq",
        "category": "支持",
        "content": (
            "在工作时间（周一至周五 9:00-18:00）可以通过聊天组件左下角的“转人工”按钮联系在线客服。"
            "非工作时间提交的问题会进入待处理队列，客服会在下一个工作日 10:00 前回复。\n\n"
            "你也可以发送邮件到 support@helpflow.com，或在后台会话中心创建工单。"
            "涉及账户安全、退款争议和合同问题时，建议直接转人工客服处理。"
        ),
    },
    {
        "title": "账号安全与密码管理",
        "type": "markdown",
        "category": "账号",
        "content": (
            "# 账号安全\n\n"
            "## 密码策略\n\n"
            "HelpFlow 要求密码长度不少于 8 位，必须同时包含字母和数字。密码加密使用 bcrypt，"
            "系统不会以明文存储密码。\n\n"
            "## 两步验证\n\n"
            "管理员可以在个人设置里开启两步验证（TOTP）。开启后登录时除了密码还需要输入 6 位动态验证码。"
            "企业版支持 SSO（SAML / OIDC），可直接对接企业身份源。\n\n"
            "## 登录安全\n\n"
            "- 连续 5 次登录失败会临时锁定账号 30 分钟。\n"
            "- 异地登录会通过邮件发送告警。\n"
            "- 可以在「会话与安全」页查看并一键踢出所有其他设备。"
        ),
    },
    {
        "title": "发票与账单管理",
        "type": "text",
        "category": "账单",
        "content": (
            "所有付费方案都支持开具增值税普通发票，企业版支持增值税专用发票。"
            "工作空间管理员在「账单」页面填写抬头、税号和接收邮箱后提交，财务团队会在 3 个工作日内处理。\n\n"
            "月度订阅账单会在每月 1 日自动生成；年度订阅账单在到期前 30 天生成续费提醒。"
            "发票开具后会同步到账单页面并发送到预留邮箱。\n\n"
            "如果账单金额与预期不符，请转人工客服并提供账单编号，财务会在 5 个工作日内核查并回复。"
        ),
    },
    {
        "title": "团队成员与权限说明",
        "type": "markdown",
        "category": "团队",
        "content": (
            "# 角色说明\n\n"
            "- **管理员（admin）**：全部权限，包括订阅计费、成员管理、知识库发布/撤回、审计日志查看。\n"
            "- **客服（agent）**：会话接入与回复、工单创建与处理、知识库编辑（不能发布）、审计日志不可见。\n"
            "- **访客（viewer）**：只读，可查看会话中心、工单、知识库和看板，不能修改任何数据。\n\n"
            "## 成员管理\n\n"
            "管理员在「设置 → 成员」中通过邮箱邀请新成员。成员加入后自动分配为 agent 角色，"
            "可随时在列表里调整角色或移除。移除时正在进行的会话和工单会保留历史记录但不再指派。"
        ),
    },
    {
        "title": "API 限流与配额说明",
        "type": "markdown",
        "category": "技术",
        "content": (
            "# 限流策略\n\n"
            "HelpFlow 会对公开接口和管理接口分别做限流：\n\n"
            "- 访客问答（/public/.../chat）：30 次 / 分钟 / 访客，超出返回 429。\n"
            "- 登录（/auth/login）：12 次 / 分钟 / IP，防暴力破解。\n"
            "- 管理接口（/api/v1/*）：200 次 / 分钟 / 用户。\n\n"
            "## AI 使用量\n\n"
            "AI 回答次数按自然月计费，超出套餐的部分每 1,000 次 60 元。"
            "管理员在看板可以看到当天的 AI 使用情况和预估剩余量。企业版支持自定义告警阈值，"
            "当月度 AI 使用量超过 80% 时自动发送邮件通知。"
        ),
    },
    {
        "title": "数据导出与备份",
        "type": "text",
        "category": "数据",
        "content": (
            "管理员可以在「设置 → 数据」里导出工作空间的完整数据，包括：\n"
            "- 所有知识文档（Markdown 格式 + 原始文件）\n"
            "- 全部会话与工单记录（CSV + JSON）\n"
            "- AI 调用日志和审计日志（CSV）\n\n"
            "导出任务通常在 10 分钟内完成，完成后会通过邮件发送下载链接，有效期 7 天。"
            "单个工作空间的完整导出文件大小上限为 5 GB。\n\n"
            "系统每天凌晨 3 点自动备份数据库快照，保留最近 30 天。"
            "企业版支持手动触发备份并恢复到任意快照时间点。"
        ),
    },
    {
        "title": "如何删除工作空间或账号",
        "type": "faq",
        "category": "账号",
        "content": (
            "删除账号：登录后进入个人设置 → 安全 → 删除账号，按提示输入邮箱确认后账号会在 7 天后删除。"
            "7 天内重新登录可以取消删除。\n\n"
            "删除工作空间：只有管理员可以操作。进入「设置 → 基本信息 → 删除工作空间」，"
            "需要输入工作空间名称作为二次确认。删除后所有关联数据（知识、会话、工单、日志）会永久清除，"
            "操作前请务必完成数据导出。\n\n"
            "已付费的工作空间删除后不会退款剩余时段的费用，建议先取消订阅等待到期。"
        ),
    },
    {
        "title": "Webhook 事件订阅",
        "type": "markdown",
        "category": "技术",
        "content": (
            "# Webhook 接入\n\n"
            "HelpFlow 支持通过 Webhook 把关键事件推送到你的系统。进入「设置 → 集成」，"
            "填写接收地址后保存即可。支持的事件类型：\n\n"
            "- `conversation.created`：新访客发起会话\n"
            "- `conversation.handoff`：会话转人工\n"
            "- `ticket.created`：创建工单\n"
            "- `ticket.status_changed`：工单状态变更\n\n"
            "## 签名验证\n\n"
            "每个请求头都会带 `X-HelpFlow-Signature`，是用 HMAC-SHA256 基于 Webhook Secret 对请求体签名。"
            "你的接收端应该验证该签名以确认请求确实来自 HelpFlow。"
        ),
    },
    {
        "title": "SLA 与服务等级说明",
        "type": "text",
        "category": "服务",
        "content": (
            "基础版和专业版的服务目标可用性为 99.5%，企业版为 99.9%。"
            "服务中断时间超过 SLA 承诺时，会根据超出时长按比例折算当月费用。\n\n"
            "技术支持响应时效：\n"
            "- 基础版：工单 24 小时内首次响应\n"
            "- 专业版：工单 4 小时内首次响应，含电话支持\n"
            "- 企业版：专属客户成功经理，2 小时内首次响应，7x24 紧急支持\n\n"
            "所有 SLA 详情会在签订合同时作为附件交付。"
        ),
    },
    {
        "title": "工单 SLA 与超时升级机制",
        "type": "markdown",
        "category": "工单",
        "content": (
            "# 工单优先级与 SLA\n\n"
            "工单可以设置三种优先级，系统会根据优先级自动标记 SLA 截止时间：\n\n"
            "- **低**：24 小时内首次响应，7 天内解决\n"
            "- **普通**：8 小时内首次响应，3 天内解决\n"
            "- **紧急**：2 小时内首次响应，24 小时内解决\n\n"
            "## 超时升级\n\n"
            "工单 SLA 剩余 30 分钟时会自动提醒处理人；超时 1 小时仍未回复时"
            "会升级通知处理人的上级管理员。管理员可以在看板查看所有即将超时的工单。"
        ),
    },
    {
        "title": "钉钉集成与 IM 同步",
        "type": "markdown",
        "category": "集成",
        "content": (
            "# 钉钉集成\n\n"
            "HelpFlow 支持将客服会话实时推送到钉钉群机器人，客服可以在钉钉里直接回复访客。\n\n"
            "## 配置步骤\n\n"
            "1. 在钉钉开放平台创建「自定义机器人」，获取 Webhook URL。\n"
            "2. 进入 HelpFlow「设置 → 集成 → 钉钉」，粘贴 Webhook URL。\n"
            "3. 选择需要推送的事件（新会话、转人工、工单打回）。\n\n"
            "## 回复访客\n\n"
            "钉钉机器人消息下方会带一个「回复」按钮，点击后在钉钉内输入的文本会自动同步回 HelpFlow，"
            "并作为人工回复发送给访客。"
        ),
    },
    {
        "title": "私有化部署说明",
        "type": "markdown",
        "category": "技术",
        "content": (
            "# 私有化部署\n\n"
            "仅企业版支持私有化部署。部署形态支持 Docker Compose 和 Kubernetes 两种。\n\n"
            "## 最低硬件要求\n\n"
            "- 2 核 4 GB 以上 CPU / 内存\n"
            "- 50 GB SSD（含向量数据库）\n"
            "- 操作系统：Ubuntu 22.04 / CentOS 8 / macOS 13+\n\n"
            "## 部署包\n\n"
            "专属客户成功经理会在合同签署后交付离线部署包，包含：\n"
            "- HelpFlow 前端镜像\n"
            "- HelpFlow 后端镜像\n"
            "- PostgreSQL + pgvector 初始化脚本\n"
            "- Redis 配置\n"
            "- 一键启动脚本（`./helpflow up`）\n\n"
            "## 升级方式\n\n"
            "企业版客户可以获得 OTA 升级密钥，在管理后台「设置 → 升级」输入密钥后自动拉取并应用新版本。"
        ),
    },
]


def _seed_knowledge(workspace: Workspace) -> int:
    """Create the demo documents once and keep them published."""
    created_ids = []
    with SessionLocal() as db:
        for item in DEMO_DOCUMENTS:
            exists = db.scalar(
                select(KnowledgeDocument.id).where(
                    KnowledgeDocument.workspace_id == workspace.id,
                    KnowledgeDocument.title == item["title"],
                )
            )
            if exists is not None:
                continue
            document = KnowledgeDocument(
                workspace_id=workspace.id,
                title=item["title"],
                type=item["type"],
                category=item["category"],
                content=item["content"],
                status="uploading",
            )
            db.add(document)
            db.flush()
            created_ids.append(document.id)
        db.commit()

    for document_id in created_ids:
        process_document(document_id)

    with SessionLocal() as db:
        for document_id in created_ids:
            document = db.get(KnowledgeDocument, document_id)
            if document is not None and document.status == "ready":
                document.status = "published"
                document.published_at = datetime.now(UTC)
        db.commit()
    return len(created_ids)


def _ensure_user(db, email: str, name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name, password_hash=hash_password(DEMO_PASSWORD))
        db.add(user)
        db.flush()
    else:
        if user.password_hash == "not-enabled-until-auth-phase":
            user.password_hash = hash_password(DEMO_PASSWORD)
        if user.name != name:
            user.name = name
    return user


REFUSAL_TEXT = (
    "抱歉，我在已发布的知识库中没有找到足够可靠的信息，因此不能凭空回答。"
    "你可以换个说法继续提问，或转人工客服让同事进一步确认。"
)
HANDOFF_TEXT = (
    "好的，正在为你转接人工客服。请补充你的具体问题，客服会在工作时间（周一至周五 9:00-18:00）尽快回复。"
)
CLOSING_TEXT = "本次会话已由人工客服结束，如仍有问题可以重新发起咨询。"
REFUND_COMPLETED_ANSWER = (
    "退款已完成：订单 HF-2026-0001 的 8990 元已原路退回，"
    "通常 3 到 10 个工作日内到账，请留意银行通知。"
)


def _seed_operations(workspace_id, admin_id, agent_id) -> tuple[int, int]:
    """Create believable conversions, tickets and logs exactly once per workspace."""
    with SessionLocal() as db:
        existing = db.scalar(
            select(Conversation.id)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.metadata_["seed"].astext == "phase6",
            )
            .limit(1)
        )
        if existing is not None:
            return 0, 0

        now = datetime.now(UTC)
        authors = {"admin": admin_id, "agent": agent_id}

        def add_conversation(
            *,
            key: str,
            visitor_id: str,
            subject: str,
            status: str,
            assigned: str | None,
            days_ago: int,
            minutes_ago: int = 0,
            messages: list[dict[str, object]],
        ) -> Conversation:
            created = now - timedelta(days=days_ago, minutes=minutes_ago)
            conversation = Conversation(
                workspace_id=workspace_id,
                visitor_id=visitor_id,
                channel="web",
                status=status,
                subject=subject,
                metadata_={"seed": "phase6", "seed_key": key},
                assigned_user_id=authors.get(assigned) if assigned else None,
                assigned_at=created + timedelta(minutes=1) if assigned else None,
                last_message_at=created,
                created_at=created,
                updated_at=created,
            )
            db.add(conversation)
            db.flush()

            moment = created
            for index, item in enumerate(messages):
                moment += timedelta(minutes=int(item.get("offset", 2)))
                mode = item.get("mode")
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        workspace_id=workspace_id,
                        role=str(item["role"]),
                        content=str(item["content"]),
                        confidence=item.get("confidence"),
                        citations=[],
                        metadata_={"mode": mode} if mode else {},
                        visibility=str(item.get("visibility", "public")),
                        author_user_id=authors.get(str(item["author"])) if item.get("author") else None,
                        created_at=moment,
                    )
                )
                db.flush()
                if item["role"] == "assistant":
                    db.add(
                        AiCallLog(
                            workspace_id=workspace_id,
                            conversation_id=conversation.id,
                            provider="openrouter" if mode == "answer" else "rules",
                            model="openrouter/free" if mode == "answer" else None,
                            mode=str(mode),
                            confidence=item.get("confidence"),
                            latency_ms=240 + index * 160,
                            success=True,
                            created_at=moment,
                        )
                    )
            conversation.last_message_at = moment
            conversation.updated_at = moment
            if status == "closed":
                conversation.closed_at = moment
            return conversation

        invoice = add_conversation(
            key="invoice",
            visitor_id="visitor-01",
            subject="专业版可以开发票吗？",
            status="closed",
            assigned="admin",
            days_ago=6,
            messages=[
                {"role": "visitor", "content": "专业版可以开发票吗？", "mode": "answer"},
                {
                    "role": "assistant",
                    "content": (
                        "可以。专业版支持开具增值税普通发票，工作空间管理员可以在账单页面提交抬头与税号，"
                        "财务会在 3 个工作日内处理。 [1]"
                    ),
                    "mode": "answer",
                    "confidence": 0.78,
                    "offset": 1,
                },
                {
                    "role": "agent",
                    "content": "已为你在账单页面开启发票申请入口，填好抬头后告诉我即可。",
                    "author": "admin",
                    "offset": 6,
                },
                {"role": "system", "content": CLOSING_TEXT, "offset": 18},
            ],
        )
        refund = add_conversation(
            key="refund",
            visitor_id="visitor-02",
            subject="年度订阅如何退款？",
            status="closed",
            assigned="admin",
            days_ago=5,
            messages=[
                {"role": "visitor", "content": "年度订阅怎么退款？", "mode": "answer"},
                {
                    "role": "assistant",
                    "content": (
                        "年度订阅在首次购买后 7 天内且 AI 使用量低于 100 次时，可以申请全额退款。"
                        "退款需要工作空间管理员在账单页面提交，财务会在 5 个工作日内审核。 [1]"
                    ),
                    "mode": "answer",
                    "confidence": 0.86,
                    "offset": 1,
                },
                {"role": "system", "content": CLOSING_TEXT, "offset": 12},
            ],
        )
        dingtalk = add_conversation(
            key="dingtalk",
            visitor_id="visitor-03",
            subject="支持钉钉集成吗？",
            status="closed",
            assigned="agent",
            days_ago=4,
            messages=[
                {"role": "visitor", "content": "HelpFlow 支持钉钉集成吗？", "mode": "refused"},
                {"role": "assistant", "content": REFUSAL_TEXT, "mode": "refused", "offset": 1},
                {
                    "role": "agent",
                    "content": "目前还没有钉钉原生集成，但可以通过 Webhook 把工单通知转发到钉钉群。",
                    "author": "agent",
                    "offset": 5,
                },
                {"role": "system", "content": CLOSING_TEXT, "offset": 14},
            ],
        )
        deployment = add_conversation(
            key="deployment",
            visitor_id="visitor-04",
            subject="企业版私有化部署怎么报价？",
            status="human",
            assigned="agent",
            days_ago=2,
            messages=[
                {"role": "visitor", "content": "我们需要私有化部署，怎么报价？", "mode": "answer"},
                {
                    "role": "assistant",
                    "content": (
                        "企业版按需报价，提供私有化部署、单点登录和专属客户成功经理，"
                        "具体价格会根据部署规模与支持范围确定。 [1]"
                    ),
                    "mode": "answer",
                    "confidence": 0.72,
                    "offset": 1,
                },
                {
                    "role": "agent",
                    "content": "已记录你的需求，稍后把报价方案和部署清单发到你的邮箱。",
                    "author": "agent",
                    "offset": 6,
                },
            ],
        )
        add_conversation(
            key="handoff",
            visitor_id="visitor-05",
            subject="我要人工客服",
            status="waiting_human",
            assigned=None,
            days_ago=0,
            minutes_ago=180,
            messages=[
                {"role": "visitor", "content": "我要人工客服", "mode": "handoff"},
                {"role": "assistant", "content": HANDOFF_TEXT, "mode": "handoff", "offset": 1},
            ],
        )
        add_conversation(
            key="trial",
            visitor_id="visitor-06",
            subject="可以免费试用多久？",
            status="closed",
            assigned=None,
            days_ago=1,
            messages=[
                {"role": "visitor", "content": "可以免费试用多久？", "mode": "answer"},
                {
                    "role": "assistant",
                    "content": (
                        "新客户可以免费试用专业版 14 天，无需绑定信用卡。"
                        "试用期间 AI 回答上限为 500 次，工作空间上限为 1 个。 [1]"
                    ),
                    "mode": "answer",
                    "confidence": 0.91,
                    "offset": 1,
                },
                {"role": "system", "content": CLOSING_TEXT, "offset": 9},
            ],
        )
        add_conversation(
            key="pricing",
            visitor_id="visitor-07",
            subject="基础版每月多少钱？",
            status="active",
            assigned=None,
            days_ago=0,
            minutes_ago=25,
            messages=[
                {"role": "visitor", "content": "基础版每月多少钱？", "mode": "answer"},
                {
                    "role": "assistant",
                    "content": (
                        "基础版每月 299 元，包含 1 个工作空间、3 个客服席位和每月 2,000 次 AI 回答。 [1]"
                    ),
                    "mode": "answer",
                    "confidence": 0.88,
                    "offset": 1,
                },
            ],
        )
        add_conversation(
            key="dingtalk-repeat",
            visitor_id="visitor-08",
            subject="支持钉钉集成吗？",
            status="closed",
            assigned=None,
            days_ago=3,
            messages=[
                {"role": "visitor", "content": "支持钉钉集成吗？", "mode": "refused"},
                {"role": "assistant", "content": REFUSAL_TEXT, "mode": "refused", "offset": 1},
                {"role": "system", "content": CLOSING_TEXT, "offset": 7},
            ],
        )

        tickets = [
            Ticket(
                workspace_id=workspace_id,
                conversation_id=deployment.id,
                title="企业版私有化部署报价",
                description="客户需要私有化部署方案与报价，涉及单点登录和专属客户成功支持。",
                priority="high",
                status="in_progress",
                assignee_id=agent_id,
                created_by_user_id=admin_id,
                created_at=deployment.created_at,
                updated_at=deployment.created_at + timedelta(hours=3),
            ),
            Ticket(
                workspace_id=workspace_id,
                conversation_id=refund.id,
                title="年度订阅退款审核",
                description="客户申请年度订阅退款，需要财务确认 AI 使用量是否低于 100 次。",
                priority="normal",
                status="open",
                assignee_id=None,
                created_by_user_id=admin_id,
                created_at=refund.created_at + timedelta(hours=1),
                updated_at=refund.created_at + timedelta(hours=1),
            ),
            Ticket(
                workspace_id=workspace_id,
                conversation_id=dingtalk.id,
                title="钉钉集成咨询跟进",
                description="客户希望对接钉钉，已说明可通过 Webhook 转发工单通知。",
                priority="low",
                status="closed",
                assignee_id=agent_id,
                created_by_user_id=admin_id,
                created_at=dingtalk.created_at + timedelta(hours=1),
                updated_at=dingtalk.created_at + timedelta(hours=2),
            ),
        ]
        db.add_all(tickets)
        db.flush()

        db.add_all(
            [
                AuditLog(
                    workspace_id=workspace_id,
                    actor_user_id=admin_id,
                    action="conversation.close",
                    target_type="conversation",
                    target_id=invoice.id,
                    detail={"visitor_id": invoice.visitor_id},
                    created_at=invoice.updated_at,
                ),
                AuditLog(
                    workspace_id=workspace_id,
                    actor_user_id=agent_id,
                    action="conversation.join",
                    target_type="conversation",
                    target_id=deployment.id,
                    detail={"visitor_id": deployment.visitor_id},
                    created_at=deployment.created_at + timedelta(minutes=3),
                ),
                AuditLog(
                    workspace_id=workspace_id,
                    actor_user_id=admin_id,
                    action="ticket.create",
                    target_type="ticket",
                    target_id=tickets[0].id,
                    detail={"title": tickets[0].title, "priority": "high"},
                    created_at=tickets[0].created_at,
                ),
                AuditLog(
                    workspace_id=workspace_id,
                    actor_user_id=admin_id,
                    action="ticket.update",
                    target_type="ticket",
                    target_id=tickets[0].id,
                    detail={"status": "in_progress", "priority": "high"},
                    created_at=tickets[0].updated_at,
                ),
                AuditLog(
                    workspace_id=workspace_id,
                    actor_user_id=admin_id,
                    action="knowledge.publish",
                    target_type="knowledge_document",
                    target_id=None,
                    detail={"title": "价格方案与计费方式"},
                    created_at=now - timedelta(days=8),
                ),
            ]
        )
        db.commit()
        return 8, len(tickets)


def _seed_agent_data(workspace_id, admin_id, agent_id) -> tuple[int, int, int]:
    """Create demo customers, orders and two refund agent runs exactly once."""
    with SessionLocal() as db:
        existing = db.scalar(
            select(Conversation.id)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.metadata_["seed"].astext == "agent_phase7",
            )
            .limit(1)
        )
        if existing is not None:
            return 0, 0, 0

        now = datetime.now(UTC)
        customers = [
            Customer(
                workspace_id=workspace_id,
                name="张敏",
                email="zhangmin@acme.cn",
                phone="13800000001",
                company="Acme 科技",
                metadata_={"seed": "agent_phase7", "visitor_id": "visitor-01"},
            ),
            Customer(
                workspace_id=workspace_id,
                name="李伟",
                email="liwei@bright.cn",
                phone="13800000002",
                company="Bright 电商",
                metadata_={"seed": "agent_phase7", "visitor_id": "visitor-02"},
            ),
            Customer(
                workspace_id=workspace_id,
                name="王芳",
                email="wangfang@nova.cn",
                phone="13800000003",
                company="Nova 咨询",
                metadata_={"seed": "agent_phase7", "visitor_id": "visitor-03"},
            ),
        ]
        db.add_all(customers)
        db.flush()
        zhangmin, liwei, wangfang = customers

        orders = [
            Order(
                workspace_id=workspace_id,
                customer_id=zhangmin.id,
                order_no="HF-2026-0001",
                product_name="专业版年度订阅",
                plan="pro",
                amount=8990.0,
                currency="CNY",
                status="refunded",
                purchased_at=now - timedelta(days=3),
                delivered_at=now - timedelta(days=3),
                refunded_at=now - timedelta(days=1),
                metadata_={"seed": "agent_phase7", "ai_usage": 12},
            ),
            Order(
                workspace_id=workspace_id,
                customer_id=zhangmin.id,
                order_no="HF-2026-0002",
                product_name="基础版月度订阅",
                plan="basic",
                amount=299.0,
                currency="CNY",
                status="paid",
                purchased_at=now - timedelta(days=20),
                delivered_at=now - timedelta(days=20),
                metadata_={"seed": "agent_phase7", "ai_usage": 4},
            ),
            Order(
                workspace_id=workspace_id,
                customer_id=liwei.id,
                order_no="HF-2026-0003",
                product_name="企业版年度订阅",
                plan="enterprise",
                amount=29900.0,
                currency="CNY",
                status="delivered",
                purchased_at=now - timedelta(days=2),
                delivered_at=now - timedelta(days=2),
                metadata_={"seed": "agent_phase7", "ai_usage": 180},
            ),
            Order(
                workspace_id=workspace_id,
                customer_id=liwei.id,
                order_no="HF-2026-0004",
                product_name="专业版月度订阅",
                plan="pro",
                amount=899.0,
                currency="CNY",
                status="refunded",
                purchased_at=now - timedelta(days=8),
                delivered_at=now - timedelta(days=8),
                refunded_at=now - timedelta(days=6),
                metadata_={"seed": "agent_phase7", "ai_usage": 6},
            ),
            Order(
                workspace_id=workspace_id,
                customer_id=wangfang.id,
                order_no="HF-2026-0005",
                product_name="专业版年度订阅",
                plan="pro",
                amount=8990.0,
                currency="CNY",
                status="shipped",
                purchased_at=now - timedelta(days=4),
                metadata_={"seed": "agent_phase7", "ai_usage": 40},
            ),
        ]
        db.add_all(orders)
        db.flush()

        def add_conversation(
            *,
            key: str,
            visitor_id: str,
            subject: str,
            conversation_status: str,
            created_at: datetime,
            assigned_user_id,
            messages: list[dict[str, object]],
        ) -> Conversation:
            conversation = Conversation(
                workspace_id=workspace_id,
                visitor_id=visitor_id,
                channel="web",
                status=conversation_status,
                subject=subject,
                metadata_={"seed": "agent_phase7", "seed_key": key},
                assigned_user_id=assigned_user_id,
                assigned_at=created_at + timedelta(minutes=1) if assigned_user_id else None,
                last_message_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(conversation)
            db.flush()

            moment = created_at
            for item in messages:
                moment += timedelta(minutes=int(item.get("offset", 1)))
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        workspace_id=workspace_id,
                        role=str(item["role"]),
                        content=str(item["content"]),
                        confidence=item.get("confidence"),
                        citations=[],
                        metadata_=dict(item.get("metadata") or {}),
                        visibility="public",
                        created_at=moment,
                    )
                )
            conversation.last_message_at = moment
            conversation.updated_at = moment
            if conversation_status == "closed":
                conversation.closed_at = moment
            db.flush()
            return conversation

        def add_events(
            run: AgentRun, started_at: datetime, events: list[dict[str, object]]
        ) -> None:
            moment = started_at
            for seq, event in enumerate(events, start=1):
                moment += timedelta(minutes=1)
                db.add(
                    AgentEvent(
                        run_id=run.id,
                        workspace_id=workspace_id,
                        seq=seq,
                        type=str(event["type"]),
                        name=str(event["name"]) if event.get("name") else None,
                        status=str(event.get("status", "ok")),
                        summary=str(event["summary"]) if event.get("summary") else None,
                        payload=dict(event.get("payload") or {}),
                        created_at=moment,
                    )
                )

        completed_started = now - timedelta(days=1, hours=3)
        completed = add_conversation(
            key="refund-completed",
            visitor_id="visitor-02",
            subject="年度订阅退款进度",
            conversation_status="closed",
            created_at=completed_started,
            assigned_user_id=admin_id,
            messages=[
                {"role": "visitor", "content": "我的订单 HF-2026-0001 要退款"},
                {
                    "role": "assistant",
                    "content": INTERIM_REFUND_ANSWER,
                    "offset": 2,
                    "metadata": {"source": "agent", "status": "waiting_approval"},
                },
                {
                    "role": "assistant",
                    "content": REFUND_COMPLETED_ANSWER,
                    "offset": 6,
                    "metadata": {"source": "agent", "status": "completed"},
                },
            ],
        )
        completed_run = AgentRun(
            workspace_id=workspace_id,
            conversation_id=completed.id,
            thread_id=uuid.uuid4().hex,
            question="我的订单 HF-2026-0001 要退款",
            intent="refund",
            status="completed",
            answer=REFUND_COMPLETED_ANSWER,
            citations=[],
            latency_ms=6400,
            created_at=completed_started,
            updated_at=completed_started + timedelta(minutes=8),
            finished_at=completed_started + timedelta(minutes=8),
        )
        db.add(completed_run)
        db.flush()

        completed_approval = AgentApproval(
            run_id=completed_run.id,
            workspace_id=workspace_id,
            tool_name="request_refund",
            arguments={
                "order_no": "HF-2026-0001",
                "amount": 8990,
                "reason": "客户申请年度订阅退款，AI 使用量 12 次",
            },
            status="approved",
            note="符合 7 天退款窗口",
            requested_at=completed_started + timedelta(minutes=3),
            decided_by_user_id=admin_id,
            decided_at=completed_started + timedelta(minutes=4),
        )
        db.add(completed_approval)
        db.flush()
        add_events(
            completed_run,
            completed_started,
            [
                {
                    "type": "tool_call",
                    "name": "check_refund_eligibility",
                    "status": "running",
                    "summary": "调用工具 check_refund_eligibility",
                    "payload": {"arguments": {"order_no": "HF-2026-0001"}},
                },
                {
                    "type": "tool_result",
                    "name": "check_refund_eligibility",
                    "status": "ok",
                    "summary": "订单存在，购买 3 天，AI 使用量 12 次，符合退款条件",
                    "payload": {
                        "data": {"eligible": True, "order_no": "HF-2026-0001"},
                        "duration_ms": 168,
                    },
                },
                {
                    "type": "approval_required",
                    "name": "request_refund",
                    "status": "pending",
                    "summary": "退款申请等待人工审批",
                    "payload": {
                        "approval_id": str(completed_approval.id),
                        "order_no": "HF-2026-0001",
                        "reason": "客户申请年度订阅退款",
                    },
                },
                {
                    "type": "approval_decided",
                    "name": "request_refund",
                    "status": "approved",
                    "summary": "管理员 通过了退款申请",
                    "payload": {"note": "符合 7 天退款窗口", "decided_by": "管理员"},
                },
                {
                    "type": "tool_call",
                    "name": "request_refund",
                    "status": "running",
                    "summary": "调用工具 request_refund",
                    "payload": {"arguments": {"order_no": "HF-2026-0001"}},
                },
                {
                    "type": "tool_result",
                    "name": "request_refund",
                    "status": "ok",
                    "summary": "退款已提交，订单状态更新为 refunded",
                    "payload": {
                        "data": {"order_no": "HF-2026-0001", "status": "refunded"},
                        "duration_ms": 420,
                    },
                },
            ],
        )

        pending_started = now - timedelta(hours=2)
        pending = add_conversation(
            key="refund-pending",
            visitor_id="visitor-05",
            subject="申请退款 HF-2026-0005",
            conversation_status="waiting_human",
            created_at=pending_started,
            assigned_user_id=agent_id,
            messages=[
                {"role": "visitor", "content": "我的订单 HF-2026-0005 要退款，金额 8990"},
                {
                    "role": "assistant",
                    "content": INTERIM_REFUND_ANSWER,
                    "offset": 2,
                    "metadata": {"source": "agent", "status": "waiting_approval"},
                },
            ],
        )
        pending_run = AgentRun(
            workspace_id=workspace_id,
            conversation_id=pending.id,
            thread_id=uuid.uuid4().hex,
            question="我的订单 HF-2026-0005 要退款，金额 8990",
            intent="refund",
            status="waiting_approval",
            answer=INTERIM_REFUND_ANSWER,
            citations=[],
            created_at=pending_started,
            updated_at=pending_started + timedelta(minutes=3),
        )
        db.add(pending_run)
        db.flush()

        pending_approval = AgentApproval(
            run_id=pending_run.id,
            workspace_id=workspace_id,
            tool_name="request_refund",
            arguments={
                "order_no": "HF-2026-0005",
                "amount": 8990,
                "reason": "客户申请年度订阅退款，购买 4 天且 AI 使用量 40 次",
            },
            status="pending",
            requested_at=pending_started + timedelta(minutes=3),
        )
        db.add(pending_approval)
        db.flush()
        add_events(
            pending_run,
            pending_started,
            [
                {
                    "type": "tool_call",
                    "name": "check_refund_eligibility",
                    "status": "running",
                    "summary": "调用工具 check_refund_eligibility",
                    "payload": {"arguments": {"order_no": "HF-2026-0005"}},
                },
                {
                    "type": "tool_result",
                    "name": "check_refund_eligibility",
                    "status": "ok",
                    "summary": "订单存在，购买 4 天，AI 使用量 40 次，符合退款条件",
                    "payload": {
                        "data": {"eligible": True, "order_no": "HF-2026-0005"},
                        "duration_ms": 152,
                    },
                },
                {
                    "type": "approval_required",
                    "name": "request_refund",
                    "status": "pending",
                    "summary": "退款申请等待人工审批",
                    "payload": {
                        "approval_id": str(pending_approval.id),
                        "order_no": "HF-2026-0005",
                        "reason": "客户申请年度订阅退款，购买 4 天且 AI 使用量 40 次",
                    },
                },
            ],
        )
        db.commit()
        return len(customers), len(orders), 2


def seed() -> None:
    with SessionLocal() as db:
        user = _ensure_user(db, DEMO_EMAIL, "管理员")
        agent = _ensure_user(db, DEMO_AGENT_EMAIL, "Agent")

        workspace = db.scalar(select(Workspace).where(Workspace.slug == "helpflow"))
        if workspace is None:
            workspace = Workspace(name="HelpFlow 客户服务中心", slug="helpflow")
            db.add(workspace)
            db.flush()

        for member, role in ((user, "admin"), (agent, "agent")):
            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == member.id, Membership.workspace_id == workspace.id
                )
            )
            if membership is None:
                db.add(Membership(user_id=member.id, workspace_id=workspace.id, role=role))
        db.commit()

        workspace_id = workspace.id
        workspace_slug = workspace.slug
        admin_id = user.id
        agent_id = agent.id
        knowledge_count = _seed_knowledge(workspace)

    with SessionLocal() as db:
        published_chunks = int(
            db.scalar(
                select(func.count(KnowledgeChunk.id))
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .where(
                    KnowledgeDocument.workspace_id == workspace_id,
                    KnowledgeDocument.status == "published",
                )
            )
            or 0
        )
    reindexed = reindex_documents(workspace_slug) if published_chunks == 0 else 0

    conversation_count, ticket_count = _seed_operations(workspace_id, admin_id, agent_id)
    customer_count, order_count, run_count = _seed_agent_data(workspace_id, admin_id, agent_id)
    print(
        f"Seeded workspace '{workspace_slug}', users '{DEMO_EMAIL}' / '{DEMO_AGENT_EMAIL}', "
        f"{knowledge_count} knowledge document(s), {reindexed} reindexed document(s), "
        f"{conversation_count} conversation(s), {ticket_count} ticket(s), "
        f"{customer_count} customer(s), {order_count} order(s) and {run_count} agent run(s)."
    )


if __name__ == "__main__":
    seed()
