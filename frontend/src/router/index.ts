import { createRouter, createWebHistory } from 'vue-router'
import { authState } from '@/lib/auth'
import AppShell from '@/views/AppShell.vue'
import ConversationView from '@/views/ConversationView.vue'
import DashboardView from '@/views/DashboardView.vue'
import HomeView from '@/views/HomeView.vue'
import KnowledgeView from '@/views/KnowledgeView.vue'
import LoginView from '@/views/LoginView.vue'
import LogsView from '@/views/LogsView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import RegisterView from '@/views/RegisterView.vue'
import SettingsView from '@/views/SettingsView.vue'
import TicketsView from '@/views/TicketsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { public: true } },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/register', name: 'register', component: RegisterView, meta: { public: true } },
    {
      path: '/app',
      component: AppShell,
      children: [
        { path: '', redirect: '/app/dashboard' },
        { path: 'dashboard', component: DashboardView },
        { path: 'conversations', component: ConversationView },
        { path: 'knowledge', component: KnowledgeView },
        { path: 'tickets', component: TicketsView },
        { path: 'logs', component: LogsView },
        { path: 'settings', component: SettingsView },
      ],
    },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView, meta: { public: true } },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !authState.session) return { name: 'login' }
  if (to.name === 'login' && authState.session) return '/app/dashboard'
  if (to.name === 'register' && authState.session) return '/app/dashboard'
  return true
})

export default router
