<script setup lang="ts">
import { authState } from '@/lib/auth'
</script>

<template>
  <section class="not-found">
    <p class="eyebrow">404</p>
    <h1>这个页面不存在</h1>
    <p class="page-description">
      链接可能已经过期，或者地址输入有误。你可以回到首页，或直接进入后台继续处理会话与工单。
    </p>
    <div class="actions">
      <RouterLink class="primary" to="/">返回官网</RouterLink>
      <RouterLink v-if="authState.session" class="ghost" to="/app/dashboard">进入后台</RouterLink>
      <RouterLink v-else class="ghost" to="/login">登录后台</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.not-found { max-width: 620px; margin: 8vh auto 0; padding: 2rem; text-align: center; }
.not-found h1 { margin: 0 0 .5rem; font-size: 2rem; }
.page-description { color: #63728a; line-height: 1.7; }
.actions { display: flex; justify-content: center; gap: .75rem; margin-top: 1.5rem; }
.actions a { padding: .8rem 1.2rem; font-weight: 700; text-decoration: none; border-radius: 8px; }
.primary { color: white; background: #356ae6; }
.ghost { color: #356ae6; background: #eef3ff; }
</style>
