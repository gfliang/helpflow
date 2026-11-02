<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  ApiError,
  approveAgentRun,
  closeConversation,
  createTicket,
  getConversation,
  joinConversation,
  listConversations,
  listMembers,
  rejectAgentRun,
  replyToConversation,
  type AgentApproval,
  type AgentRunDetail,
  type AgentRunStatus,
  type ConversationDetail,
  type ConversationStatus,
  type ConversationSummary,
  type Member,
  type TicketPriority,
} from '@/lib/api'
import { authState } from '@/lib/auth'

const statusLabel: Record<ConversationStatus, string> = {
  active: 'AI 应答中',
  waiting_human: '待人工接入',
  human: '人工服务中',
  closed: '已结束',
}
const roleLabel: Record<string, string> = {
  visitor: '访客',
  assistant: 'AI 助手',
  agent: '人工客服',
  system: '系统',
}
const priorityLabel: Record<TicketPriority, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}
const filters: { value: ConversationStatus | ''; label: string }[] = [
  { value: 'waiting_human', label: '待接入' },
  { value: 'human', label: '人工中' },
  { value: 'active', label: 'AI 应答' },
  { value: 'closed', label: '已结束' },
  { value: '', label: '全部' },
]
const intentLabel: Record<string, string> = {
  refund: '退款',
  order: '订单',
  ticket: '工单',
  knowledge: '知识问答',
}
const runStatusLabel: Record<AgentRunStatus, string> = {
  running: '运行中',
  waiting_approval: '等待审批',
  completed: '已完成',
  rejected: '已拒绝',
  failed: '失败',
}
const approvalStatusLabel: Record<AgentApproval['status'], string> = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已拒绝',
}
const toolLabel: Record<string, string> = {
  search_knowledge: '检索知识库',
  get_customer: '查询客户',
  list_orders: '查询订单列表',
  get_order: '查询订单',
  create_ticket: '创建工单',
  request_refund: '提交退款',
  handoff_to_human: '转人工客服',
}

const conversations = ref<ConversationSummary[]>([])
const selected = ref<ConversationDetail | null>(null)
const members = ref<Member[]>([])
const activeFilter = ref<ConversationStatus | ''>('waiting_human')
const search = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const notice = ref('')
const actionBusy = ref(false)

const sendMode = ref<'public' | 'internal'>('public')
const draft = ref('')
const sending = ref(false)

const ticketFormOpen = ref(false)
const ticketSaving = ref(false)
const ticketForm = reactive({
  title: '',
  description: '',
  priority: 'normal' as TicketPriority,
  assignee_id: '',
})

const expandedRuns = reactive<Record<string, boolean>>({})
const approvalNotes = reactive<Record<string, string>>({})
const decisionBusy = reactive<Record<string, boolean>>({})

const canWrite = computed(() => authState.session?.workspace.role !== 'viewer')
const currentUserId = computed(() => authState.session?.user.id)
const assignableMembers = computed(() => members.value.filter((member) => member.role !== 'viewer'))
const agentRuns = computed<AgentRunDetail[]>(() => selected.value?.agent_runs ?? [])
const selectedIsMine = computed(
  () => !!selected.value && selected.value.assigned_user_id === currentUserId.value,
)
const canJoin = computed(
  () => canWrite.value && !!selected.value && selected.value.status !== 'closed' && !selected.value.assigned_user_id,
)

let pollTimer: number | undefined

function messageOf(value: unknown): string {
  return value instanceof ApiError ? value.message : '操作失败，请稍后重试。'
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
}

function formatLatency(value: number | null): string {
  return value === null ? '—' : `${value} ms`
}

function summarizeTool(run: AgentRunDetail): string {
  const names = [
    ...new Set(
      run.events
        .filter((event) => event.type === 'tool_result')
        .map((event) => event.name)
        .filter((name): name is string => !!name),
    ),
  ]
  if (!names.length) return '—'
  return names.map((name) => toolLabel[name] ?? name).join(' → ')
}

function summarizeResult(run: AgentRunDetail): string {
  if (run.error) return run.error
  const last = [...run.events].reverse().find((event) => event.summary)
  return last?.summary || run.answer || '—'
}

function isRunExpanded(run: AgentRunDetail): boolean {
  return expandedRuns[run.id] ?? run.status === 'waiting_approval'
}

function toggleRun(id: string): void {
  const run = agentRuns.value.find((item) => item.id === id)
  expandedRuns[id] = run ? !isRunExpanded(run) : true
}

function pendingApproval(run: AgentRunDetail): AgentApproval | null {
  return run.approvals.find((approval) => approval.status === 'pending') ?? null
}

async function decideRun(run: AgentRunDetail, approved: boolean): Promise<void> {
  if (decisionBusy[run.id] || !selected.value) return
  const conversationId = selected.value.id
  const approval = pendingApproval(run)
  const note = approval ? (approvalNotes[approval.id] ?? '').trim() : ''
  decisionBusy[run.id] = true
  error.value = ''
  try {
    if (approved) await approveAgentRun(run.id, note || undefined)
    else await rejectAgentRun(run.id, note || undefined)
    notice.value = approved
      ? '已通过审批，Agent 将继续执行后续步骤。'
      : '已拒绝审批，Agent 已结束本次执行。'
    if (approval) approvalNotes[approval.id] = ''
    await openConversation(conversationId, true)
    await loadList(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    decisionBusy[run.id] = false
  }
}

async function loadList(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    conversations.value = await listConversations({
      status: activeFilter.value || undefined,
      q: search.value.trim() || undefined,
    })
    if (!silent) error.value = ''
  } catch (value) {
    if (!silent) error.value = messageOf(value)
  } finally {
    loading.value = false
  }
}

async function loadMembers(): Promise<void> {
  try {
    members.value = await listMembers()
  } catch {
    members.value = []
  }
}

async function openConversation(id: string, silent = false): Promise<void> {
  if (!silent) detailLoading.value = true
  try {
    selected.value = await getConversation(id)
    if (!silent) {
      error.value = ''
      sendMode.value = 'public'
      ticketFormOpen.value = false
    }
  } catch (value) {
    if (!silent) error.value = messageOf(value)
  } finally {
    detailLoading.value = false
  }
}

function setFilter(value: ConversationStatus | ''): void {
  activeFilter.value = value
  void loadList()
}

async function join(): Promise<void> {
  if (!selected.value) return
  actionBusy.value = true
  error.value = ''
  try {
    selected.value = await joinConversation(selected.value.id)
    notice.value = '已接入会话，可以开始回复访客。'
    await loadList(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    actionBusy.value = false
  }
}

async function sendMessage(): Promise<void> {
  if (!selected.value || !draft.value.trim() || sending.value) return
  sending.value = true
  error.value = ''
  const content = draft.value.trim()
  try {
    await replyToConversation(selected.value.id, {
      content,
      internal: sendMode.value === 'internal',
    })
    draft.value = ''
    notice.value = sendMode.value === 'internal' ? '内部备注已保存，访客不可见。' : '回复已发送。'
    await openConversation(selected.value.id, true)
    await loadList(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    sending.value = false
  }
}

async function close(): Promise<void> {
  if (!selected.value) return
  if (!window.confirm('确认关闭本次会话？访客将看到会话已结束。')) return
  actionBusy.value = true
  error.value = ''
  try {
    selected.value = await closeConversation(selected.value.id)
    notice.value = '会话已关闭。'
    await loadList(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    actionBusy.value = false
  }
}

function openTicketForm(): void {
  if (!selected.value) return
  ticketForm.title = selected.value.subject || `访客 ${selected.value.visitor_id.slice(0, 8)} 的咨询`
  ticketForm.description = selected.value.messages
    .filter((message) => message.visibility === 'public' && message.role !== 'system')
    .slice(-4)
    .map((message) => `${roleLabel[message.role] ?? message.role}: ${message.content}`)
    .join('\n')
  ticketForm.priority = 'normal'
  ticketForm.assignee_id = selected.value.assigned_user_id ?? ''
  ticketFormOpen.value = true
}

async function submitTicket(): Promise<void> {
  if (!selected.value || !ticketForm.title.trim()) return
  ticketSaving.value = true
  error.value = ''
  try {
    await createTicket({
      conversation_id: selected.value.id,
      title: ticketForm.title.trim(),
      description: ticketForm.description.trim() || undefined,
      priority: ticketForm.priority,
      assignee_id: ticketForm.assignee_id || undefined,
    })
    ticketFormOpen.value = false
    notice.value = '工单已创建，可在工单中心继续跟进。'
    await openConversation(selected.value.id, true)
    await loadList(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    ticketSaving.value = false
  }
}

function startPolling(): void {
  pollTimer = window.setInterval(() => {
    void loadList(true)
    if (selected.value) void openConversation(selected.value.id, true)
  }, 10_000)
}

onMounted(() => {
  void loadList()
  void loadMembers()
  startPolling()
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="inbox-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">会话中心</p>
        <h1>人工接入与访客会话</h1>
        <p class="page-description">
          访客在官网点击「转人工」后会进入这里。接入会话、回复访客、记录内部备注，并把需要跟进的问题转成工单。
        </p>
      </div>
      <button class="ghost" type="button" :disabled="loading" @click="loadList()">
        {{ loading ? '刷新中…' : '刷新队列' }}
      </button>
    </header>

    <p v-if="error" class="alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <div class="inbox-layout">
      <aside class="panel queue">
        <div class="filter-row">
          <button
            v-for="filter in filters"
            :key="filter.label"
            type="button"
            class="chip"
            :class="{ active: activeFilter === filter.value }"
            @click="setFilter(filter.value)"
          >
            {{ filter.label }}
          </button>
        </div>
        <form class="search" @submit.prevent="loadList()">
          <input v-model="search" maxlength="120" placeholder="搜索访客或会话主题" />
          <button type="submit">搜索</button>
        </form>

        <p v-if="!conversations.length && !loading" class="empty">
          当前筛选下没有会话。访客在官网发起对话后会出现在这里。
        </p>
        <ul class="queue-list">
          <li v-for="conversation in conversations" :key="conversation.id">
            <button
              type="button"
              class="queue-item"
              :class="{ active: selected?.id === conversation.id }"
              @click="openConversation(conversation.id)"
            >
              <span class="queue-top">
                <strong>{{ conversation.subject || '未命名会话' }}</strong>
                <span class="badge" :class="`status-${conversation.status}`">
                  {{ statusLabel[conversation.status] }}
                </span>
              </span>
              <span class="queue-preview">{{ conversation.last_message || '暂无公开消息' }}</span>
              <span class="queue-meta">
                <span>{{ conversation.assigned_user_name ?? '未指派' }}</span>
                <span>{{ conversation.message_count }} 条 · {{ formatDate(conversation.last_message_at) }}</span>
              </span>
              <span v-if="conversation.ticket_id" class="ticket-chip">已关联工单</span>
            </button>
          </li>
        </ul>
      </aside>

      <section class="panel detail">
        <p v-if="!selected && !detailLoading" class="empty">
          从左侧选择一个会话，查看对话记录并接入。
        </p>
        <p v-else-if="detailLoading && !selected" class="empty">正在加载会话…</p>

        <template v-if="selected">
          <div class="detail-head">
            <div>
              <h2>{{ selected.subject || '未命名会话' }}</h2>
              <p class="subline">
                访客 {{ selected.visitor_id }} · 创建于 {{ formatDate(selected.created_at) }}
                <span v-if="selected.assigned_user_name"> · 负责人 {{ selected.assigned_user_name }}</span>
              </p>
            </div>
            <span class="badge" :class="`status-${selected.status}`">
              {{ statusLabel[selected.status] }}
            </span>
          </div>

          <div class="detail-actions">
            <button
              v-if="canJoin"
              type="button"
              :disabled="actionBusy"
              @click="join"
            >
              接入会话
            </button>
            <span v-else-if="selectedIsMine" class="hint">你已接入该会话</span>
            <span v-else-if="selected.assigned_user_id" class="hint">
              会话已由 {{ selected.assigned_user_name }} 接入
            </span>
            <button
              v-if="canWrite && selected.status !== 'closed'"
              type="button"
              class="ghost danger"
              :disabled="actionBusy"
              @click="close"
            >
              关闭会话
            </button>
            <RouterLink
              v-if="selected.ticket_id"
              class="ghost link-button"
              to="/app/tickets"
            >
              查看关联工单
            </RouterLink>
            <button
              v-else-if="canWrite && selected.status !== 'closed'"
              type="button"
              class="ghost"
              @click="openTicketForm"
            >
              从会话创建工单
            </button>
          </div>

          <form v-if="ticketFormOpen" class="ticket-form" @submit.prevent="submitTicket">
            <label>工单标题<input v-model="ticketForm.title" maxlength="255" required /></label>
            <label>
              问题描述
              <textarea v-model="ticketForm.description" rows="4" maxlength="5000" />
            </label>
            <div class="form-row">
              <label>
                优先级
                <select v-model="ticketForm.priority">
                  <option v-for="(label, value) in priorityLabel" :key="value" :value="value">
                    {{ label }}
                  </option>
                </select>
              </label>
              <label>
                负责人
                <select v-model="ticketForm.assignee_id">
                  <option value="">暂不指派</option>
                  <option v-for="member in assignableMembers" :key="member.user_id" :value="member.user_id">
                    {{ member.name }}（{{ member.role }}）
                  </option>
                </select>
              </label>
            </div>
            <div class="form-actions">
              <button :disabled="ticketSaving || !ticketForm.title.trim()" type="submit">
                {{ ticketSaving ? '创建中…' : '创建工单' }}
              </button>
              <button type="button" class="ghost" @click="ticketFormOpen = false">取消</button>
            </div>
          </form>

          <section v-if="agentRuns.length" class="agent-workbench">
            <div class="workbench-head">
              <h3>Agent 工作台</h3>
              <span class="hint">最近 {{ agentRuns.length }} 次 Agent 执行与工具审批</span>
            </div>

            <article v-for="run in agentRuns" :key="run.id" class="run-card">
              <button
                type="button"
                class="run-head"
                :aria-expanded="isRunExpanded(run)"
                @click="toggleRun(run.id)"
              >
                <span class="run-tags">
                  <span class="intent-tag">
                    {{ intentLabel[run.intent ?? ''] ?? run.intent ?? '未识别意图' }}
                  </span>
                  <span class="badge run-status" :class="`run-${run.status}`">
                    {{ runStatusLabel[run.status] }}
                  </span>
                </span>
                <span class="run-question">{{ run.question }}</span>
                <span class="run-meta">
                  {{ formatLatency(run.latency_ms) }} · {{ formatDate(run.created_at) }}
                </span>
                <span class="run-toggle">{{ isRunExpanded(run) ? '收起' : '展开' }}</span>
              </button>

              <div v-if="isRunExpanded(run)" class="run-body">
                <dl class="run-summary">
                  <div>
                    <dt>意图</dt>
                    <dd>{{ intentLabel[run.intent ?? ''] ?? run.intent ?? '未识别' }}</dd>
                  </div>
                  <div>
                    <dt>工具</dt>
                    <dd>{{ summarizeTool(run) }}</dd>
                  </div>
                  <div>
                    <dt>结果</dt>
                    <dd>{{ summarizeResult(run) }}</dd>
                  </div>
                </dl>

                <div
                  v-for="approval in run.approvals"
                  :key="approval.id"
                  class="approval-card"
                  :class="`approval-${approval.status}`"
                >
                  <header class="approval-head">
                    <strong>{{ toolLabel[approval.tool_name] ?? approval.tool_name }}</strong>
                    <span class="badge decision-badge" :class="`decision-${approval.status}`">
                      {{ approvalStatusLabel[approval.status] }}
                    </span>
                  </header>
                  <p class="approval-line">
                    订单号：{{ approval.arguments?.order_no ?? '—' }}
                  </p>
                  <p class="approval-line">理由：{{ approval.arguments?.reason ?? '—' }}</p>

                  <template v-if="approval.status === 'pending' && run.status === 'waiting_approval'">
                    <template v-if="canWrite">
                      <label class="approval-note">
                        审批备注（可选）
                        <input
                          v-model="approvalNotes[approval.id]"
                          maxlength="2000"
                          placeholder="填写通过或拒绝的原因"
                        />
                      </label>
                      <div class="approval-actions">
                        <button
                          type="button"
                          :disabled="decisionBusy[run.id]"
                          @click="decideRun(run, true)"
                        >
                          {{ decisionBusy[run.id] ? '提交中…' : '通过审批' }}
                        </button>
                        <button
                          type="button"
                          class="ghost danger"
                          :disabled="decisionBusy[run.id]"
                          @click="decideRun(run, false)"
                        >
                          拒绝审批
                        </button>
                      </div>
                    </template>
                    <p v-else class="hint">等待客服审批。</p>
                  </template>
                  <p v-else-if="approval.status !== 'pending'" class="approval-result">
                    {{ approval.status === 'approved' ? '已通过' : '已拒绝' }} ·
                    {{ formatDate(approval.decided_at) }}
                    <template v-if="approval.note"> · 备注：{{ approval.note }}</template>
                  </p>
                </div>
              </div>
            </article>
          </section>

          <div class="message-list">
            <p v-if="!selected.messages.length" class="empty">暂无消息。</p>
            <article
              v-for="message in selected.messages"
              :key="message.id"
              class="message"
              :class="[message.role, { internal: message.visibility === 'internal' }]"
            >
              <header>
                <strong>
                  {{ roleLabel[message.role] ?? message.role }}
                  <template v-if="message.author_user_name">· {{ message.author_user_name }}</template>
                </strong>
                <span v-if="message.visibility === 'internal'" class="internal-tag">内部备注</span>
                <time>{{ formatDate(message.created_at) }}</time>
              </header>
              <p>{{ message.content }}</p>
              <details v-if="message.citations.length" class="citations">
                <summary>引用 {{ message.citations.length }} 条知识库资料</summary>
                <ul>
                  <li v-for="citation in message.citations" :key="citation.chunk_id">
                    [{{ citation.index }}] {{ citation.document_title }}
                  </li>
                </ul>
              </details>
            </article>
          </div>

          <div v-if="canWrite && selected.status !== 'closed'" class="composer">
            <div class="mode-row">
              <button
                type="button"
                class="chip"
                :class="{ active: sendMode === 'public' }"
                @click="sendMode = 'public'"
              >
                回复访客
              </button>
              <button
                type="button"
                class="chip"
                :class="{ active: sendMode === 'internal' }"
                @click="sendMode = 'internal'"
              >
                内部备注
              </button>
              <span class="hint">
                {{ sendMode === 'internal' ? '内部备注仅工作空间成员可见，访客不可见。' : '回复会实时同步到访客的聊天窗口。' }}
              </span>
            </div>
            <textarea
              v-model="draft"
              rows="3"
              maxlength="5000"
              :placeholder="sendMode === 'internal' ? '记录给同事看的备注…' : '输入要发送给访客的回复…'"
            />
            <div class="form-actions">
              <button
                :disabled="sending || !draft.trim()"
                type="button"
                @click="sendMessage"
              >
                {{ sending ? '发送中…' : sendMode === 'internal' ? '保存备注' : '发送回复' }}
              </button>
            </div>
          </div>
          <p v-else-if="!canWrite" class="hint readonly-hint">只读角色可以查看会话，但不能接入或回复。</p>
          <p v-else class="hint readonly-hint">会话已结束，无法继续回复。</p>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.inbox-page { max-width: 1320px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.page-head h1 { margin: 0; font-size: 2.2rem; }
.page-description { max-width: 760px; color: #63728a; line-height: 1.7; }
.alert { padding: .75rem 1rem; color: #b42318; background: #fdecec; border: 1px solid #f3c9c2; border-radius: 8px; }
.notice { padding: .75rem 1rem; color: #17603a; background: #e8f7ee; border: 1px solid #bfe8cf; border-radius: 8px; }
.inbox-layout { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 1.25rem; align-items: start; margin-top: 1.5rem; }
.panel { padding: 1.25rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.queue { position: sticky; top: 1.5rem; }
.filter-row { display: flex; flex-wrap: wrap; gap: .4rem; }
.chip { padding: .4rem .7rem; color: #45536b; font-size: .78rem; font-weight: 600; background: #f3f6fb; border: 1px solid #e1e8f4; border-radius: 999px; }
.chip.active { color: white; background: #356ae6; border-color: #356ae6; }
.search { display: flex; gap: .5rem; margin: .9rem 0; }
.search input { flex: 1; padding: .55rem .7rem; color: #172033; font: inherit; font-size: .85rem; border: 1px solid #cbd5e3; border-radius: 8px; }
.search button { padding: .55rem .8rem; font-size: .8rem; }
.queue-list { display: grid; gap: .6rem; margin: 0; padding: 0; list-style: none; max-height: 620px; overflow-y: auto; }
.queue-item { display: grid; gap: .35rem; width: 100%; padding: .75rem .8rem; color: #172033; text-align: left; background: #f8fafd; border: 1px solid #edf1f7; border-radius: 10px; }
.queue-item:hover { border-color: #c9d8f5; }
.queue-item.active { background: #eef4ff; border-color: #9bb8ee; }
.queue-top { display: flex; align-items: flex-start; justify-content: space-between; gap: .5rem; }
.queue-top strong { font-size: .86rem; line-height: 1.4; }
.queue-preview { overflow: hidden; color: #66758e; font-size: .78rem; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.queue-meta { display: flex; justify-content: space-between; gap: .5rem; color: #8a97ab; font-size: .7rem; }
.ticket-chip { width: fit-content; padding: .15rem .45rem; color: #264b96; font-size: .68rem; font-weight: 700; background: #eef3ff; border-radius: 999px; }
.badge { display: inline-block; padding: .2rem .5rem; font-size: .72rem; font-weight: 700; white-space: nowrap; border-radius: 999px; }
.status-active { color: #264b96; background: #eef3ff; }
.status-waiting_human { color: #8a5a00; background: #fff4dc; }
.status-human { color: #17603a; background: #e8f7ee; }
.status-closed { color: #5b6475; background: #eef1f5; }
.detail { min-height: 560px; display: flex; flex-direction: column; }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.detail-head h2 { margin: 0; font-size: 1.25rem; }
.subline { margin: .35rem 0 0; color: #66758e; font-size: .8rem; }
.detail-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin: .9rem 0; }
.ghost { padding: .55rem .85rem; color: #356ae6; font-size: .85rem; background: #eef3ff; }
.ghost.danger { color: #b42318; background: #fdecec; }
.link-button { text-decoration: none; }
.hint { color: #66758e; font-size: .8rem; line-height: 1.6; }
.readonly-hint { margin-top: 1rem; padding: .7rem .9rem; background: #f8fafd; border: 1px dashed #dbe3f0; border-radius: 8px; }
.ticket-form { display: grid; gap: .75rem; padding: 1rem; margin-bottom: 1rem; background: #f8fafd; border: 1px solid #e1e8f4; border-radius: 10px; }
.ticket-form textarea, .composer textarea { width: 100%; padding: .7rem .8rem; color: #172033; font: inherit; font-size: .88rem; border: 1px solid #cbd5e3; border-radius: 8px; resize: vertical; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
select { width: 100%; padding: .7rem .8rem; color: #172033; font: inherit; background: white; border: 1px solid #cbd5e3; border-radius: 8px; }
.form-actions { display: flex; gap: .5rem; }
.agent-workbench { display: grid; gap: .7rem; padding: 1rem; margin-bottom: 1rem; background: #f8fafd; border: 1px solid #e1e8f4; border-radius: 10px; }
.workbench-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .4rem .75rem; }
.workbench-head h3 { margin: 0; font-size: .98rem; }
.run-card { overflow: hidden; background: white; border: 1px solid #e8eef8; border-radius: 10px; }
.run-head { display: flex; flex-wrap: wrap; align-items: center; gap: .35rem .6rem; width: 100%; padding: .7rem .8rem; color: #172033; font-size: .84rem; font-weight: 500; text-align: left; background: white; border-radius: 0; }
.run-head:hover { background: #f8fafd; }
.run-tags { display: inline-flex; flex-wrap: wrap; align-items: center; gap: .35rem; }
.intent-tag { padding: .15rem .5rem; color: #264b96; font-size: .7rem; font-weight: 700; white-space: nowrap; background: #eef3ff; border-radius: 999px; }
.run-status { font-size: .7rem; }
.run-running { color: #264b96; background: #eef3ff; }
.run-waiting_approval { color: #8a5a00; background: #fff4dc; }
.run-completed { color: #17603a; background: #e8f7ee; }
.run-rejected { color: #b42318; background: #fdecec; }
.run-failed { color: #b42318; background: #fdecec; }
.run-question { flex: 1 1 200px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-meta { color: #8a97ab; font-size: .72rem; white-space: nowrap; }
.run-toggle { margin-left: auto; color: #356ae6; font-size: .74rem; font-weight: 600; white-space: nowrap; }
.run-body { display: grid; gap: .7rem; padding: .65rem .8rem .9rem; border-top: 1px solid #f1f4f9; }
.run-summary { display: grid; gap: .35rem; margin: 0; }
.run-summary div { display: grid; grid-template-columns: 3rem 1fr; gap: .5rem; align-items: baseline; }
.run-summary dt { color: #8a97ab; font-size: .72rem; font-weight: 600; }
.run-summary dd { margin: 0; color: #172033; font-size: .8rem; line-height: 1.6; word-break: break-word; }
.approval-card { display: grid; gap: .55rem; padding: .7rem .8rem; background: #fff8e8; border: 1px solid #e4c476; border-radius: 10px; }
.approval-approved { background: #effaf3; border-color: #bfe8cf; }
.approval-rejected { background: #fdecec; border-color: #f3c9c2; }
.approval-head { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.approval-head strong { font-size: .84rem; }
.decision-pending { color: #8a5a00; background: #fff4dc; }
.decision-approved { color: #17603a; background: #e8f7ee; }
.decision-rejected { color: #b42318; background: #fdecec; }
.approval-line { margin: 0; color: #45536b; font-size: .78rem; line-height: 1.6; word-break: break-word; }
.approval-note { font-size: .78rem; }
.approval-note input { padding: .5rem .6rem; font-size: .82rem; background: white; }
.approval-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.approval-actions button { padding: .5rem .8rem; font-size: .8rem; }
.approval-result { margin: 0; color: #45536b; font-size: .78rem; line-height: 1.6; }
.message-list { flex: 1; display: grid; gap: .75rem; align-content: start; max-height: 480px; padding: .5rem; overflow-y: auto; background: #f8fafd; border-radius: 10px; }
.message { padding: .75rem .9rem; background: white; border: 1px solid #e8eef8; border-radius: 12px; }
.message.visitor { max-width: 88%; color: white; background: #356ae6; border-color: #356ae6; }
.message.visitor header { color: #dbe6ff; }
.message.assistant { max-width: 88%; }
.message.agent { max-width: 88%; margin-left: auto; background: #effaf3; border-color: #bfe8cf; }
.message.internal { background: #fff8e8; border: 1px dashed #e4c476; }
.message.system { color: #5b6475; font-size: .82rem; background: #eef1f5; border-color: #e3e7ee; }
.message header { display: flex; align-items: center; gap: .5rem; margin-bottom: .4rem; color: #66758e; font-size: .72rem; }
.message header strong { font-size: .78rem; }
.message time { margin-left: auto; }
.internal-tag { padding: .1rem .4rem; color: #8a5a00; font-size: .66rem; font-weight: 700; background: #fff4dc; border-radius: 999px; }
.message p { margin: 0; font-size: .88rem; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.citations { margin-top: .5rem; color: #66758e; font-size: .74rem; }
.citations summary { color: #356ae6; font-weight: 600; cursor: pointer; }
.citations ul { margin: .35rem 0 0; padding-left: 1rem; }
.composer { display: grid; gap: .65rem; margin-top: .9rem; }
.mode-row { display: flex; align-items: center; gap: .5rem; }
.mode-row .hint { margin-left: auto; text-align: right; }
.empty { margin: 0; padding: 1.5rem 0; color: #66758e; font-size: .88rem; }
@media (max-width: 1100px) {
  .inbox-layout { grid-template-columns: 1fr; }
  .queue { position: static; }
}
@media (max-width: 720px) {
  .page-head { flex-direction: column; }
  .form-row { grid-template-columns: 1fr; }
  .mode-row { flex-wrap: wrap; }
}
</style>
