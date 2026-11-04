import { authState, clearSession, setSession, type Session } from './auth'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type ApiEnvelope<T> = { data: T }
type TokenPayload = {
  access_token: string
  refresh_token: string
  user: Session['user']
  workspace: Session['workspace']
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export type KnowledgeDocument = {
  id: string
  title: string
  type: 'faq' | 'markdown' | 'text' | 'pdf'
  category: string | null
  status: 'uploading' | 'processing' | 'ready' | 'published' | 'failed' | 'archived'
  version: number
  source_filename: string | null
  failure_reason: string | null
  chunk_count: number
  created_at: string
  updated_at: string
  published_at: string | null
}

export type KnowledgeDocumentDetail = KnowledgeDocument & { content: string | null }

export type KnowledgeChunk = {
  id: string
  sequence: number
  content: string
  metadata: Record<string, unknown>
}

export type KnowledgeMatch = {
  document_id: string
  document_title: string
  chunk_id: string
  content: string
  score: number
}

export type KnowledgeTestResult = {
  answer_preview: string
  matches: KnowledgeMatch[]
}

export type PublicChatConfig = {
  slug: string
  name: string
  greeting: string
  preset_questions: string[]
  handoff_note: string
}

export type PublicVisitorMessage = {
  id: string
  role: 'visitor' | 'assistant' | 'agent' | 'system'
  content: string
  created_at: string
}

export type PublicConversationMessages = {
  conversation_id: string
  status: ConversationStatus
  messages: PublicVisitorMessage[]
}

export type ConversationStatus = 'active' | 'waiting_human' | 'human' | 'closed'
export type ConversationRole = 'visitor' | 'assistant' | 'agent' | 'system'

export type ConversationSummary = {
  id: string
  visitor_id: string
  channel: string
  status: ConversationStatus
  subject: string | null
  assigned_user_id: string | null
  assigned_user_name: string | null
  message_count: number
  last_message: string | null
  ticket_id: string | null
  last_message_at: string | null
  created_at: string
  updated_at: string
}

export type ConversationMessage = {
  id: string
  role: ConversationRole
  content: string
  confidence: number | null
  citations: ChatCitation[]
  visibility: 'public' | 'internal'
  author_user_id: string | null
  author_user_name: string | null
  created_at: string
}

export type AgentRunStatus = 'running' | 'waiting_approval' | 'completed' | 'rejected' | 'failed'

export type AgentEvent = {
  id: string
  seq: number
  type: string
  name: string | null
  status: string
  summary: string | null
  payload: Record<string, unknown>
  created_at: string
}

export type AgentApproval = {
  id: string
  tool_name: string
  arguments: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected'
  note: string | null
  requested_at: string
  decided_by_user_id: string | null
  decided_at: string | null
}

export type AgentRun = {
  id: string
  conversation_id: string
  question: string
  intent: string | null
  status: AgentRunStatus
  answer: string | null
  citations: ChatCitation[]
  error: string | null
  latency_ms: number | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

export type AgentRunDetail = AgentRun & {
  events: AgentEvent[]
  approvals: AgentApproval[]
}

export type ConversationDetail = ConversationSummary & {
  messages: ConversationMessage[]
  agent_runs: AgentRunDetail[]
}

export type TicketPriority = 'low' | 'normal' | 'high' | 'urgent'
export type TicketStatus = 'open' | 'in_progress' | 'waiting' | 'resolved' | 'closed'

export type Ticket = {
  id: string
  conversation_id: string | null
  conversation_subject: string | null
  title: string
  description: string | null
  priority: TicketPriority
  status: TicketStatus
  assignee_id: string | null
  assignee_name: string | null
  created_by_user_id: string | null
  created_by_name: string | null
  created_at: string
  updated_at: string
}

export type Member = {
  id: string
  user_id: string
  email: string
  name: string
  role: 'admin' | 'agent' | 'viewer'
}

export type DashboardDailyPoint = {
  date: string
  conversations: number
  ai_answers: number
  refusals: number
}

export type DashboardKnowledgeGap = {
  question: string
  occurrences: number
  last_asked_at: string
}

export type DashboardSummary = {
  conversations_total: number
  waiting_human: number
  human_active: number
  closed_conversations: number
  tickets_total: number
  tickets_open: number
  ai_answers: number
  refused_answers: number
  handoff_requests: number
  refusal_rate: number
  avg_confidence: number | null
  daily: DashboardDailyPoint[]
  knowledge_gaps: DashboardKnowledgeGap[]
}

export type AiCallLog = {
  id: string
  conversation_id: string | null
  conversation_subject: string | null
  provider: string
  model: string | null
  mode: string
  confidence: number | null
  latency_ms: number | null
  success: boolean
  error: string | null
  created_at: string
}

export type AuditLog = {
  id: string
  actor_name: string | null
  action: string
  target_type: string
  target_id: string | null
  detail: Record<string, unknown>
  created_at: string
}

export type EvalMode = 'answer' | 'refused'

export type EvalCase = {
  id: string
  question: string
  expected_documents: string[]
  cited_documents: string[]
  predicted_mode: EvalMode
  expected_mode: EvalMode
  passed: boolean
  metrics: Record<string, number | string | boolean>
  latency_ms: number | null
  error: string | null
  created_at: string
}

export type EvalRun = {
  id: string
  name: string
  status: string
  judge: string
  total_cases: number
  passed_cases: number
  metrics: Record<string, number | string | boolean>
  created_by_user_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export type EvalRunDetail = EvalRun & { cases: EvalCase[] }

export type EvalHistoryPoint = {
  id: string
  name: string
  created_at: string
  pass_rate: number
}

export type EvalSummary = {
  latest: EvalRun | null
  history: EvalHistoryPoint[]
  golden_total: number
}

export type ConversationListParams = {
  status?: ConversationStatus
  assigned?: 'all' | 'me' | 'unassigned'
  q?: string
}

export type TicketListParams = {
  status?: TicketStatus
  priority?: TicketPriority
  assignee?: 'all' | 'me' | 'unassigned'
}

export type ChatCitation = {
  index: number
  document_id: string
  document_title: string
  chunk_id: string
  snippet: string
  score: number
}

export type ChatMeta = {
  conversation_id: string
  visitor_id: string
  provider: string
  mode: 'answer' | 'refused' | 'handoff' | 'blocked' | 'human_waiting'
  confidence: number
  refused: boolean
  blocked: boolean
  handoff: boolean
  handoff_suggested: boolean
}

export type ChatDone = ChatMeta & { message_id: string | null }

export type ChatStreamCallbacks = {
  onMeta?: (data: ChatMeta) => void
  onDelta?: (text: string) => void
  onCitations?: (citations: ChatCitation[]) => void
  onHandoff?: (note: string) => void
  onDone?: (data: ChatDone) => void
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (authState.session) headers.set('Authorization', `Bearer ${authState.session.accessToken}`)
  const response = await fetch(`${apiBaseUrl}/api/v1${path}`, { ...init, headers })

  if (response.status === 401 && retry && authState.session) {
    try {
      const payload = await refresh(authState.session.refreshToken)
      setSession(toSession(payload))
      return request<T>(path, init, false)
    } catch {
      clearSession()
    }
  }
  const body = (await response.json().catch(() => null)) as { detail?: string } | null
  if (!response.ok) throw new ApiError(body?.detail ?? '请求失败，请稍后重试。', response.status)
  return (body as ApiEnvelope<T>).data
}

function toSession(payload: TokenPayload): Session {
  return {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token,
    user: payload.user,
    workspace: payload.workspace,
  }
}

export async function login(email: string, password: string): Promise<Session> {
  const response = await request<TokenPayload>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return toSession(response)
}

export async function register(payload: {
  email: string
  password: string
  name: string
  workspace_name: string
}): Promise<Session> {
  const response = await request<TokenPayload>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return toSession(response)
}

async function refresh(refreshToken: string): Promise<TokenPayload> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!response.ok) throw new ApiError('登录状态已过期。', response.status)
  return ((await response.json()) as ApiEnvelope<TokenPayload>).data
}

export function getCurrentUser(): Promise<{ user: Session['user']; workspace: Session['workspace'] }> {
  return request('/auth/me')
}

export function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  return request('/knowledge/documents')
}

export function getKnowledgeDocument(id: string): Promise<KnowledgeDocumentDetail> {
  return request(`/knowledge/documents/${id}`)
}

export function listKnowledgeChunks(id: string): Promise<KnowledgeChunk[]> {
  return request(`/knowledge/documents/${id}/chunks`)
}

export function createFaq(payload: {
  title: string
  content: string
  category?: string
}): Promise<KnowledgeDocument> {
  return request('/knowledge/documents', { method: 'POST', body: JSON.stringify(payload) })
}

export function uploadKnowledgeDocument(file: File, category?: string): Promise<KnowledgeDocument> {
  const form = new FormData()
  form.append('file', file)
  if (category) form.append('category', category)
  return request('/knowledge/documents/upload', { method: 'POST', body: form })
}

export function updateKnowledgeDocument(
  id: string,
  payload: { title?: string; category?: string; content?: string },
): Promise<KnowledgeDocument> {
  return request(`/knowledge/documents/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function publishKnowledgeDocument(id: string): Promise<KnowledgeDocument> {
  return request(`/knowledge/documents/${id}/publish`, { method: 'POST' })
}

export function archiveKnowledgeDocument(id: string): Promise<KnowledgeDocument> {
  return request(`/knowledge/documents/${id}/archive`, { method: 'POST' })
}

export function testKnowledgeQuery(query: string, limit = 4): Promise<KnowledgeTestResult> {
  return request('/knowledge/test-query', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  })
}

export async function fetchPublicChatConfig(slug: string): Promise<PublicChatConfig> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/public/workspaces/${encodeURIComponent(slug)}`,
  )
  const body = (await response.json().catch(() => null)) as
    | { detail?: string; data?: PublicChatConfig }
    | null
  if (!response.ok || !body?.data) {
    throw new ApiError(body?.detail ?? '暂时无法加载在线客服配置。', response.status)
  }
  return body.data
}

export async function streamPublicChat(
  slug: string,
  payload: { message: string; conversation_id?: string | null; visitor_id?: string | null },
  callbacks: ChatStreamCallbacks,
): Promise<void> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/public/workspaces/${encodeURIComponent(slug)}/chat`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(body?.detail ?? '发送消息失败，请稍后重试。', response.status)
  }
  if (!response.body) throw new ApiError('当前浏览器不支持流式响应。', 0)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (block: string): void => {
    let event = ''
    const dataLines: string[] = []
    for (const rawLine of block.split('\n')) {
      const line = rawLine.replace(/\r$/, '')
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!event || dataLines.length === 0) return
    const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
    if (event === 'meta') callbacks.onMeta?.(data as unknown as ChatMeta)
    else if (event === 'delta') callbacks.onDelta?.(String(data.text ?? ''))
    else if (event === 'citations') {
      callbacks.onCitations?.((data.citations as ChatCitation[]) ?? [])
    } else if (event === 'handoff') callbacks.onHandoff?.(String(data.note ?? ''))
    else if (event === 'done') callbacks.onDone?.(data as unknown as ChatDone)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      dispatch(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) dispatch(buffer)
}

function toQuery(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value)
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

export function listConversations(params: ConversationListParams = {}): Promise<ConversationSummary[]> {
  return request(
    `/conversations${toQuery({ status: params.status, assigned: params.assigned, q: params.q })}`,
  )
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request(`/conversations/${id}`)
}

export function joinConversation(id: string): Promise<ConversationDetail> {
  return request(`/conversations/${id}/join`, { method: 'POST' })
}

export function replyToConversation(
  id: string,
  payload: { content: string; internal: boolean },
): Promise<ConversationMessage> {
  return request(`/conversations/${id}/messages`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function closeConversation(id: string): Promise<ConversationDetail> {
  return request(`/conversations/${id}/close`, { method: 'POST' })
}

export function listTickets(params: TicketListParams = {}): Promise<Ticket[]> {
  return request(
    `/tickets${toQuery({ status: params.status, priority: params.priority, assignee: params.assignee })}`,
  )
}

export function createTicket(payload: {
  conversation_id?: string
  title: string
  description?: string
  priority?: TicketPriority
  assignee_id?: string
}): Promise<Ticket> {
  return request('/tickets', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateTicket(
  id: string,
  payload: {
    title?: string
    description?: string
    priority?: TicketPriority
    status?: TicketStatus
    assignee_id?: string | null
  },
): Promise<Ticket> {
  return request(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function listMembers(): Promise<Member[]> {
  return request('/workspaces/current/members')
}

export function addMember(payload: { email: string; name: string; role: Member['role'] }): Promise<Member> {
  return request('/workspaces/current/members', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateMemberRole(memberId: string, role: Member['role']): Promise<Member> {
  return request(`/workspaces/current/members/${memberId}`, { method: 'PATCH', body: JSON.stringify({ role }) })
}

export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return request('/dashboard/summary')
}

export function listAiLogs(
  params: { limit?: number; success?: boolean; provider?: string } = {},
): Promise<AiCallLog[]> {
  const search = new URLSearchParams()
  if (params.limit) search.set('limit', String(params.limit))
  if (params.success !== undefined) search.set('success', String(params.success))
  if (params.provider) search.set('provider', params.provider)
  const query = search.toString()
  return request(`/ai-logs${query ? `?${query}` : ''}`)
}

export function listAuditLogs(params: { limit?: number; action?: string } = {}): Promise<AuditLog[]> {
  const search = new URLSearchParams()
  if (params.limit) search.set('limit', String(params.limit))
  if (params.action) search.set('action', params.action)
  const query = search.toString()
  return request(`/audit-logs${query ? `?${query}` : ''}`)
}

export function fetchAgentRuns(
  params: { status?: AgentRunStatus; conversation_id?: string; limit?: number } = {},
): Promise<AgentRun[]> {
  return request(
    `/agents/runs${toQuery({
      status: params.status,
      conversation_id: params.conversation_id,
      limit: params.limit === undefined ? undefined : String(params.limit),
    })}`,
  )
}

export function fetchAgentRun(id: string): Promise<AgentRunDetail> {
  return request(`/agents/runs/${id}`)
}

export function approveAgentRun(id: string, note?: string): Promise<AgentRunDetail> {
  return request(`/agents/runs/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ note: note ?? null }),
  })
}

export function rejectAgentRun(id: string, note?: string): Promise<AgentRunDetail> {
  return request(`/agents/runs/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ note: note ?? null }),
  })
}

export function fetchEvalRuns(limit?: number): Promise<EvalRun[]> {
  return request(`/evals/runs${toQuery({ limit: limit === undefined ? undefined : String(limit) })}`)
}

export function fetchEvalRun(id: string): Promise<EvalRunDetail> {
  return request(`/evals/runs/${id}`)
}

export function fetchEvalSummary(): Promise<EvalSummary> {
  return request('/evals/summary')
}

export async function fetchPublicConversationMessages(
  slug: string,
  conversationId: string,
  visitorId: string,
): Promise<PublicConversationMessages> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/public/workspaces/${encodeURIComponent(slug)}/conversations/${encodeURIComponent(conversationId)}/messages?visitor_id=${encodeURIComponent(visitorId)}`,
  )
  const body = (await response.json().catch(() => null)) as
    | { detail?: string; data?: PublicConversationMessages }
    | null
  if (!response.ok || !body?.data) {
    throw new ApiError(body?.detail ?? '暂时无法获取人工客服消息。', response.status)
  }
  return body.data
}
