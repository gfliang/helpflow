<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
  fetchEvalRun,
  fetchEvalRuns,
  fetchEvalSummary,
  listAiLogs,
  listAuditLogs,
  type AiCallLog,
  type AuditLog,
  type EvalHistoryPoint,
  type EvalRun,
  type EvalRunDetail,
  type EvalSummary,
} from '@/lib/api'
import { authState } from '@/lib/auth'

type Tab = 'ai' | 'audit' | 'eval'

const modeLabel: Record<string, string> = {
  answer: '知识回答',
  refused: '拒答',
  handoff: '转人工',
  blocked: '敏感词拦截',
  human_waiting: '人工等待',
}

const actionLabel: Record<string, string> = {
  'knowledge.publish': '发布知识',
  'knowledge.archive': '撤回知识',
  'conversation.join': '接入会话',
  'conversation.close': '关闭会话',
  'ticket.create': '创建工单',
  'ticket.update': '更新工单',
}

const successFilters: { value: '' | 'true' | 'false'; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'true', label: '成功' },
  { value: 'false', label: '失败' },
]

const isAdmin = computed(() => authState.session?.workspace.role === 'admin')
const activeTab = ref<Tab>('ai')
const aiLogs = ref<AiCallLog[]>([])
const auditLogs = ref<AuditLog[]>([])
const successFilter = ref<'' | 'true' | 'false'>('')
const loading = ref(false)
const error = ref('')

const evalRuns = ref<EvalRun[]>([])
const evalSummary = ref<EvalSummary | null>(null)
const evalDetail = ref<EvalRunDetail | null>(null)
const evalLoading = ref(false)
const evalDetailLoading = ref(false)

const evalDetailStatus = computed(() => evalDetail.value?.status ?? '')
const evalCases = computed(() => evalDetail.value?.cases ?? [])

const evalStatusLabel: Record<string, string> = {
  completed: '已完成',
  running: '运行中',
  failed: '失败',
}

const refreshLabel = computed(() => {
  if (activeTab.value === 'eval' ? evalLoading.value : loading.value) return '刷新中…'
  return activeTab.value === 'eval' ? '刷新评测' : '刷新日志'
})

const evalHistory = computed<EvalHistoryPoint[]>(() => {
  const points: EvalHistoryPoint[] = evalRuns.value.length
    ? evalRuns.value.map((run) => ({
        id: run.id,
        name: run.name,
        created_at: run.created_at,
        pass_rate: metricNumber(run.metrics, 'pass_rate') ?? runPassRate(run),
      }))
    : (evalSummary.value?.history ?? [])
  return [...points].sort(
    (left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
  )
})

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function describe(detail: Record<string, unknown>): string {
  const entries = Object.entries(detail ?? {})
  if (!entries.length) return '—'
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(' · ')
}

async function loadAi(): Promise<void> {
  loading.value = true
  try {
    aiLogs.value = await listAiLogs({
      limit: 50,
      success: successFilter.value === '' ? undefined : successFilter.value === 'true',
    })
    error.value = ''
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : 'AI 调用日志加载失败。'
  } finally {
    loading.value = false
  }
}

async function loadAudit(): Promise<void> {
  loading.value = true
  try {
    auditLogs.value = await listAuditLogs({ limit: 50 })
    error.value = ''
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '审计日志加载失败。'
  } finally {
    loading.value = false
  }
}

function metricNumber(
  metrics: Record<string, number | string | boolean> | undefined,
  key: string,
): number | null {
  const value = metrics?.[key]
  if (typeof value === 'number') return value
  if (typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value))) {
    return Number(value)
  }
  return null
}

function runPassRate(run: EvalRun): number {
  if (!run.total_cases) return 0
  return run.passed_cases / run.total_cases
}

function formatPercent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function barWidth(value: number | null): number {
  if (value === null) return 0
  return Math.min(100, Math.max(0, value * 100))
}

function evalMetric(key: string): number | null {
  return evalDetail.value ? metricNumber(evalDetail.value.metrics, key) : null
}

function evalPassRate(): number | null {
  if (!evalDetail.value) return null
  return metricNumber(evalDetail.value.metrics, 'pass_rate') ?? runPassRate(evalDetail.value)
}

function evalLatency(): string {
  const value = evalMetric('avg_latency_ms')
  return value === null ? '—' : `${Math.round(value)} ms`
}

function joinDocuments(documents: string[]): string {
  return documents.length ? documents.join('、') : '—'
}

async function loadEvalDetail(id: string): Promise<void> {
  evalDetailLoading.value = true
  try {
    evalDetail.value = await fetchEvalRun(id)
    error.value = ''
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '评测详情加载失败。'
  } finally {
    evalDetailLoading.value = false
  }
}

async function loadEval(): Promise<void> {
  evalLoading.value = true
  try {
    const [runs, summary] = await Promise.all([fetchEvalRuns(10), fetchEvalSummary()])
    evalRuns.value = runs
    evalSummary.value = summary
    error.value = ''
    const targetId = evalDetail.value?.id ?? summary.latest?.id ?? runs[0]?.id ?? null
    if (targetId) await loadEvalDetail(targetId)
    else evalDetail.value = null
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '评测数据加载失败。'
  } finally {
    evalLoading.value = false
  }
}

function selectEvalRun(id: string): void {
  void loadEvalDetail(id)
}

function switchTab(tab: Tab): void {
  activeTab.value = tab
  error.value = ''
  if (tab === 'ai') void loadAi()
  else if (tab === 'audit') void loadAudit()
  else void loadEval()
}

function refreshActive(): void {
  if (activeTab.value === 'ai') void loadAi()
  else if (activeTab.value === 'audit') void loadAudit()
  else void loadEval()
}

function setSuccessFilter(value: '' | 'true' | 'false'): void {
  successFilter.value = value
  void loadAi()
}

onMounted(loadAi)
</script>

<template>
  <section class="logs-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">质量与日志</p>
        <h1>AI 调用、操作审计与质量评测</h1>
        <p class="page-description">
          AI 调用日志记录每一次回答的模式、置信度与耗时，用来排查答非所问。审计日志只对管理员可见，记录知识发布、
          会话处理与工单流转等关键操作。质量评测汇总回归用例的命中率、引用准确率与拒答准确率。
        </p>
      </div>
      <button class="ghost" type="button" :disabled="loading || evalLoading" @click="refreshActive">
        {{ refreshLabel }}
      </button>
    </header>

    <div class="tabs" role="tablist">
      <button
        type="button"
        role="tab"
        class="chip"
        :class="{ active: activeTab === 'ai' }"
        :aria-selected="activeTab === 'ai'"
        @click="switchTab('ai')"
      >
        AI 调用日志
      </button>
      <button
        type="button"
        role="tab"
        class="chip"
        :class="{ active: activeTab === 'audit' }"
        :aria-selected="activeTab === 'audit'"
        @click="switchTab('audit')"
      >
        审计日志{{ isAdmin ? '' : '（仅管理员）' }}
      </button>
      <button
        type="button"
        role="tab"
        class="chip"
        :class="{ active: activeTab === 'eval' }"
        :aria-selected="activeTab === 'eval'"
        @click="switchTab('eval')"
      >
        质量评测
      </button>
    </div>

    <p v-if="error" class="alert" role="alert">{{ error }}</p>

    <template v-if="activeTab === 'ai'">
      <div class="filter-row">
        <button
          v-for="option in successFilters"
          :key="option.label"
          type="button"
          class="chip"
          :class="{ active: successFilter === option.value }"
          @click="setSuccessFilter(option.value)"
        >
          {{ option.label }}
        </button>
      </div>

      <section class="panel">
        <p v-if="!aiLogs.length && !loading" class="empty">
          暂时没有 AI 调用记录。去官网聊天组件提一个问题，日志会自动出现在这里。
        </p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>会话</th>
                <th>模式</th>
                <th>提供方 / 模型</th>
                <th>置信度</th>
                <th>耗时</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in aiLogs" :key="log.id">
                <td>{{ formatDate(log.created_at) }}</td>
                <td>{{ log.conversation_subject || '—' }}</td>
                <td>
                  <span class="badge" :class="`mode-${log.mode}`">{{ modeLabel[log.mode] ?? log.mode }}</span>
                </td>
                <td>
                  <strong>{{ log.provider }}</strong>
                  <small>{{ log.model || '—' }}</small>
                </td>
                <td>{{ log.confidence === null ? '—' : log.confidence.toFixed(2) }}</td>
                <td>{{ log.latency_ms === null ? '—' : `${log.latency_ms} ms` }}</td>
                <td>
                  <span class="badge" :class="log.success ? 'ok' : 'fail'">
                    {{ log.success ? '成功' : '失败' }}
                  </span>
                  <small v-if="log.error">{{ log.error }}</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <template v-else-if="activeTab === 'audit'">
      <section v-if="!isAdmin" class="panel locked">
        <h2>需要管理员权限</h2>
        <p>审计日志记录全工作空间的关键操作，只有管理员可以查看。你可以切换到 AI 调用日志。</p>
      </section>
      <section v-else class="panel">
        <p v-if="!auditLogs.length && !loading" class="empty">
          暂无审计记录。发布知识、接入会话、关闭会话或更新工单后，这里会留下操作痕迹。
        </p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>操作人</th>
                <th>动作</th>
                <th>对象</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in auditLogs" :key="log.id">
                <td>{{ formatDate(log.created_at) }}</td>
                <td>{{ log.actor_name || '系统' }}</td>
                <td>{{ actionLabel[log.action] ?? log.action }}</td>
                <td>{{ log.target_type }}<small v-if="log.target_id">{{ log.target_id.slice(0, 8) }}</small></td>
                <td class="detail-cell">{{ describe(log.detail) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <template v-else>
      <section v-if="!evalRuns.length && !evalSummary?.latest && !evalLoading && !error" class="panel">
        <p class="empty">
          暂无评测记录。在 backend 目录执行 <code>make eval</code> 生成第一份评测报告。
        </p>
      </section>

      <template v-else-if="evalDetail">
        <div class="eval-grid">
          <section class="panel">
            <header class="panel-head">
              <div>
                <h2>{{ evalDetail.name }}</h2>
                <p class="panel-sub">
                  完成于 {{ formatDate(evalDetail.finished_at ?? evalDetail.created_at) }} ·
                  评测器 {{ evalDetail.judge }} · 用例 {{ evalDetail.total_cases }} 条
                </p>
              </div>
              <span
                class="badge"
                :class="
                  evalDetailStatus === 'completed'
                    ? 'ok'
                    : evalDetailStatus === 'failed'
                      ? 'fail'
                      : 'mode-human_waiting'
                "
              >
                {{ evalStatusLabel[evalDetailStatus] ?? evalDetailStatus }}
              </span>
            </header>

            <div class="eval-metrics">
              <div class="eval-metric">
                <span>通过率</span>
                <strong>{{ formatPercent(evalPassRate()) }}</strong>
              </div>
              <div class="eval-metric">
                <span>命中率</span>
                <strong>{{ formatPercent(evalMetric('hit_rate')) }}</strong>
              </div>
              <div class="eval-metric">
                <span>引用准确率</span>
                <strong>{{ formatPercent(evalMetric('citation_accuracy')) }}</strong>
              </div>
              <div class="eval-metric">
                <span>拒答准确率</span>
                <strong>{{ formatPercent(evalMetric('refusal_accuracy')) }}</strong>
              </div>
              <div class="eval-metric">
                <span>忠实度</span>
                <strong>{{ formatPercent(evalMetric('faithfulness')) }}</strong>
              </div>
              <div class="eval-metric">
                <span>平均耗时</span>
                <strong>{{ evalLatency() }}</strong>
              </div>
            </div>
          </section>

          <section class="panel">
            <header class="panel-head">
              <h2>历史趋势</h2>
              <span class="panel-sub">最近 {{ evalHistory.length }} 次运行</span>
            </header>
            <p v-if="!evalHistory.length" class="empty">暂无历史运行。</p>
            <ul v-else class="eval-bars">
              <li v-for="point in evalHistory" :key="point.id">
                <button
                  type="button"
                  class="eval-bar"
                  :class="{ active: evalDetail?.id === point.id }"
                  @click="selectEvalRun(point.id)"
                >
                  <span class="bar-label">{{ formatDate(point.created_at) }}</span>
                  <span class="bar-track">
                    <span class="bar-fill" :style="{ width: `${barWidth(point.pass_rate)}%` }" />
                  </span>
                  <span class="bar-value">{{ formatPercent(point.pass_rate) }}</span>
                </button>
              </li>
            </ul>
          </section>
        </div>

        <section class="panel cases-panel">
          <header class="panel-head">
            <h2>用例明细</h2>
            <span class="panel-sub">
              {{ evalDetail.passed_cases }} / {{ evalDetail.total_cases }} 通过
            </span>
          </header>
          <p v-if="!evalCases.length" class="empty">该次评测没有用例记录。</p>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>问题</th>
                  <th>期望文档</th>
                  <th>实际引用</th>
                  <th>预测模式</th>
                  <th>期望模式</th>
                  <th>是否通过</th>
                  <th>耗时</th>
                  <th>错误</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in evalCases" :key="item.id">
                  <td class="question-cell">{{ item.question }}</td>
                  <td>{{ joinDocuments(item.expected_documents) }}</td>
                  <td>{{ joinDocuments(item.cited_documents) }}</td>
                  <td>{{ modeLabel[item.predicted_mode] ?? item.predicted_mode }}</td>
                  <td>{{ modeLabel[item.expected_mode] ?? item.expected_mode }}</td>
                  <td>
                    <span class="badge" :class="item.passed ? 'ok' : 'fail'">
                      {{ item.passed ? '通过' : '未通过' }}
                    </span>
                  </td>
                  <td>{{ item.latency_ms === null ? '—' : `${item.latency_ms} ms` }}</td>
                  <td class="detail-cell">{{ item.error || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>

      <section v-else class="panel">
        <p class="empty">
          {{ evalLoading || evalDetailLoading ? '正在加载评测数据…' : '评测数据暂时不可用，请稍后刷新重试。' }}
        </p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.logs-page { max-width: 1180px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.page-head h1 { margin: 0; font-size: 2.2rem; }
.page-description { max-width: 760px; color: #63728a; line-height: 1.7; }
.ghost { padding: .55rem .85rem; color: #356ae6; font-size: .85rem; background: #eef3ff; }
.tabs { display: flex; gap: .5rem; margin: 1.5rem 0 1rem; }
.chip { padding: .4rem .8rem; color: #45536b; font-size: .8rem; font-weight: 600; background: #f3f6fb; border: 1px solid #e1e8f4; border-radius: 999px; }
.chip.active { color: white; background: #356ae6; border-color: #356ae6; }
.filter-row { display: flex; gap: .4rem; margin-bottom: 1rem; }
.alert { padding: .75rem 1rem; color: #b42318; background: #fdecec; border: 1px solid #f3c9c2; border-radius: 8px; }
.panel { padding: 1.25rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.locked h2 { margin: 0 0 .5rem; font-size: 1.05rem; }
.locked p { margin: 0; color: #63728a; font-size: .88rem; line-height: 1.7; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .86rem; }
th { padding: .6rem .5rem; color: #66758e; font-size: .74rem; font-weight: 700; letter-spacing: .04em; text-align: left; border-bottom: 1px solid #e5eaf2; }
td { padding: .7rem .5rem; vertical-align: top; border-bottom: 1px solid #eef2f7; }
td small { display: block; margin-top: .15rem; color: #8a97ab; font-size: .72rem; }
.detail-cell { max-width: 300px; color: #66758e; font-size: .78rem; word-break: break-word; }
.badge { display: inline-block; padding: .2rem .5rem; font-size: .72rem; font-weight: 700; white-space: nowrap; border-radius: 999px; }
.mode-answer { color: #17603a; background: #e8f7ee; }
.mode-refused { color: #8a5a00; background: #fff4dc; }
.mode-handoff { color: #5b3a99; background: #f1ecff; }
.mode-blocked { color: #b42318; background: #fdecec; }
.mode-human_waiting { color: #264b96; background: #eef3ff; }
.ok { color: #17603a; background: #e8f7ee; }
.fail { color: #b42318; background: #fdecec; }
.panel-head { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: .5rem .75rem; }
.panel-head h2 { margin: 0; font-size: 1.05rem; }
.panel-sub { margin: .3rem 0 0; color: #66758e; font-size: .78rem; }
.eval-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: 1rem; align-items: start; }
.eval-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; margin-top: 1rem; }
.eval-metric { padding: .7rem .8rem; background: #f8fafd; border: 1px solid #edf1f7; border-radius: 10px; }
.eval-metric span { display: block; color: #66758e; font-size: .72rem; }
.eval-metric strong { display: block; margin-top: .3rem; font-size: 1.05rem; }
.eval-bars { display: grid; gap: .45rem; margin: 1rem 0 0; padding: 0; list-style: none; }
.eval-bar { display: grid; grid-template-columns: 70px minmax(0, 1fr) 54px; align-items: center; gap: .5rem; width: 100%; padding: .35rem .45rem; color: #172033; text-align: left; background: #f8fafd; border: 1px solid #edf1f7; border-radius: 8px; }
.eval-bar:hover { border-color: #c9d8f5; }
.eval-bar.active { background: #eef4ff; border-color: #9bb8ee; }
.bar-label { color: #66758e; font-size: .72rem; font-weight: 500; white-space: nowrap; }
.bar-track { height: 8px; overflow: hidden; background: #e1e8f4; border-radius: 999px; }
.bar-fill { display: block; height: 100%; background: #356ae6; border-radius: 999px; }
.bar-value { color: #45536b; font-size: .74rem; font-weight: 600; text-align: right; }
.cases-panel { margin-top: 1rem; }
.question-cell { max-width: 260px; color: #172033; font-size: .82rem; word-break: break-word; }
.empty code { padding: .1rem .35rem; color: #264b96; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .8rem; background: #eef3ff; border-radius: 4px; }
.empty { margin: 0; padding: 1.5rem 0; color: #66758e; font-size: .88rem; line-height: 1.6; }
@media (max-width: 900px) {
  .eval-grid { grid-template-columns: 1fr; }
  .eval-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .page-head { flex-direction: column; }
  .tabs { flex-wrap: wrap; }
  .eval-bar { grid-template-columns: 62px minmax(0, 1fr) 52px; }
}
@media (max-width: 480px) {
  .eval-metrics { grid-template-columns: 1fr; }
}
</style>
