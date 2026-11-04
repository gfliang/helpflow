<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { addMember, ApiError, listMembers, updateMemberRole, type Member } from '@/lib/api'
import { authState } from '@/lib/auth'

const members = ref<Member[]>([])
const error = ref('')
const notice = ref('')
const loading = ref(true)

const roleLabel: Record<Member['role'], string> = { admin: '管理员', agent: '客服', viewer: '只读' }
const roleOptions: Member['role'][] = ['admin', 'agent', 'viewer']

const isAdmin = computed(() => authState.session?.workspace.role === 'admin')

const inviteEmail = ref('')
const inviteName = ref('')
const inviteRole = ref<Member['role']>('agent')
const inviting = ref(false)
const savingMemberId = ref('')

async function loadMembers() {
  try {
    members.value = await listMembers()
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '成员列表加载失败。'
  } finally {
    loading.value = false
  }
}

async function submitInvite() {
  error.value = ''
  notice.value = ''
  if (!inviteEmail.value.trim() || !inviteName.value.trim()) {
    error.value = '请填写成员邮箱和姓名。'
    return
  }
  inviting.value = true
  try {
    await addMember({
      email: inviteEmail.value.trim(),
      name: inviteName.value.trim(),
      role: inviteRole.value,
    })
    notice.value = `已把 ${inviteEmail.value.trim()} 加入工作空间，角色为「${roleLabel[inviteRole.value]}」。`
    inviteEmail.value = ''
    inviteName.value = ''
    inviteRole.value = 'agent'
    await loadMembers()
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '邀请失败，请稍后重试。'
  } finally {
    inviting.value = false
  }
}

async function changeRole(member: Member, event: Event) {
  const nextRole = (event.target as HTMLSelectElement).value as Member['role']
  if (nextRole === member.role) return
  error.value = ''
  notice.value = ''
  savingMemberId.value = member.id
  try {
    await updateMemberRole(member.id, nextRole)
    member.role = nextRole
    notice.value = `已将 ${member.name} 的角色调整为「${roleLabel[nextRole]}」。`
  } catch (value) {
    error.value = value instanceof ApiError ? value.message : '角色调整失败，请稍后重试。'
    ;(event.target as HTMLSelectElement).value = member.role
  } finally {
    savingMemberId.value = ''
  }
}

onMounted(loadMembers)
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
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>

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
        <p v-if="!isAdmin" class="hint">成员邀请与角色调整仅管理员可操作，你当前是只读视图。</p>
        <form v-if="isAdmin" class="invite-form" @submit.prevent="submitInvite">
          <input v-model="inviteEmail" type="email" placeholder="成员邮箱（需已注册）" required />
          <input v-model="inviteName" type="text" placeholder="成员姓名" required />
          <select v-model="inviteRole">
            <option v-for="role in roleOptions" :key="role" :value="role">{{ roleLabel[role] }}</option>
          </select>
          <button type="submit" :disabled="inviting">{{ inviting ? '邀请中…' : '邀请成员' }}</button>
        </form>
        <p v-if="loading" class="hint">正在加载成员…</p>
        <p v-else-if="!members.length" class="hint">当前工作空间还没有成员。</p>
        <ul v-else>
          <li v-for="member in members" :key="member.id">
            <strong>{{ member.name }}</strong>
            <span>{{ member.email }}</span>
            <select
              v-if="isAdmin"
              class="role-select"
              :value="member.role"
              :disabled="savingMemberId === member.id"
              @change="changeRole(member, $event)"
            >
              <option v-for="role in roleOptions" :key="role" :value="role">{{ roleLabel[role] }}</option>
            </select>
            <span v-else class="badge">{{ roleLabel[member.role] }}</span>
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
.notice { padding: .75rem 1rem; color: #175cd3; background: #eef4ff; border: 1px solid #c7dafc; border-radius: 8px; }
.invite-form { display: grid; grid-template-columns: 1.4fr 1fr .8fr auto; gap: .6rem; margin-bottom: 1rem; }
.invite-form input, .invite-form select, .role-select { padding: .5rem .65rem; font-size: .82rem; border: 1px solid #d5ddea; border-radius: 8px; }
.invite-form button { padding: .5rem 1rem; color: white; font-size: .82rem; font-weight: 600; background: #264b96; border: none; border-radius: 8px; cursor: pointer; }
.invite-form button:disabled { opacity: .6; cursor: default; }
.role-select { color: #264b96; font-weight: 700; background: #eef3ff; border-color: #c7dafc; }
@media (max-width: 720px) { .invite-form { grid-template-columns: 1fr 1fr; } }
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
