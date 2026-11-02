<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, register } from '@/lib/api'
import { setSession } from '@/lib/auth'

const router = useRouter()
const name = ref('')
const workspaceName = ref('')
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  error.value = ''
  if (password.value.length < 8) {
    error.value = '密码至少需要 8 位字符。'
    return
  }
  loading.value = true
  try {
    setSession(
      await register({
        email: email.value,
        password: password.value,
        name: name.value.trim(),
        workspace_name: workspaceName.value.trim(),
      }),
    )
    await router.push('/app/dashboard')
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 409) {
      error.value = '该邮箱已被注册，请直接登录。'
    } else if (caught instanceof ApiError && caught.status === 422) {
      error.value = '请检查填写内容：邮箱格式或密码长度（至少 8 位）不符合要求。'
    } else {
      error.value = caught instanceof ApiError ? caught.message : '无法连接 API 服务。'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-brand">
      <p class="eyebrow">HELPFLOW</p>
      <h1>为你的团队创建独立的客服空间。</h1>
      <p>每个工作空间都有自己的知识库、会话、工单与数据看板，成员与数据互不干扰。</p>
    </section>
    <section class="auth-card" aria-labelledby="register-title">
      <p class="eyebrow">新工作空间</p>
      <h2 id="register-title">注册 HelpFlow</h2>
      <form @submit.prevent="submit">
        <label>
          姓名
          <input v-model.trim="name" autocomplete="name" maxlength="120" required />
        </label>
        <label>
          团队名称
          <input v-model.trim="workspaceName" maxlength="120" placeholder="例如：星河科技客服组" required />
        </label>
        <label>
          邮箱
          <input v-model.trim="email" autocomplete="email" type="email" required />
        </label>
        <label>
          密码
          <input v-model="password" autocomplete="new-password" minlength="8" type="password" required />
          <span class="auth-hint">至少 8 位字符</span>
        </label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button :disabled="loading" type="submit">{{ loading ? '正在创建…' : '创建账号并进入工作台' }}</button>
      </form>
      <p class="auth-switch">已有账号？<RouterLink to="/login">返回登录</RouterLink></p>
    </section>
  </main>
</template>
