<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ApiError,
  fetchPublicChatConfig,
  fetchPublicConversationMessages,
  streamPublicChat,
  type ChatCitation,
  type PublicChatConfig,
} from '@/lib/api'

const markdown = new MarkdownIt({
  html: false,          // 禁止原始 HTML，避免 XSS
  linkify: true,        // 自动识别链接
  breaks: false,        // 单行换行不强制 <br>，依赖段落间距
})

// 允许的 HTML 标签：markdown-it 默认输出 <p><strong><em><ul><ol><li><code><pre><blockquote><a><br><hr><h1-6>
// 这里额外 strip 掉 heading（气泡里不需要大标题）和 task-list，保持气泡风格。
function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = markdown.render(text)
  // 去掉 markdown-it 可能输出的 H1-H6（LLM 偶尔会意外输出大标题）
  return html.replace(/<\/?h[1-6][^>]*>/g, '')
}

type ChatMessage = {
  role: 'visitor' | 'assistant' | 'agent' | 'system'
  content: string
  citations: ChatCitation[]
  pending?: boolean
  refused?: boolean
  blocked?: boolean
  error?: boolean
}

const props = withDefaults(defineProps<{ workspaceSlug?: string }>(), {
  workspaceSlug: import.meta.env.VITE_WORKSPACE_SLUG ?? 'helpflow',
})
const open = defineModel<boolean>('open', { default: false })

const config = ref<PublicChatConfig | null>(null)
const configError = ref('')
const loadingConfig = ref(false)
const messages = ref<ChatMessage[]>([])
const question = ref('')
const sending = ref(false)
const conversationId = ref<string | null>(null)
const visitorId = ref('')
const handoffNote = ref('')
const handoffActive = ref(false)
const conversationClosed = ref(false)
const agentMessageIds = new Set<string>()
const logRef = ref<HTMLElement | null>(null)
let pollTimer: number | undefined

const greeting = computed(
  () => config.value?.greeting ?? '你好，我是 HelpFlow 智能助手。可以问我产品、价格、试用、退款或接入相关的问题。',
)
const presetQuestions = computed(() => config.value?.preset_questions ?? [])
const showPresets = computed(() => messages.value.length === 0 && !sending.value)

function ensureVisitorId(): void {
  if (visitorId.value) return
  const stored = localStorage.getItem('helpflow.visitor')
  if (stored) {
    visitorId.value = stored
    return
  }
  const generated =
    typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `visitor-${Date.now()}-${Math.random().toString(16).slice(2)}`
  visitorId.value = generated
  localStorage.setItem('helpflow.visitor', generated)
}

const CONVERSATION_KEY = 'helpflow.conversation'

function restoreConversation(): void {
  const stored = sessionStorage.getItem(CONVERSATION_KEY)
  if (stored) conversationId.value = stored
}

function resetConversation(): void {
  conversationId.value = null
  sessionStorage.removeItem(CONVERSATION_KEY)
  agentMessageIds.clear()
}

async function loadConfig(): Promise<void> {
  if (config.value || loadingConfig.value) return
  loadingConfig.value = true
  configError.value = ''
  try {
    config.value = await fetchPublicChatConfig(props.workspaceSlug)
  } catch (error) {
    configError.value =
      error instanceof ApiError ? error.message : '暂时无法连接客服服务，请稍后重试。'
  } finally {
    loadingConfig.value = false
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
}

function stopPolling(): void {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function pollAgentMessages(): Promise<void> {
  if (!conversationId.value || !visitorId.value) return
  try {
    const data = await fetchPublicConversationMessages(
      props.workspaceSlug,
      conversationId.value,
      visitorId.value,
    )
    let added = false
    for (const message of data.messages) {
      if (message.role !== 'agent' && message.role !== 'system') continue
      if (agentMessageIds.has(message.id)) continue
      agentMessageIds.add(message.id)
      messages.value.push({ role: message.role, content: message.content, citations: [] })
      added = true
    }
    if (data.status === 'human') handoffActive.value = true
    if (data.status === 'closed') {
      conversationClosed.value = true
      handoffActive.value = false
      stopPolling()
    }
    if (added) {
      void scrollToBottom()
    }
  } catch {
    // Polling is best effort; a transient failure should not disturb the chat.
  }
}

function startPolling(): void {
  if (pollTimer) return
  pollTimer = window.setInterval(() => void pollAgentMessages(), 4_000)
  void pollAgentMessages()
}

async function send(text?: string): Promise<void> {
  const content = (text ?? question.value).trim()
  if (!content || sending.value) return
  ensureVisitorId()
  if (conversationClosed.value) {
    resetConversation()
    conversationClosed.value = false
    handoffActive.value = false
    handoffNote.value = ''
  }
  question.value = ''
  sending.value = true
  handoffNote.value = ''

  messages.value.push({ role: 'visitor', content, citations: [] })
  messages.value.push({ role: 'assistant', content: '', citations: [], pending: true })
  const reply = messages.value[messages.value.length - 1]
  await scrollToBottom()

  try {
    await streamPublicChat(
      props.workspaceSlug,
      { message: content, conversation_id: conversationId.value, visitor_id: visitorId.value },
      {
        onMeta(data) {
          conversationId.value = data.conversation_id
          sessionStorage.setItem(CONVERSATION_KEY, data.conversation_id)
          if (data.visitor_id) visitorId.value = data.visitor_id
          reply.refused = data.refused
          reply.blocked = data.blocked
          if (data.handoff) handoffActive.value = true
        },
        onDelta(chunk) {
          reply.content += chunk
          void scrollToBottom()
        },
        onCitations(citations) {
          reply.citations = citations
          void scrollToBottom()
        },
        onHandoff(note) {
          handoffActive.value = true
          handoffNote.value = note
          void scrollToBottom()
        },
        onDone(data) {
          reply.refused = data.refused
          reply.blocked = data.blocked
          reply.pending = false
          if (data.handoff) startPolling()
        },
      },
    )
  } catch (error) {
    reply.error = true
    reply.content =
      error instanceof ApiError ? error.message : '连接助手失败，请稍后重试或转人工客服。'
  } finally {
    reply.pending = false
    sending.value = false
    void scrollToBottom()
  }
}

function askHuman(): void {
  handoffActive.value = false
  void send('我要转人工客服')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

watch(open, (value) => {
  if (value) {
    ensureVisitorId()
    void loadConfig()
    void scrollToBottom()
  }
})

onMounted(() => {
  restoreConversation()
  void loadConfig()
})

onUnmounted(() => stopPolling())
</script>

<template>
  <div class="chat-widget">
    <Transition name="panel">
      <section
        v-if="open"
        class="chat-panel"
        role="dialog"
        aria-label="HelpFlow 在线客服"
        aria-modal="false"
      >
        <header class="chat-header">
          <div class="brand-avatar" aria-hidden="true">HF</div>
          <div class="brand-copy">
            <strong>HelpFlow 智能助手</strong>
            <span>
              <i class="status-dot"></i>
              {{ handoffActive ? '人工客服服务中 · 回复会同步到这里' : '基于已发布知识库回答 · 引用可查' }}
            </span>
          </div>
          <button class="icon-button" type="button" aria-label="转人工客服" @click="askHuman">
            转人工
          </button>
          <button class="icon-button close" type="button" aria-label="关闭聊天" @click="open = false">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
          </button>
        </header>

        <div ref="logRef" class="chat-log" role="log" aria-live="polite">
          <article class="bubble assistant">
            <div class="answer-text" v-html="renderMarkdown(greeting)"></div>
          </article>

          <p v-if="configError" class="config-error" role="alert">
            {{ configError }}
            <button type="button" @click="loadConfig">重试</button>
          </p>

          <template v-for="(message, index) in messages" :key="index">
            <p v-if="message.role === 'system'" class="system-note">{{ message.content }}</p>
            <article v-else class="bubble" :class="message.role">
              <template v-if="message.role === 'assistant'">
                <div v-if="message.content" class="answer-text markdown-body" v-html="renderMarkdown(message.content)"></div>
                <p v-else-if="message.pending" class="typing" aria-label="正在生成回答">
                  <span></span><span></span><span></span>
                </p>
                <p v-if="message.error" class="bubble-error">请稍后重试，或点击顶部「转人工」。</p>
                <details v-if="message.citations.length" class="citations">
                  <summary>引用 {{ message.citations.length }} 条知识库资料</summary>
                  <ul>
                    <li v-for="citation in message.citations" :key="citation.chunk_id">
                      <span class="citation-index">[{{ citation.index }}]</span>
                      <strong>{{ citation.document_title }}</strong>
                      <p>{{ citation.snippet }}</p>
                    </li>
                  </ul>
                </details>
              </template>
              <template v-else-if="message.role === 'agent'">
                <p class="agent-label">人工客服</p>
                <div class="answer-text markdown-body" v-html="renderMarkdown(message.content)"></div>
              </template>
              <p v-else class="answer-text">{{ message.content }}</p>
            </article>
          </template>

          <article v-if="handoffActive" class="handoff-card">
            <strong>已转接人工客服</strong>
            <p>{{ handoffNote || config?.handoff_note || '客服会在工作时间（周一至周五 9:00-18:00）尽快回复。' }}</p>
          </article>

          <div v-if="showPresets && presetQuestions.length" class="presets">
            <p>你可以这样问</p>
            <button
              v-for="preset in presetQuestions"
              :key="preset"
              type="button"
              @click="send(preset)"
            >
              {{ preset }}
            </button>
          </div>
        </div>

        <form class="composer" @submit.prevent="send()">
          <textarea
            v-model="question"
            rows="1"
            placeholder="输入你的问题…"
            aria-label="输入你的问题"
            @keydown="onKeydown"
          ></textarea>
          <button class="send-button" type="submit" :disabled="sending || !question.trim()" aria-label="发送">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M5 12h13M12 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </form>
        <p class="composer-hint">
          <template v-if="conversationClosed">人工客服已结束会话，继续发送将开启新会话。</template>
          <template v-else>Enter 发送 · Shift + Enter 换行 · AI 回答仅供参考</template>
        </p>
      </section>
    </Transition>

    <button
      v-if="!open"
      class="chat-fab"
      type="button"
      aria-label="打开 HelpFlow 在线客服"
      @click="open = true"
    >
      <span class="fab-ring" aria-hidden="true"></span>
      <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
        <path
          d="M4 6.5A2.5 2.5 0 016.5 4h11A2.5 2.5 0 0120 6.5v7a2.5 2.5 0 01-2.5 2.5H10l-4.6 3.4c-.7.5-1.4 0-1.4-.8V6.5z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linejoin="round"
        />
        <circle cx="9" cy="10" r="1.1" fill="currentColor" />
        <circle cx="13" cy="10" r="1.1" fill="currentColor" />
        <circle cx="17" cy="10" r="1.1" fill="currentColor" />
      </svg>
      <span class="fab-label">在线客服</span>
    </button>
  </div>
</template>

<style scoped>
.chat-widget {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 60;
  font-family: inherit;
}

.chat-fab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.9rem 1.2rem;
  color: #fff;
  font-weight: 700;
  background: linear-gradient(135deg, #356ae6, #1d4ed8);
  border: 0;
  border-radius: 999px;
  box-shadow: 0 16px 34px rgb(24 64 160 / 38%);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.chat-fab:hover {
  transform: translateY(-2px);
  box-shadow: 0 20px 40px rgb(24 64 160 / 46%);
}

.fab-label {
  font-size: 0.92rem;
}

.fab-ring {
  position: absolute;
  inset: -6px;
  border: 2px solid rgb(53 106 230 / 28%);
  border-radius: inherit;
  animation: ring 2.6s ease-out infinite;
}

@keyframes ring {
  0% { transform: scale(0.94); opacity: 0.9; }
  70% { transform: scale(1.16); opacity: 0; }
  100% { transform: scale(1.16); opacity: 0; }
}

.chat-panel {
  display: flex;
  flex-direction: column;
  width: min(400px, calc(100vw - 3rem));
  height: min(640px, calc(100vh - 3rem));
  overflow: hidden;
  background: #fff;
  border: 1px solid #e2e9f5;
  border-radius: 20px;
  box-shadow: 0 30px 70px rgb(18 38 84 / 26%);
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 1rem 1rem 1rem 1.1rem;
  color: #fff;
  background: linear-gradient(135deg, #14213d, #1d3a7a);
}

.brand-avatar {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  font-size: 0.8rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  background: linear-gradient(135deg, #4f8bff, #356ae6);
  border-radius: 12px;
}

.brand-copy {
  display: grid;
  gap: 0.18rem;
  margin-right: auto;
}

.brand-copy strong {
  font-size: 0.95rem;
  line-height: 1.2;
}

.brand-copy span {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  color: #b7c9ef;
  font-size: 0.7rem;
}

.status-dot {
  width: 6px;
  height: 6px;
  background: #34d399;
  border-radius: 50%;
  box-shadow: 0 0 0 3px rgb(52 211 153 / 22%);
}

.icon-button {
  display: inline-flex;
  align-items: center;
  padding: 0.35rem 0.55rem;
  color: #dbe6ff;
  font-size: 0.72rem;
  font-weight: 600;
  background: rgb(255 255 255 / 10%);
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}

.icon-button:hover {
  background: rgb(255 255 255 / 18%);
}

.icon-button.close {
  padding: 0.35rem;
  color: #fff;
  background: transparent;
}

.chat-log {
  flex: 1;
  padding: 1rem;
  overflow-y: auto;
  background:
    radial-gradient(circle at 100% 0, rgb(53 106 230 / 7%), transparent 40%),
    #f7f9fd;
}

.bubble {
  max-width: 88%;
  margin-bottom: 0.75rem;
  padding: 0.72rem 0.9rem;
  font-size: 0.88rem;
  line-height: 1.62;
  border-radius: 14px;
}

.bubble.assistant {
  background: #fff;
  border: 1px solid #e5ecf8;
  border-bottom-left-radius: 4px;
  box-shadow: 0 4px 14px rgb(26 49 96 / 5%);
}

.bubble.visitor {
  margin-left: auto;
  color: #fff;
  background: #356ae6;
  border-bottom-right-radius: 4px;
}

.bubble.agent {
  background: #effaf3;
  border: 1px solid #bfe8cf;
  border-bottom-left-radius: 4px;
}

.agent-label {
  margin-bottom: 0.3rem !important;
  color: #17603a;
  font-size: 0.72rem;
  font-weight: 700;
}

.system-note {
  margin: 0.25rem 0 0.85rem;
  padding: 0.5rem 0.75rem;
  color: #5b6475;
  font-size: 0.76rem;
  line-height: 1.5;
  text-align: center;
  background: #eef1f5;
  border-radius: 8px;
}

.bubble p {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

/* --- Markdown body rendered inside assistant / agent bubbles --- */
.markdown-body :deep(p) {
  margin: 0 0 0.45rem;
  white-space: normal;
  word-break: break-word;
}
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(strong),
.markdown-body :deep(b) { font-weight: 700; }
.markdown-body :deep(em),
.markdown-body :deep(i) { font-style: italic; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.2rem 0 0.5rem;
  padding-left: 1.1rem;
}
.markdown-body :deep(ul) { list-style: disc; }
.markdown-body :deep(ol) { list-style: decimal; }
.markdown-body :deep(li) { margin-bottom: 0.2rem; }
.markdown-body :deep(blockquote) {
  margin: 0.35rem 0;
  padding: 0.3rem 0.6rem;
  color: #63728a;
  font-size: 0.82rem;
  background: #f5f8fe;
  border-left: 3px solid #9bb8ee;
  border-radius: 0 6px 6px 0;
}
.markdown-body :deep(code) {
  padding: 0.08rem 0.35rem;
  color: #b42318;
  font-size: 0.8rem;
  background: #fff2ef;
  border-radius: 4px;
}
.markdown-body :deep(pre) {
  margin: 0.4rem 0;
  padding: 0.6rem 0.75rem;
  overflow-x: auto;
  font-size: 0.78rem;
  line-height: 1.5;
  background: #14213d;
  border-radius: 8px;
}
.markdown-body :deep(pre code) {
  padding: 0;
  color: #e6edff;
  font-size: inherit;
  background: transparent;
}
.markdown-body :deep(a) {
  color: #356ae6;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-body :deep(hr) {
  height: 1px;
  margin: 0.6rem 0;
  background: #e2e9f5;
  border: 0;
}

/* Assistant bubble Markdown 里的段落、代码块、列表在深色 visitor 气泡里保持清晰 */
.bubble.visitor .markdown-body :deep(code) { color: #fff2ef; background: rgb(255 255 255 / 20%); }
.bubble.visitor .markdown-body :deep(a) { color: #dbe6ff; }
.bubble.visitor .markdown-body :deep(blockquote) {
  color: #dbe6ff;
  background: rgb(255 255 255 / 10%);
  border-left-color: #9bb8ee;
}

.bubble-error {
  margin-top: 0.5rem !important;
  color: #b42318;
  font-size: 0.78rem;
}

.typing {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  min-height: 18px;
}

.typing span {
  width: 6px;
  height: 6px;
  background: #8fa6c8;
  border-radius: 50%;
  animation: bounce 1.1s infinite ease-in-out;
}

.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-4px); opacity: 1; }
}

.citations {
  margin-top: 0.65rem;
  padding-top: 0.55rem;
  border-top: 1px dashed #e1e8f4;
}

.citations summary {
  color: #356ae6;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
}

.citations ul {
  display: grid;
  gap: 0.5rem;
  margin: 0.55rem 0 0;
  padding: 0;
  list-style: none;
}

.citations li {
  padding: 0.5rem 0.6rem;
  font-size: 0.74rem;
  line-height: 1.55;
  background: #f5f8fe;
  border-radius: 8px;
}

.citation-index {
  margin-right: 0.25rem;
  color: #356ae6;
  font-weight: 700;
}

.citations strong {
  color: #263a5e;
}

.citations li p {
  margin-top: 0.25rem;
  color: #6a7894;
  white-space: pre-wrap;
}

.handoff-card {
  margin: 0.25rem 0 0.85rem;
  padding: 0.75rem 0.9rem;
  color: #7a4a00;
  background: #fff7e6;
  border: 1px solid #f7dfae;
  border-radius: 12px;
}

.handoff-card strong {
  font-size: 0.82rem;
}

.handoff-card p {
  margin: 0.3rem 0 0;
  font-size: 0.78rem;
  line-height: 1.55;
}

.presets {
  display: grid;
  gap: 0.45rem;
  margin-top: 0.5rem;
}

.presets p {
  margin: 0 0 0.2rem;
  color: #8494ae;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
}

.presets button {
  padding: 0.6rem 0.75rem;
  color: #274474;
  font-size: 0.82rem;
  font-weight: 600;
  text-align: left;
  background: #fff;
  border: 1px solid #dbe5f5;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.presets button:hover {
  background: #eef4ff;
  border-color: #b9cdf3;
}

.config-error {
  margin: 0 0 0.75rem;
  padding: 0.6rem 0.75rem;
  color: #b42318;
  font-size: 0.78rem;
  background: #fff4f2;
  border: 1px solid #f3c9c2;
  border-radius: 10px;
}

.config-error button {
  margin-left: 0.4rem;
  padding: 0.15rem 0.45rem;
  color: #b42318;
  font-size: 0.74rem;
  background: #fff;
  border: 1px solid #e4a9a1;
  border-radius: 6px;
  cursor: pointer;
}

.composer {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
  padding: 0.75rem 0.9rem 0.35rem;
  background: #fff;
  border-top: 1px solid #e8eef8;
}

.composer textarea {
  flex: 1;
  max-height: 120px;
  padding: 0.65rem 0.75rem;
  color: #172033;
  font: inherit;
  font-size: 0.86rem;
  line-height: 1.5;
  resize: none;
  outline: none;
  background: #f5f8fd;
  border: 1px solid #dfe8f6;
  border-radius: 12px;
}

.composer textarea:focus {
  border-color: #9bb8ee;
  box-shadow: 0 0 0 3px rgb(53 106 230 / 10%);
}

.send-button {
  display: grid;
  flex: 0 0 auto;
  width: 40px;
  height: 40px;
  place-items: center;
  color: #fff;
  background: #356ae6;
  border: 0;
  border-radius: 12px;
  cursor: pointer;
}

.send-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.composer-hint {
  margin: 0;
  padding: 0.35rem 0.9rem 0.7rem;
  color: #9aa8c0;
  font-size: 0.66rem;
  text-align: center;
  background: #fff;
}

.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateY(14px) scale(0.98);
}

@media (max-width: 640px) {
  .chat-widget {
    right: 16px;
    bottom: 16px;
  }

  .chat-fab {
    padding: 0.85rem 1rem;
  }

  .chat-panel {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    border: 0;
    border-radius: 0;
  }
}
</style>
