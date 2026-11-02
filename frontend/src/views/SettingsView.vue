<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, listMembers, type Member } from '@/lib/api'
import { authState } from '@/lib/auth'

const members = ref<Member[]>([])
const error = ref('')
const loading = ref(true)

const roleLabel: Record<Member['role'], string> = { admin: '管理员', agent: '客服', viewer: '只读' }

onMounted(async () => {
  try {
    members.value = await listMembers()
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '成员列表加载失败。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="settings-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">设置</p>
        <h1>工作空间与接入</h1>
        <p class="page-description">
          当前版本展示工作空间信息、客服成员与嵌入代码。品牌色、欢迎语和 AI 策略的在线编辑会在后续版本开放。
        </p>
      </div>
    </header>

    <p v-if="error" class="alert" role="alert">{{ error }}</p>

    <div class="settings-grid">
      <section class="panel">
        <h2>工作空间</h2>
        <dl>
          <div><dt>名称</dt><dd>{{ authState.session?.workspace.name }}</dd></div>
          <div><dt>标识（slug）</dt><dd><code>{{ authState.session?.workspace.slug }}</code></dd></div>
          <div><dt>我的角色</dt><dd>{{ authState.session ? roleLabel[authState.session.workspace.role] : '—' }}</dd></div>
        </dl>
      </section>

      <section class="panel">
        <h2>嵌入代码</h2>
        <p>把下面的代码放到企业网站 <code>&lt;/body&gt;</code> 之前，官网右下角就会出现客服组件。</p>
        <pre>&lt;script src="https://cdn.helpflow.com/widget.js"
        data-workspace="{{ authState.session?.workspace.slug }}"
        async&gt;&lt;/script&gt;</pre>
        <p class="hint">把组件接入你的网站后，访客可在右下角直接提问并转接人工客服。</p>
      </section>

      <section class="panel members-panel">
        <h2>客服成员</h2>
        <p v-if="loading" class="hint">正在加载成员…</p>
        <p v-else-if="!members.length" class="hint">当前工作空间还没有成员。</p>
        <ul v-else>
          <li v-for="member in members" :key="member.id">
            <strong>{{ member.name }}</strong>
            <span>{{ member.email }}</span>
            <span class="badge">{{ roleLabel[member.role] }}</span>
          </li>
        </ul>
      </section>

      <section class="panel">
        <h2>运行配置</h2>
        <dl>
          <div><dt>AI 提供方</dt><dd>优先 OpenRouter，也支持任意 OpenAI 兼容接口（vLLM、LM Studio、Azure）</dd></div>
          <div><dt>访客限流</dt><dd>默认每个访客每分钟 30 次提问</dd></div>
          <div><dt>登录限流</dt><dd>默认每个 IP + 邮箱每分钟 12 次尝试</dd></div>
        </dl>
      </section>
    </div>
  </section>
</template>

<style scoped>
.settings-page { max-width: 1100px; }
.page-head h1 { margin: 0; font-size: 2.2rem; }
.page-description { max-width: 760px; color: #63728a; line-height: 1.7; }
.alert { padding: .75rem 1rem; color: #b42318; background: #fdecec; border: 1px solid #f3c9c2; border-radius: 8px; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.25rem; margin-top: 1.5rem; }
.panel { padding: 1.25rem; background: white; border: 1px solid #e5eaf2; border-radius: 12px; }
.panel h2 { margin: 0 0 .75rem; font-size: 1.05rem; }
.panel p { margin: 0 0 .75rem; color: #63728a; font-size: .86rem; line-height: 1.7; }
dl { display: grid; gap: .7rem; margin: 0; }
dl div { display: flex; justify-content: space-between; gap: 1rem; font-size: .86rem; }
dt { color: #66758e; }
dd { margin: 0; color: #172033; text-align: right; }
code { padding: .1rem .35rem; color: #264b96; background: #eef3ff; border-radius: 4px; }
pre { margin: 0 0 .75rem; padding: .85rem; color: #dce7ff; font-size: .76rem; line-height: 1.6; white-space: pre-wrap; word-break: break-all; background: #14213d; border-radius: 8px; }
.hint { color: #8a97ab !important; font-size: .8rem !important; }
ul { display: grid; gap: .6rem; margin: 0; padding: 0; list-style: none; }
li { display: grid; grid-template-columns: 1fr auto; gap: .1rem .75rem; padding: .7rem .8rem; background: #f8fafd; border-radius: 8px; font-size: .84rem; }
li span { color: #66758e; font-size: .78rem; }
.badge { padding: .15rem .45rem; color: #264b96; font-size: .72rem; font-weight: 700; background: #eef3ff; border-radius: 999px; }
@media (max-width: 960px) { .settings-grid { grid-template-columns: 1fr; } }
</style>
