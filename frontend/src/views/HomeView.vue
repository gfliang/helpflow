<script setup lang="ts">
import { ref } from 'vue'
import ChatWidget from '@/components/ChatWidget.vue'

const chatOpen = ref(false)

const capabilities = [
  {
    index: '01',
    title: '知识库驱动回答',
    text: '只检索已发布文档的切片；追问会结合最近几轮对话改写为独立问题再检索，发布与撤回即时生效。',
  },
  {
    index: '02',
    title: '每句回答都有引用',
    text: '回答末尾标注来源编号，访客可展开查看命中的文档标题与原文片段。',
  },
  {
    index: '03',
    title: '低置信度不编造',
    text: '检索得分低于阈值时直接说明「没有足够依据」，并引导转人工，而不是猜测答案。',
  },
  {
    index: '04',
    title: '识别敏感词与转人工',
    text: '自动识别不友善内容和人工诉求，会话进入待人工队列，保留完整上下文。',
  },
]

const steps = [
  {
    index: '01',
    title: '访客提出一个问题',
    text: '官网右下角的聊天组件无需登录即可使用，输入产品或价格相关问题。',
  },
  {
    index: '02',
    title: '检索、判定与流式回答',
    text: '语义检索已发布知识，命中阈值后通过 SSE 逐字返回答案，并附上可展开的引用。',
  },
  {
    index: '03',
    title: '无依据或人工诉求转接',
    text: '低置信度直接拒答；识别到「转人工」后立即进入人工队列，客服接手完整会话。',
  },
]

const techStack = [
  { name: 'LangChain', detail: 'LCEL 回答链、MultiQuery 检索改写与对话记忆' },
  { name: 'LangGraph', detail: '工具调用 Agent，interrupt 中断 + checkpoint 恢复等待人工审批' },
  { name: 'BGE / fastembed', detail: '本地中文向量模型（bge-small-zh，512 维）离线推理' },
  { name: 'PostgreSQL + pgvector', detail: '切片向量检索、工作空间隔离与 Agent 检查点' },
  { name: 'Vue 3 + Vite', detail: '官网、后台与悬浮聊天组件' },
  { name: 'FastAPI', detail: '公开问答与后台 API，SSE 流式输出' },
  { name: 'Langfuse', detail: '可选的自托管链路追踪，记录每次检索与生成' },
  { name: '评测流水线', detail: '42 条黄金集，统计命中率、引用与拒答准确率' },
]
</script>

<template>
  <div class="site">
    <header class="site-nav">
      <a class="logo" href="#top" aria-label="HelpFlow 首页">
        <span class="logo-mark">HF</span>
        <span>HelpFlow</span>
      </a>
      <nav aria-label="官网导航">
        <a href="#capabilities">产品能力</a>
        <a href="#workflow">工作流程</a>
        <a href="#tech">技术栈</a>
      </nav>
      <div class="nav-actions">
        <button class="ghost-button" type="button" @click="chatOpen = true">立即咨询</button>
        <RouterLink class="primary-link" to="/login">进入工作台</RouterLink>
      </div>
    </header>

    <main id="top">
      <section class="hero">
        <div class="hero-copy">
          <p class="eyebrow">AI CUSTOMER SUPPORT</p>
          <h1>把知识库变成<br /><span>7×24 小时的智能客服。</span></h1>
          <p class="lede">
            HelpFlow 用已发布的知识库回答访客问题，每句回答都可追溯引用；
            遇到低置信度或人工请求时，无缝转接人工客服。
          </p>
          <div class="hero-actions">
            <button class="cta-button" type="button" @click="chatOpen = true">
              立即体验 AI 客服
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d="M5 12h13M12 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
            <RouterLink class="text-link" to="/login">查看客服工作台</RouterLink>
          </div>
          <ul class="hero-points">
            <li>访客无需登录</li>
            <li>只引用已发布知识</li>
            <li>低置信度不编造</li>
          </ul>
        </div>

        <aside
          class="hero-preview"
          role="button"
          tabindex="0"
          aria-label="打开在线客服"
          @click="chatOpen = true"
          @keydown.enter="chatOpen = true"
          @keydown.space.prevent="chatOpen = true"
        >
          <div class="preview-head">
            <span class="preview-dot"></span>
            <strong>在线预览</strong>
            <small>HelpFlow 智能助手</small>
          </div>
          <div class="preview-thread">
            <div class="preview-user">专业版多少钱？</div>
            <div class="preview-ai">
              专业版每月 899 元，包含 3 个工作空间、10 个客服席位和每月 10,000 次 AI 回答
              <span class="cite-mark">[1]</span>
              <span class="preview-cite">引用 · 价格方案与计费方式</span>
            </div>
            <div class="preview-user">今天天气怎么样？</div>
            <div class="preview-ai refused">
              抱歉，我在已发布的知识库中没有找到足够可靠的信息，因此不能凭空回答。
            </div>
          </div>
          <div class="preview-foot">
            <span>点击与真实助手对话</span>
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d="M5 12h13M12 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
        </aside>
      </section>

      <section id="capabilities" class="section">
        <div class="section-head">
          <p class="eyebrow">CAPABILITIES</p>
          <h2>回答有依据，转接有上下文</h2>
          <p>从知识库检索到人工接手，每一步都留下可追溯的记录。</p>
        </div>
        <div class="card-grid">
          <article v-for="capability in capabilities" :key="capability.index" class="capability-card">
            <span class="card-index">{{ capability.index }}</span>
            <h3>{{ capability.title }}</h3>
            <p>{{ capability.text }}</p>
          </article>
        </div>
      </section>

      <section id="workflow" class="workflow">
        <div class="workflow-copy">
          <p class="eyebrow">WORKFLOW</p>
          <h2>一次提问，三步闭环</h2>
          <p>
            访客看到的只是一个聊天框，背后是检索、置信度判定、流式生成和人工队列的完整链路。
          </p>
          <button class="cta-button light" type="button" @click="chatOpen = true">现在问一个问题</button>
        </div>
        <ol class="step-list">
          <li v-for="step in steps" :key="step.index">
            <span>{{ step.index }}</span>
            <div>
              <h3>{{ step.title }}</h3>
              <p>{{ step.text }}</p>
            </div>
          </li>
        </ol>
      </section>

      <section id="tech" class="section tech">
        <div class="section-head">
          <p class="eyebrow">TECH STACK</p>
          <h2>本地可跑通的技术栈</h2>
          <p>
            用 LangChain 组装检索与生成链，用 LangGraph 承载带人工审批的 Agent；
            向量检索走本地 BGE 模型，模型服务支持 OpenRouter、vLLM、Azure OpenAI 等任一 OpenAI 兼容接口。
          </p>
        </div>
        <div class="tech-grid">
          <article v-for="item in techStack" :key="item.name">
            <strong>{{ item.name }}</strong>
            <span>{{ item.detail }}</span>
          </article>
        </div>
      </section>

      <section class="cta-band">
        <div>
          <p class="eyebrow">TRY IT YOURSELF</p>
          <h2>亲自问一句，看看 AI 会不会编造。</h2>
          <p>试试「年度订阅怎么退款？」，再问一个知识库里没有的问题。</p>
        </div>
        <button class="cta-button inverse" type="button" @click="chatOpen = true">打开聊天组件</button>
      </section>
    </main>

    <footer class="site-footer">
      <div class="footer-brand">
        <span class="logo-mark">HF</span>
        <div>
          <strong>HelpFlow</strong>
          <span>AI 智能客服与工单管理系统</span>
        </div>
      </div>
      <p>回答仅基于已发布知识库 · 管理员入口 <RouterLink to="/login">登录</RouterLink></p>
    </footer>

    <ChatWidget v-model:open="chatOpen" />
  </div>
</template>

<style scoped>
.site {
  min-height: 100vh;
  overflow-x: hidden;
  color: #172033;
  background:
    radial-gradient(circle at 8% 4%, rgb(53 106 230 / 12%), transparent 32rem),
    radial-gradient(circle at 92% 10%, rgb(72 187 178 / 10%), transparent 28rem),
    linear-gradient(180deg, #fff 0%, #f5f8fd 55%, #eef3fa 100%);
}

.site-nav {
  display: flex;
  align-items: center;
  gap: 2rem;
  width: min(1180px, calc(100% - 3rem));
  margin: 0 auto;
  padding: 1.35rem 0;
}

.logo {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  color: #172033;
  font-size: 1.15rem;
  font-weight: 800;
  text-decoration: none;
}

.logo-mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  background: linear-gradient(135deg, #356ae6, #1d4ed8);
  border-radius: 10px;
  box-shadow: 0 6px 16px rgb(53 106 230 / 32%);
}

.site-nav nav {
  display: flex;
  gap: 1.6rem;
  margin-left: auto;
}

.site-nav nav a {
  color: #53627c;
  font-size: 0.9rem;
  font-weight: 600;
  text-decoration: none;
}

.site-nav nav a:hover {
  color: #356ae6;
}

.nav-actions {
  display: flex;
  gap: 0.65rem;
  align-items: center;
}

.ghost-button {
  padding: 0.55rem 0.95rem;
  color: #356ae6;
  font-size: 0.86rem;
  font-weight: 700;
  background: rgb(53 106 230 / 9%);
  border: 0;
  border-radius: 999px;
  cursor: pointer;
}

.ghost-button:hover {
  background: rgb(53 106 230 / 15%);
}

.primary-link {
  padding: 0.6rem 1.1rem;
  color: #fff;
  font-size: 0.86rem;
  font-weight: 700;
  text-decoration: none;
  background: #14213d;
  border-radius: 999px;
}

.primary-link:hover {
  background: #24365f;
}

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(340px, 0.9fr);
  gap: clamp(2rem, 6vw, 5rem);
  align-items: center;
  width: min(1180px, calc(100% - 3rem));
  margin: 0 auto;
  padding: clamp(3rem, 8vw, 7rem) 0 clamp(4rem, 8vw, 7rem);
}

.hero h1 {
  margin: 0;
  font-size: clamp(2.6rem, 5.4vw, 4.6rem);
  line-height: 1.08;
  letter-spacing: -0.03em;
}

.hero h1 span {
  color: #356ae6;
}

.lede {
  max-width: 560px;
  margin: 1.5rem 0 0;
  color: #5b6a84;
  font-size: 1.06rem;
  line-height: 1.75;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  margin-top: 2rem;
}

.cta-button {
  display: inline-flex;
  gap: 0.5rem;
  align-items: center;
  padding: 0.8rem 1.25rem;
  color: #fff;
  font-size: 0.92rem;
  font-weight: 700;
  background: #356ae6;
  border: 0;
  border-radius: 11px;
  box-shadow: 0 12px 26px rgb(53 106 230 / 28%);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.cta-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 16px 32px rgb(53 106 230 / 34%);
}

.text-link {
  color: #33415a;
  font-size: 0.9rem;
  font-weight: 600;
  text-decoration: none;
  border-bottom: 1px solid #c9d5e8;
  padding-bottom: 2px;
}

.text-link:hover {
  color: #356ae6;
  border-color: #356ae6;
}

.hero-points {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.2rem;
  margin: 1.6rem 0 0;
  padding: 0;
  color: #6a7894;
  font-size: 0.82rem;
  list-style: none;
}

.hero-points li {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}

.hero-points li::before {
  width: 5px;
  height: 5px;
  content: '';
  background: #48bbb2;
  border-radius: 50%;
}

.hero-preview {
  padding: 1rem;
  background: rgb(255 255 255 / 78%);
  border: 1px solid rgb(213 225 244 / 90%);
  border-radius: 22px;
  box-shadow: 0 28px 70px rgb(23 47 100 / 14%);
  backdrop-filter: blur(14px);
  cursor: pointer;
  transition: transform 0.22s ease, box-shadow 0.22s ease;
}

.hero-preview:hover {
  transform: translateY(-4px);
  box-shadow: 0 34px 80px rgb(23 47 100 / 19%);
}

.hero-preview:focus-visible {
  outline: 3px solid rgb(53 106 230 / 35%);
  outline-offset: 3px;
}

.preview-head {
  display: flex;
  gap: 0.55rem;
  align-items: center;
  padding: 0.2rem 0.35rem 0.8rem;
  border-bottom: 1px solid #e9eff9;
}

.preview-dot {
  width: 8px;
  height: 8px;
  background: #34d399;
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgb(52 211 153 / 16%);
}

.preview-head strong {
  font-size: 0.84rem;
}

.preview-head small {
  margin-left: auto;
  color: #8494ae;
  font-size: 0.72rem;
}

.preview-thread {
  display: grid;
  gap: 0.6rem;
  padding: 0.9rem 0.2rem;
}

.preview-user {
  justify-self: end;
  max-width: 82%;
  padding: 0.55rem 0.75rem;
  color: #fff;
  font-size: 0.8rem;
  line-height: 1.5;
  background: #356ae6;
  border-radius: 12px 12px 4px 12px;
}

.preview-ai {
  max-width: 92%;
  padding: 0.65rem 0.8rem;
  color: #33415a;
  font-size: 0.8rem;
  line-height: 1.65;
  background: #fff;
  border: 1px solid #e5ecf8;
  border-radius: 12px 12px 12px 4px;
  box-shadow: 0 4px 12px rgb(23 47 100 / 4%);
}

.preview-ai.refused {
  color: #7a5a2a;
  background: #fffaf0;
  border-color: #f4e2bb;
}

.cite-mark {
  color: #356ae6;
  font-weight: 700;
}

.preview-cite {
  display: block;
  margin-top: 0.4rem;
  color: #356ae6;
  font-size: 0.68rem;
  font-weight: 600;
}

.preview-foot {
  display: flex;
  gap: 0.4rem;
  align-items: center;
  justify-content: center;
  padding: 0.75rem;
  color: #356ae6;
  font-size: 0.76rem;
  font-weight: 700;
  background: rgb(53 106 230 / 6%);
  border-radius: 11px;
}

.section {
  width: min(1180px, calc(100% - 3rem));
  margin: 0 auto;
  padding: clamp(3.5rem, 7vw, 6rem) 0;
}

.section-head {
  max-width: 680px;
  margin-bottom: 2.4rem;
}

.section-head h2 {
  margin: 0;
  font-size: clamp(1.8rem, 3.4vw, 2.7rem);
  letter-spacing: -0.02em;
}

.section-head p:last-child {
  margin: 0.9rem 0 0;
  color: #63728a;
  font-size: 1rem;
  line-height: 1.7;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
}

.capability-card {
  padding: 1.4rem;
  background: rgb(255 255 255 / 82%);
  border: 1px solid #e3ebf7;
  border-radius: 16px;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.capability-card:hover {
  transform: translateY(-3px);
  border-color: #c6d8f5;
  box-shadow: 0 18px 40px rgb(26 49 96 / 8%);
}

.card-index {
  display: inline-grid;
  width: 34px;
  height: 34px;
  margin-bottom: 1rem;
  place-items: center;
  color: #356ae6;
  font-size: 0.72rem;
  font-weight: 800;
  background: #eef4ff;
  border-radius: 10px;
}

.capability-card h3 {
  margin: 0 0 0.55rem;
  font-size: 1rem;
}

.capability-card p {
  margin: 0;
  color: #66758e;
  font-size: 0.86rem;
  line-height: 1.65;
}

.workflow {
  display: grid;
  grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
  gap: clamp(2rem, 6vw, 5rem);
  align-items: start;
  width: min(1180px, calc(100% - 3rem));
  margin: 1rem auto 0;
  padding: clamp(2.5rem, 5vw, 4rem);
  color: #fff;
  background:
    radial-gradient(circle at 85% 20%, rgb(72 187 178 / 22%), transparent 24rem),
    linear-gradient(135deg, #14213d, #1b3366);
  border-radius: 24px;
}

.workflow-copy h2 {
  margin: 0;
  font-size: clamp(1.9rem, 3.2vw, 2.6rem);
}

.workflow-copy p {
  margin: 1rem 0 1.8rem;
  color: #b7c9ef;
  font-size: 0.98rem;
  line-height: 1.75;
}

.workflow-copy .eyebrow {
  color: #7fd6cf;
}

.cta-button.light {
  color: #14213d;
  background: #fff;
  box-shadow: none;
}

.step-list {
  display: grid;
  gap: 0.7rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-list li {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  padding: 1.1rem 1.2rem;
  background: rgb(255 255 255 / 7%);
  border: 1px solid rgb(255 255 255 / 10%);
  border-radius: 14px;
}

.step-list li > span {
  flex: 0 0 auto;
  color: #7fd6cf;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.step-list h3 {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
}

.step-list p {
  margin: 0;
  color: #b7c9ef;
  font-size: 0.82rem;
  line-height: 1.6;
}

.tech-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
}

.tech-grid article {
  display: grid;
  gap: 0.45rem;
  padding: 1.25rem;
  background: #fff;
  border: 1px solid #e5ecf8;
  border-radius: 14px;
}

.tech-grid strong {
  font-size: 0.93rem;
}

.tech-grid span {
  color: #6a7894;
  font-size: 0.8rem;
  line-height: 1.55;
}

.cta-band {
  display: flex;
  gap: 2rem;
  align-items: center;
  justify-content: space-between;
  width: min(1180px, calc(100% - 3rem));
  margin: clamp(2rem, 5vw, 4rem) auto clamp(3rem, 6vw, 5rem);
  padding: clamp(2rem, 4vw, 3rem);
  background: linear-gradient(135deg, #eaf1ff, #f4fbff);
  border: 1px solid #d8e5f9;
  border-radius: 20px;
}

.cta-band h2 {
  margin: 0;
  font-size: clamp(1.5rem, 2.6vw, 2.1rem);
}

.cta-band p {
  margin: 0.6rem 0 0;
  color: #63728a;
  font-size: 0.92rem;
}

.cta-band .eyebrow {
  margin-bottom: 0.6rem;
}

.cta-button.inverse {
  flex: 0 0 auto;
  color: #fff;
  background: #14213d;
  box-shadow: none;
}

.site-footer {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  justify-content: space-between;
  width: min(1180px, calc(100% - 3rem));
  margin: 0 auto;
  padding: 2rem 0 2.5rem;
  color: #7b89a1;
  font-size: 0.78rem;
  border-top: 1px solid #dde6f3;
}

.footer-brand {
  display: flex;
  gap: 0.7rem;
  align-items: center;
}

.footer-brand div {
  display: grid;
  gap: 0.15rem;
}

.footer-brand strong {
  color: #33415a;
  font-size: 0.9rem;
}

.site-footer p {
  margin: 0;
}

.site-footer a {
  color: #356ae6;
}

@media (max-width: 980px) {
  .hero {
    grid-template-columns: 1fr;
  }

  .hero-preview {
    max-width: 560px;
  }

  .card-grid,
  .tech-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workflow {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .site-nav nav {
    display: none;
  }

  .site-nav {
    width: calc(100% - 2rem);
  }

  .hero,
  .section,
  .workflow,
  .cta-band,
  .site-footer {
    width: calc(100% - 2rem);
  }

  .card-grid,
  .tech-grid {
    grid-template-columns: 1fr;
  }

  .cta-band,
  .site-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .hero-actions {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
