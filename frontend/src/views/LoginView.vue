<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, login } from '@/lib/api'
import { setSession } from '@/lib/auth'

const router = useRouter()
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

const quickAccounts = [
  { label: '管理员账号', email: 'admin@helpflow.com' },
  { label: '客服账号', email: 'agent@helpflow.com' },
]
const quickPassword = 'helpflow-demo'

function fillAccount(account: { email: string }): void {
  email.value = account.email
  password.value = quickPassword
  error.value = ''
}

async function submit(): Promise<void> {
  error.value = ''
  loading.value = true
  try {
    setSession(await login(email.value, password.value))
    await router.push('/app/dashboard')
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '无法连接 API 服务。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-brand">
      <p class="eyebrow">HELPFLOW</p>
      <h1>让每一次客户咨询都有回应。</h1>
      <p>AI 解答、人工协同与工单闭环，统一在一个客服工作台中完成。</p>
    </section>
    <section class="auth-card" aria-labelledby="login-title">
      <p class="eyebrow">工作台</p>
      <h2 id="login-title">登录 HelpFlow</h2>
      <form @submit.prevent="submit">
        <label>邮箱<input v-model.trim="email" autocomplete="email" type="email" required /></label>
        <label>密码<input v-model="password" autocomplete="current-password" type="password" required /></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button :disabled="loading" type="submit">{{ loading ? '正在登录…' : '登录' }}</button>
      </form>
      <div class="quick-fill">
        <p class="auth-hint">测试账号，点击自动填入：</p>
        <button v-for="account in quickAccounts" :key="account.email" type="button" @click="fillAccount(account)">
          {{ account.label }}
        </button>
      </div>
      <p class="auth-switch">还没有账号？<RouterLink to="/register">注册新团队</RouterLink></p>
    </section>
  </main>
</template>
