<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  ApiError,
  archiveKnowledgeDocument,
  getKnowledgeDocument,
  listKnowledgeDocuments,
  publishKnowledgeDocument,
  testKnowledgeQuery,
  updateKnowledgeDocument,
  uploadKnowledgeDocument,
  type KnowledgeDocument,
  type KnowledgeDocumentDetail,
  type KnowledgeTestResult,
} from '@/lib/api'
import { authState } from '@/lib/auth'

const statusLabel: Record<string, string> = {
  uploading: '解析中',
  processing: '索引中',
  ready: '待发布',
  published: '已发布',
  failed: '失败',
  archived: '已撤回',
}
const typeLabel: Record<string, string> = {
  faq: 'FAQ',
  markdown: 'Markdown',
  text: '纯文本',
  pdf: 'PDF',
}

const documents = ref<KnowledgeDocument[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = computed(() =>
  documents.value.some((document) => ['uploading', 'processing'].includes(document.status)),
)
const canEdit = computed(() => authState.session?.workspace.role !== 'viewer')

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const dragging = ref(false)
const uploading = ref(false)

const ACCEPTED_EXTENSIONS = ['.md', '.txt', '.pdf']
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

const selected = ref<KnowledgeDocumentDetail | null>(null)
const detailLoading = ref(false)
const saving = ref(false)
const editForm = reactive({ title: '', content: '' })

const query = ref('')
const testLimit = ref(4)
const testing = ref(false)
const testResult = ref<KnowledgeTestResult | null>(null)

let pollTimer: number | undefined

function messageOf(value: unknown): string {
  if (value instanceof ApiError) return value.message
  return '操作失败，请稍后重试。'
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    documents.value = await listKnowledgeDocuments()
    if (!silent) error.value = ''
  } catch (value) {
    if (!silent) error.value = messageOf(value)
  } finally {
    loading.value = false
  }
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function pickFile(file: File | null | undefined): void {
  if (!file) return
  error.value = ''
  const name = file.name.toLowerCase()
  if (!ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    error.value = '只支持 .md、.txt、.pdf 文件。'
    return
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    error.value = '文件超过 10 MB，请压缩后再上传。'
    return
  }
  selectedFile.value = file
}

function onFileChange(event: Event): void {
  pickFile((event.target as HTMLInputElement).files?.[0])
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  pickFile(event.dataTransfer?.files?.[0])
}

function clearFile(): void {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function submitUpload(): Promise<void> {
  const file = selectedFile.value
  if (!file) {
    error.value = '请先选择 .md、.txt 或 .pdf 文件。'
    return
  }
  uploading.value = true
  error.value = ''
  try {
    const document = await uploadKnowledgeDocument(file)
    clearFile()
    notice.value = `《${document.title}》已上传，正在解析。`
    await load(true)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    uploading.value = false
  }
}

async function openEditor(document: KnowledgeDocument): Promise<void> {
  if (selected.value?.id === document.id) {
    selected.value = null
    return
  }
  detailLoading.value = true
  try {
    const detail = await getKnowledgeDocument(document.id)
    selected.value = detail
    editForm.title = detail.title
    editForm.content = detail.content ?? ''
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    detailLoading.value = false
  }
}

async function saveEdit(): Promise<void> {
  if (!selected.value) return
  saving.value = true
  error.value = ''
  try {
    const isPdf = selected.value.type === 'pdf'
    const document = await updateKnowledgeDocument(selected.value.id, {
      title: editForm.title.trim(),
      category: selected.value.category ?? '',
      ...(isPdf ? {} : { content: editForm.content }),
    })
    notice.value = isPdf
      ? '文档信息已更新。'
      : `《${document.title}》内容已更新，需要重新发布后才会参与回答。`
    await load(true)
    await openEditor(document)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    saving.value = false
  }
}

async function togglePublish(document: KnowledgeDocument): Promise<void> {
  error.value = ''
  try {
    if (document.status === 'published') {
      if (!window.confirm(`撤回《${document.title}》后，AI 将立即停止引用该文档。确定撤回吗？`)) return
      await archiveKnowledgeDocument(document.id)
      notice.value = `《${document.title}》已撤回，后续回答不会引用该文档。`
    } else {
      await publishKnowledgeDocument(document.id)
      notice.value = `《${document.title}》已发布，可参与在线回答。`
    }
    await load(true)
    if (selected.value?.id === document.id) {
      const detail = await getKnowledgeDocument(document.id)
      selected.value = detail
    }
  } catch (value) {
    error.value = messageOf(value)
  }
}

async function runTest(): Promise<void> {
  if (!query.value.trim()) return
  testing.value = true
  error.value = ''
  try {
    testResult.value = await testKnowledgeQuery(query.value.trim(), testLimit.value)
  } catch (value) {
    error.value = messageOf(value)
  } finally {
    testing.value = false
  }
}

onMounted(async () => {
  await load()
  pollTimer = window.setInterval(() => {
    if (busy.value) void load(true)
  }, 2500)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="knowledge-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">知识库</p>
        <h1>知识与 RAG 测试台</h1>
        <p class="page-description">
          只有已发布的文档会参与客服回答；撤回后立即停止引用。修改内容后需要重新发布才会生效。
        </p>
      </div>
      <button class="ghost" :disabled="loading" type="button" @click="load()">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <div class="knowledge-layout">
      <div class="knowledge-column">
        <section v-if="canEdit" class="panel create-panel">
          <div class="panel-head">
            <h2>添加知识</h2>
            <span>上传文件即可</span>
          </div>
          <form class="upload-form" @submit.prevent="submitUpload">
            <p class="hint">支持 .md、.txt、.pdf，单个文件最大 10 MB，PDF 需要可提取文本。</p>
            <div
              class="file-drop"
              :class="{ active: dragging }"
              @dragenter.prevent="dragging = true"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="onDrop"
            >
              <input ref="fileInput" class="file-input" type="file" accept=".md,.txt,.pdf" @change="onFileChange" />
              <span class="drop-copy" :class="{ picked: selectedFile }">
                <template v-if="selectedFile">
                  <strong>{{ selectedFile.name }}</strong>
                  <small>{{ formatSize(selectedFile.size) }} · 点击可重新选择</small>
                </template>
                <template v-else>
                  <strong>{{ dragging ? '松开即可选择' : '点击选择文件' }}</strong>
                  <small>或把文件从 Finder 拖到这里</small>
                </template>
              </span>
            </div>
            <div class="upload-actions">
              <button class="primary" :disabled="uploading || !selectedFile" type="submit">
                {{ uploading ? '上传中…' : '上传并解析' }}
              </button>
              <button v-if="selectedFile" class="ghost" type="button" :disabled="uploading" @click="clearFile">
                移除
              </button>
            </div>
          </form>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>文档列表</h2>
            <span>{{ documents.length }} 篇</span>
          </div>
          <p v-if="loading && !documents.length" class="empty">正在加载知识文档…</p>
          <p v-else-if="!documents.length" class="empty">
            还没有知识文档。先上传一份 Markdown / 纯文本 / PDF 文件吧。
          </p>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>标题</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="document in documents" :key="document.id">
                  <td>
                    <strong>{{ document.title }}</strong>
                    <small v-if="document.category">{{ document.category }}</small>
                    <small v-if="document.failure_reason" class="failure">{{ document.failure_reason }}</small>
                  </td>
                  <td>{{ typeLabel[document.type] ?? document.type }}</td>
                  <td>
                    <span class="badge" :class="`status-${document.status}`">
                      {{ statusLabel[document.status] ?? document.status }}
                    </span>
                  </td>
                  <td>{{ formatDate(document.updated_at) }}</td>
                  <td class="row-actions">
                    <button
                      v-if="canEdit"
                      class="link"
                      type="button"
                      @click="openEditor(document)"
                    >
                      {{ selected?.id === document.id ? '收起' : detailLoading ? '加载中…' : '编辑' }}
                    </button>
                    <button
                      v-if="canEdit && ['ready', 'archived'].includes(document.status)"
                      class="link"
                      type="button"
                      @click="togglePublish(document)"
                    >
                      发布
                    </button>
                    <button
                      v-if="canEdit && document.status === 'published'"
                      class="link danger"
                      type="button"
                      @click="togglePublish(document)"
                    >
                      撤回
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="selected" class="panel detail-panel">
          <div class="panel-head">
            <div>
              <h2>{{ selected.title }}</h2>
              <span>版本 v{{ selected.version }} · {{ statusLabel[selected.status] }}</span>
            </div>
            <div class="head-actions">
              <button class="ghost" type="button" @click="selected = null">关闭</button>
            </div>
          </div>

          <form class="edit-form" @submit.prevent="saveEdit">
            <label>标题<input v-model="editForm.title" maxlength="255" required /></label>
            <label v-if="selected.type !== 'pdf'">
              内容
              <textarea v-model="editForm.content" rows="10" required />
            </label>
            <p v-else class="hint">PDF 内容不可直接编辑，请重新上传文件。</p>
            <button :disabled="saving" type="submit">{{ saving ? '保存中…' : '保存' }}</button>
          </form>
        </section>
      </div>

      <aside class="panel test-panel">
        <div class="panel-head">
          <h2>检索测试</h2>
          <span>仅检索已发布内容</span>
        </div>
        <p class="hint">输入一个访客问题，查看召回片段与答案预览。</p>
        <form @submit.prevent="runTest">
          <label>
            问题
            <textarea v-model="query" rows="3" maxlength="1000" placeholder="例如：退款怎么申请？" required />
          </label>
          <div class="test-controls">
            <label class="inline">
              召回数量
              <input v-model.number="testLimit" type="number" min="1" max="8" />
            </label>
            <button :disabled="testing || !query.trim()" type="submit">
              {{ testing ? '检索中…' : '开始检索' }}
            </button>
          </div>
        </form>

        <div v-if="testResult" class="test-results">
          <section class="answer-preview">
            <h3>答案预览</h3>
            <p>{{ testResult.answer_preview }}</p>
          </section>
          <h3>召回片段 <span class="count">{{ testResult.matches.length }}</span></h3>
          <p v-if="!testResult.matches" class="empty">
            没有命中已发布知识。可以换一种问法，或先发布相关文档。
          </p>
          <article v-for="(match, index) in testResult.matches" :key="match.chunk_id" class="match">
            <header>
              <strong>#{{ index + 1 }} {{ match.document_title }}</strong>
              <span>相关度 {{ (match.score * 100).toFixed(1) }}%</span>
            </header>
            <p>{{ match.content }}</p>
          </article>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.knowledge-page { max-width: 1280px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.page-head h1 { margin: 0; font-size: 2.2rem; }
.page-description { max-width: 720px; color: #63728a; line-height: 1.7; }
.notice { padding: .75rem 1rem; color: #17603a; background: #e8f7ee; border: 1px solid #bfe8cf; border-radius: 8px; }
.knowledge-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 1.25rem; align-items: start; margin-top: 1.5rem; }
.knowledge-column { display: grid; gap: 1.25rem; }
.panel { padding: 1.35rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; }
.panel-head h2 { margin: 0; font-size: 1.15rem; }
.panel-head span, .panel-head small { color: #66758e; font-size: .82rem; }
.head-actions { display: flex; gap: .5rem; }
.upload-form { display: grid; gap: .9rem; }
.file-drop {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem 1rem;
  background: #f7faff;
  border: 2px dashed #bcd0f5;
  border-radius: 12px;
  cursor: pointer;
  transition: border-color .15s ease, background .15s ease;
}
.file-drop:hover { border-color: #6f97ef; background: #eef3ff; }
.file-drop.active { background: #e3edff; border-color: #356ae6; border-style: solid; }
.file-drop .file-input { position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer; }
.file-drop .drop-copy { position: relative; display: grid; gap: .35rem; text-align: center; color: #356ae6; pointer-events: none; }
.file-drop .drop-copy strong { font-size: 1rem; }
.file-drop .drop-copy small { color: #66758e; font-size: .82rem; }
.file-drop .drop-copy.picked { color: #172033; }
.file-drop .drop-copy.picked strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 34rem; }
.upload-actions { display: flex; gap: .6rem; align-items: center; }
button.primary { padding: .65rem 1rem; color: white; font-weight: 600; background: #356ae6; border: 0; border-radius: 8px; cursor: pointer; }
button.primary:disabled { opacity: .45; cursor: not-allowed; }
textarea { width: 100%; padding: .8rem .9rem; color: #172033; font: inherit; border: 1px solid #cbd5e3; border-radius: 8px; resize: vertical; }
.hint { margin: 0; color: #66758e; font-size: .84rem; line-height: 1.6; }
.ghost { padding: .55rem .85rem; color: #356ae6; background: #eef3ff; }
.ghost:disabled { opacity: .6; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th { padding: .6rem .5rem; color: #66758e; font-size: .76rem; font-weight: 700; letter-spacing: .04em; text-align: left; border-bottom: 1px solid #e5eaf2; }
td { padding: .75rem .5rem; vertical-align: top; border-bottom: 1px solid #eef2f7; }
td small { display: block; margin-top: .2rem; color: #66758e; }
td small.failure { color: #b42318; }
.row-actions { white-space: nowrap; }
.link { padding: 0; margin-right: .7rem; color: #356ae6; font-size: .82rem; font-weight: 600; background: transparent; }
.link.danger { color: #b42318; }
.badge { display: inline-block; padding: .2rem .5rem; font-size: .75rem; font-weight: 700; border-radius: 999px; }
.status-uploading, .status-processing { color: #8a5a00; background: #fff4dc; }
.status-ready { color: #264b96; background: #eef3ff; }
.status-published { color: #17603a; background: #e8f7ee; }
.status-failed { color: #b42318; background: #fdecec; }
.status-archived { color: #5b6475; background: #eef1f5; }
.empty { margin: 0; padding: 1.25rem 0; color: #66758e; font-size: .88rem; }
.edit-form { display: grid; gap: .9rem; }
.test-panel { position: sticky; top: 1.5rem; }
.test-controls { display: flex; align-items: end; gap: .75rem; }
.test-controls label.inline { flex: 0 0 92px; }
.test-results { display: grid; gap: .9rem; margin-top: 1.5rem; }
.test-results h3 { margin: 0; font-size: .95rem; }
.test-results .count { color: #66758e; font-weight: 400; }
.answer-preview { padding: 1rem; background: #f2f6ff; border: 1px solid #dbe6ff; border-radius: 10px; }
.answer-preview p { margin: .5rem 0 0; font-size: .88rem; line-height: 1.7; white-space: pre-wrap; }
.match { padding: .9rem; border: 1px solid #eef2f7; border-radius: 9px; }
.match header { display: flex; justify-content: space-between; gap: .75rem; margin-bottom: .5rem; font-size: .8rem; }
.match header span { color: #356ae6; white-space: nowrap; }
.match p { margin: 0; font-size: .85rem; line-height: 1.65; white-space: pre-wrap; }
@media (max-width: 1100px) {
  .knowledge-layout { grid-template-columns: 1fr; }
  .test-panel { position: static; }
}
@media (max-width: 720px) {
  .page-head { flex-direction: column; }
}
</style>
