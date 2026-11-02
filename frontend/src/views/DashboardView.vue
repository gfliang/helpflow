<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
  fetchDashboardSummary,
  type DashboardSummary,
  type DashboardDailyPoint,
} from '@/lib/api'

const summary = ref<DashboardSummary | null>(null)
const loading = ref(true)
const error = ref('')

const maxDaily = computed(() =>
  Math.max(1, ...(summary.value?.daily ?? []).flatMap((point) => [point.conversations, point.ai_answers, point.refusals])),
)

function barHeight(value: number): string {
  return `${Math.max(2, Math.round((value / maxDaily.value) * 100))}%`
}

function percent(value: number): string {
  return `${Math.round(value * 1000) / 10}%`
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function tooltip(point: DashboardDailyPoint): string {
  return `${point.date}：会话 ${point.conversations} · AI 回答 ${point.ai_answers} · 拒答 ${point.refusals}`
}

async function load(): Promise<void> {
  loading.value = true
  try {
    summary.value = await fetchDashboardSummary()
    error.value = ''
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '看板数据加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="dashboard-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">概览</p>
        <h1>服务运行概览</h1>
        <p class="page-description">
          汇总最近 7 天的会话、AI 回答与工单情况。拒答率和知识缺口用来判断知识库下一步需要补充什么。
        </p>
      </div>
      <button class="ghost" type="button" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新数据' }}
      </button>
    </header>

    <p v-if="error" class="alert" role="alert">{{ error }}</p>

    <div v-if="loading && !summary" class="loading">正在加载看板数据…</div>

    <template v-else-if="summary">
      <div class="metric-grid">
        <article>
          <span>总会话数</span>
          <strong>{{ summary.conversations_total }}</strong>
          <small>其中已关闭 {{ summary.closed_conversations }} 个</small>
          <RouterLink class="metric-link" to="/app/conversations">前往会话中心</RouterLink>
        </article>
        <article>
          <span>待人工接入</span>
          <strong>{{ summary.waiting_human }}</strong>
          <small>正在人工处理 {{ summary.human_active }} 个</small>
          <RouterLink class="metric-link" to="/app/conversations">打开待接入队列</RouterLink>
        </article>
        <article>
          <span>未关闭工单</span>
          <strong>{{ summary.tickets_open }}</strong>
          <small>工单总数 {{ summary.tickets_total }} 张</small>
          <RouterLink class="metric-link" to="/app/tickets">前往工单中心</RouterLink>
        </article>
        <article>
          <span>AI 回答</span>
          <strong>{{ summary.ai_answers }}</strong>
          <small>转人工请求 {{ summary.handoff_requests }} 次</small>
          <RouterLink class="metric-link" to="/app/logs">查看 AI 调用日志</RouterLink>
        </article>
        <article>
          <span>拒答率</span>
          <strong>{{ percent(summary.refusal_rate) }}</strong>
          <small>共拒答 {{ summary.refused_answers }} 次</small>
          <RouterLink class="metric-link" to="/app/knowledge">补充知识库</RouterLink>
        </article>
        <article>
          <span>平均置信度</span>
          <strong>{{ summary.avg_confidence === null ? '—' : summary.avg_confidence.toFixed(2) }}</strong>
          <small>仅统计有资料的 AI 回答</small>
        </article>
      </div>

      <div class="dashboard-grid">
        <section class="panel chart-panel">
          <div class="panel-head">
            <h2>近 7 天趋势</h2>
            <div class="legend">
              <span class="dot conversations"></span>会话
              <span class="dot answers"></span>AI 回答
              <span class="dot refusals"></span>拒答
            </div>
          </div>
          <div v-if="summary.daily.length" class="chart">
            <div v-for="point in summary.daily" :key="point.date" class="chart-column">
              <div class="bars">
                <span
                  class="bar conversations"
                  :style="{ height: barHeight(point.conversations) }"
                  :title="tooltip(point)"
                ></span>
                <span
                  class="bar answers"
                  :style="{ height: barHeight(point.ai_answers) }"
                  :title="tooltip(point)"
                ></span>
                <span
                  class="bar refusals"
                  :style="{ height: barHeight(point.refusals) }"
                  :title="tooltip(point)"
                ></span>
              </div>
              <small>{{ point.date }}</small>
            </div>
          </div>
          <p v-else class="empty">最近 7 天还没有会话数据，去官网聊天组件提一个问题试试。</p>
        </section>

        <section class="panel gap-panel">
          <div class="panel-head">
            <h2>知识缺口</h2>
            <span class="panel-hint">近 30 天被拒答的问题</span>
          </div>
          <ul v-if="summary.knowledge_gaps.length" class="gap-list">
            <li v-for="gap in summary.knowledge_gaps" :key="gap.question">
              <p>{{ gap.question }}</p>
              <small>被问到 {{ gap.occurrences }} 次 · 最近 {{ formatDate(gap.last_asked_at) }}</small>
            </li>
          </ul>
          <p v-else class="empty">暂无知识缺口，说明访客的问题都能在已发布知识中找到答案。</p>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.dashboard-page { max-width: 1180px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.page-head h1 { margin: 0; font-size: 2.2rem; }
.page-description { max-width: 760px; color: #63728a; line-height: 1.7; }
.ghost { padding: .55rem .85rem; color: #356ae6; font-size: .85rem; background: #eef3ff; }
.alert { padding: .75rem 1rem; color: #b42318; background: #fdecec; border: 1px solid #f3c9c2; border-radius: 8px; }
.loading { padding: 2rem 0; color: #66758e; }
.metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin: 2rem 0; }
.metric-grid article { display: flex; flex-direction: column; padding: 1.25rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.metric-grid span { color: #66758e; font-size: .82rem; }
.metric-grid strong { margin: .35rem 0; font-size: 2rem; }
.metric-grid small { color: #8a97ab; font-size: .76rem; }
.metric-link { margin-top: auto; padding-top: .8rem; color: #356ae6; font-size: .78rem; font-weight: 600; text-decoration: none; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 1.25rem; align-items: start; }
.panel { padding: 1.25rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
.panel-head h2 { margin: 0; font-size: 1.05rem; }
.panel-hint { color: #8a97ab; font-size: .76rem; }
.legend { display: flex; align-items: center; gap: .35rem; color: #66758e; font-size: .74rem; }
.dot { display: inline-block; width: .55rem; height: .55rem; margin-left: .5rem; border-radius: 2px; }
.dot.conversations, .bar.conversations { background: #356ae6; }
.dot.answers, .bar.answers { background: #1f9d6b; }
.dot.refusals, .bar.refusals { background: #e0a33a; }
.chart { display: flex; align-items: flex-end; gap: .5rem; height: 220px; padding-top: 1.5rem; }
.chart-column { display: flex; flex: 1; flex-direction: column; align-items: center; height: 100%; }
.bars { display: flex; align-items: flex-end; justify-content: center; gap: .2rem; width: 100%; height: 100%; }
.bar { width: 22%; min-height: 2px; border-radius: 3px 3px 0 0; }
.chart-column small { margin-top: .5rem; color: #8a97ab; font-size: .7rem; white-space: nowrap; }
.empty { margin: 0; padding: 1.25rem 0; color: #66758e; font-size: .86rem; line-height: 1.6; }
.gap-list { display: grid; gap: .75rem; margin: 1rem 0 0; padding: 0; list-style: none; }
.gap-list li { padding: .75rem .85rem; background: #f8fafd; border: 1px solid #eef2f7; border-radius: 8px; }
.gap-list p { margin: 0 0 .3rem; color: #33415a; font-size: .86rem; line-height: 1.5; }
.gap-list small { color: #8a97ab; font-size: .74rem; }
@media (max-width: 1100px) { .dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 960px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) {
  .page-head { flex-direction: column; }
  .metric-grid { grid-template-columns: 1fr; }
}
</style>
