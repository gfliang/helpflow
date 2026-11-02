<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getCurrentUser } from '@/lib/api'
import { clearSession, authState, setSession } from '@/lib/auth'

const router = useRouter()
const navigation = [
  ['概览', '/app/dashboard'], ['会话中心', '/app/conversations'], ['知识库', '/app/knowledge'],
  ['工单中心', '/app/tickets'], ['质量日志', '/app/logs'], ['设置', '/app/settings'],
]

async function logout(): Promise<void> {
  clearSession()
  await router.push('/login')
}

onMounted(async () => {
  const session = authState.session
  if (!session) return
  try {
    const profile = await getCurrentUser()
    setSession({ ...session, user: profile.user, workspace: profile.workspace })
  } catch {
    // 鉴权失败由请求层统一处理，这里不打断页面渲染
  }
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="product-name">HelpFlow</div>
      <p class="workspace-name">{{ authState.session?.workspace.name }}</p>
      <nav aria-label="主导航">
        <RouterLink v-for="[name, path] in navigation" :key="path" :to="path">{{ name }}</RouterLink>
      </nav>
      <div class="account-block">
        <strong>{{ authState.session?.user.name }}</strong>
        <span>{{ authState.session?.workspace.role }}</span>
        <button type="button" @click="logout">退出登录</button>
      </div>
    </aside>
    <main class="app-main"><RouterView /></main>
  </div>
</template>
