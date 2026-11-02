<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ApiError,
  listMembers,
  listTickets,
  updateTicket,
  type Member,
  type Ticket,
  type TicketPriority,
  type TicketStatus,
} from '@/lib/api'
import { authState } from '@/lib/auth'

const statusLabel: Record<TicketStatus, string> = {
  open: '待处理',
  in_progress: '处理中',
  waiting: '等待中',
  resolved: '已解决',
  closed: '已关闭',
}
const priorityLabel: Record<TicketPriority, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}
const transitions: Record<TicketStatus, TicketStatus[]> = {
  open: ['in_progress', 'waiting', 'resolved', 'closed'],
  in_progress: ['waiting', 'resolved', 'closed'],
  waiting: ['in_progress', 'resolved', 'closed'],
  resolved: ['in_progress', 'closed'],
  closed: ['open'],
}
const statusFilters: { value: TicketStatus | ''; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'open', label: '待处理' },
  { value: 'in_progress', label: '处理中' },
  { value: 'waiting', label: '等待中' },
  { value: 'resolved', label: '已解决' },
  { value: 'closed', label: '已关闭' },
]

const tickets = ref<Ticket[]>([])
const members = ref<Member[]>([])
const selected = ref<Ticket | null>(null)
const activeStatus = ref<TicketStatus | ''>('')
const activePriority = ref<TicketPriority | ''>('')
const assigneeFilter = ref<'all' | 'me' | 'unassigned'>('all')
const loading = ref(false)
const error = ref('')
const notice = ref('')
const saving = ref(false)

const editForm = reactive({
  status: 'open' as TicketStatus,
  priority: 'normal' as TicketPriority,
  assignee_id: '',
})

const canWrite = computed(() => authState.session?.workspace.role !== 'viewer')
const assignableMembers = computed(() => members.value.filter((member) => member.role !== 'viewer'))
const allowedStatuses = computed(() =>
  selected.value ? [selected.value.status, ...transitions[selected.value.status]] : [],
)

function messageOf(value: unknown): string {
  return value instanceof ApiError ? value.message : '操作失败，请稍后重试。'
}

function formatDate(value: string): string {
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

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    tickets.value = await listTickets({
      status: activeStatus.value || undefined,
      priority: activePriority.value || undefined,
      assignee: assigneeFilter.value,
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

function selectTicket(ticket: Ticket): void {
  selected.value = ticket
  editForm.status = ticket.status
  editForm.priority = ticket.priority
  editForm.assignee_id = ticket.assignee_id ?? ''
  notice.value = ''
}

async function save(): Promise<void> {
  if (!selected.value) return
  saving.value = true
  error.value = ''
  try {
    selected.value = await updateTicket(selected.value.id, {
      status: editForm.status,
      priority: editForm.priority,
      assignee_id: editForm.assignee_id || null,
    })
    selectTicket(selected.value)
    notice.value = '工单已更新。'
    await load(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    saving.value = false
  }
}

function setStatusFilter(value: TicketStatus | ''): void {
  activeStatus.value = value
  void load()
}

onMounted(() => {
  void load()
  void loadMembers()
})
</script>

<template>
  <section class="tickets-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">工单中心</p>
        <h1>跟进会话升级的问题</h1>
        <p class="page-description">
          工单通常从会话中心创建，保留访客问题与对话上下文。在这里指派负责人，推进优先级与状态流转。
        </p>
      </div>
      <button class="ghost" type="button" :disabled="loading" @click="load()">
        {{ loading ? '刷新中…' : '刷新工单' }}
      </button>
    </header>

    <p v-if="error" class="alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <div class="tickets-layout">
      <section class="panel">
        <div class="filter-row">
          <button
            v-for="filter in statusFilters"
            :key="filter.label"
            type="button"
            class="chip"
            :class="{ active: activeStatus === filter.value }"
            @click="setStatusFilter(filter.value)"
          >
            {{ filter.label }}
          </button>
        </div>
        <div class="secondary-filters">
          <label>
            优先级
            <select v-model="activePriority" @change="load()">
              <option value="">全部</option>
              <option v-for="(label, value) in priorityLabel" :key="value" :value="value">
                {{ label }}
              </option>
            </select>
          </label>
          <label>
            负责人
            <select v-model="assigneeFilter" @change="load()">
              <option value="all">全部</option>
              <option value="me">只看我的</option>
              <option value="unassigned">未指派</option>
            </select>
          </label>
        </div>

        <p v-if="!tickets.length && !loading" class="empty">
          还没有工单。可以在会话中心打开一个会话，点击「从会话创建工单」。
        </p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>标题</th>
                <th>来源会话</th>
                <th>优先级</th>
                <th>状态</th>
                <th>负责人</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ticket in tickets" :key="ticket.id">
                <td>
                  <strong>{{ ticket.title }}</strong>
                  <small>{{ ticket.description?.slice(0, 60) || '暂无描述' }}</small>
                </td>
                <td>{{ ticket.conversation_subject || '—' }}</td>
                <td>
                  <span class="badge" :class="`priority-${ticket.priority}`">
                    {{ priorityLabel[ticket.priority] }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="`status-${ticket.status}`">
                    {{ statusLabel[ticket.status] }}
                  </span>
                </td>
                <td>{{ ticket.assignee_name ?? '未指派' }}</td>
                <td>{{ formatDate(ticket.updated_at) }}</td>
                <td class="row-actions">
                  <button class="link" type="button" @click="selectTicket(ticket)">
                    {{ selected?.id === ticket.id ? '收起' : '管理' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <aside v-if="selected" class="panel detail">
        <div class="panel-head">
          <div>
            <h2>{{ selected.title }}</h2>
            <span>创建人 {{ selected.created_by_name || '—' }} · {{ formatDate(selected.created_at) }}</span>
          </div>
          <button class="ghost" type="button" @click="selected = null">关闭</button>
        </div>

        <p class="description">{{ selected.description || '暂无问题描述。' }}</p>
        <p v-if="selected.conversation_subject" class="source">
          来源会话：{{ selected.conversation_subject }}
        </p>

        <p v-if="!canWrite" class="hint readonly-hint">只读角色可以查看工单，但不能修改状态或指派。</p>
        <form v-else class="edit-form" @submit.prevent="save">
          <label>
            状态
            <select v-model="editForm.status">
              <option v-for="status in allowedStatuses" :key="status" :value="status">
                {{ statusLabel[status] }}
              </option>
            </select>
          </label>
          <label>
            优先级
            <select v-model="editForm.priority">
              <option v-for="(label, value) in priorityLabel" :key="value" :value="value">
                {{ label }}
              </option>
            </select>
          </label>
          <label>
            负责人
            <select v-model="editForm.assignee_id">
              <option value="">未指派</option>
              <option v-for="member in assignableMembers" :key="member.user_id" :value="member.user_id">
                {{ member.name }}（{{ member.role }}）
              </option>
            </select>
          </label>
          <button :disabled="saving" type="submit">{{ saving ? '保存中…' : '保存变更' }}</button>
        </form>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.tickets-page { max-width: 1320px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.page-head h1 { margin: 0; font-size: 2.2rem; }
.page-description { max-width: 760px; color: #63728a; line-height: 1.7; }
.alert { padding: .75rem 1rem; color: #b42318; background: #fdecec; border: 1px solid #f3c9c2; border-radius: 8px; }
.notice { padding: .75rem 1rem; color: #17603a; background: #e8f7ee; border: 1px solid #bfe8cf; border-radius: 8px; }
.tickets-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 1.25rem; align-items: start; margin-top: 1.5rem; }
.panel { padding: 1.25rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.filter-row { display: flex; flex-wrap: wrap; gap: .4rem; }
.chip { padding: .4rem .7rem; color: #45536b; font-size: .78rem; font-weight: 600; background: #f3f6fb; border: 1px solid #e1e8f4; border-radius: 999px; }
.chip.active { color: white; background: #356ae6; border-color: #356ae6; }
.secondary-filters { display: flex; gap: .75rem; margin: 1rem 0; }
.secondary-filters label { width: 160px; color: #33415a; font-size: .8rem; font-weight: 600; }
select { width: 100%; padding: .5rem .65rem; color: #172033; font: inherit; font-size: .85rem; background: white; border: 1px solid #cbd5e3; border-radius: 8px; }
.ghost { padding: .55rem .85rem; color: #356ae6; font-size: .85rem; background: #eef3ff; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th { padding: .6rem .5rem; color: #66758e; font-size: .76rem; font-weight: 700; letter-spacing: .04em; text-align: left; border-bottom: 1px solid #e5eaf2; }
td { padding: .75rem .5rem; vertical-align: top; border-bottom: 1px solid #eef2f7; }
td small { display: block; max-width: 280px; margin-top: .2rem; color: #66758e; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { white-space: nowrap; }
.link { padding: 0; color: #356ae6; font-size: .82rem; font-weight: 600; background: transparent; }
.badge { display: inline-block; padding: .2rem .5rem; font-size: .72rem; font-weight: 700; white-space: nowrap; border-radius: 999px; }
.status-open { color: #264b96; background: #eef3ff; }
.status-in_progress { color: #8a5a00; background: #fff4dc; }
.status-waiting { color: #5b3a99; background: #f1ecff; }
.status-resolved { color: #17603a; background: #e8f7ee; }
.status-closed { color: #5b6475; background: #eef1f5; }
.priority-low { color: #5b6475; background: #eef1f5; }
.priority-normal { color: #264b96; background: #eef3ff; }
.priority-high { color: #8a5a00; background: #fff4dc; }
.priority-urgent { color: #b42318; background: #fdecec; }
.empty { margin: 0; padding: 1.5rem 0; color: #66758e; font-size: .88rem; }
.detail { position: sticky; top: 1.5rem; }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; }
.panel-head h2 { margin: 0; font-size: 1.1rem; }
.panel-head span { color: #66758e; font-size: .76rem; }
.description { margin: 1rem 0 .5rem; padding: .8rem .9rem; color: #33415a; font-size: .86rem; line-height: 1.7; white-space: pre-wrap; background: #f8fafd; border-radius: 8px; }
.source { margin: 0 0 1rem; color: #66758e; font-size: .8rem; }
.edit-form { display: grid; gap: .8rem; margin-top: 1rem; }
.hint { color: #66758e; font-size: .82rem; line-height: 1.6; }
.readonly-hint { margin-top: 1rem; padding: .7rem .9rem; background: #f8fafd; border: 1px dashed #dbe3f0; border-radius: 8px; }
@media (max-width: 1100px) {
  .tickets-layout { grid-template-columns: 1fr; }
  .detail { position: static; }
}
@media (max-width: 720px) {
  .page-head { flex-direction: column; }
  .secondary-filters { flex-wrap: wrap; }
}
</style>
