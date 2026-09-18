<script setup>
import MarkdownIt from 'markdown-it'
import { ref, computed, nextTick, onMounted } from 'vue'
import { v4 as uuidv4 } from 'uuid'

const STORAGE_KEY = 'chatGroups'
const LEGACY_PERSONA_STORAGE_KEY = 'chatGroupPersonas'
const LEGACY_MAX_ROUNDS_STORAGE_KEY = 'chatGroupMaxRounds'
const MAIN_CHAT_ID = 'e6ead6c0-9188-4fdd-b82d-51dbeeb283b3'
const DEFAULT_MAX_ROUNDS = 5
const DEFAULT_MESSAGES = [{ role: 'assistant', content: '你好，有什么可以帮你的？' }]
const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true
})

const members = [
  {
    name: '产品经理',
    persona: '工作上关注用户需求、产品边界和投入产出，能把模糊想法整理成方案；生活里爱刷新产品、看综艺和观察消费趋势；说话轻松务实，喜欢用例子解释问题，必要时才切到正式分析。'
  },
  {
    name: '项目经理',
    persona: '工作上关注进度、排期、风险和资源协调，习惯提前发现延期苗头；生活里爱做计划，也会吐槽计划赶不上变化；说话直接但不端着，闲聊时像靠谱朋友，聊项目时会迅速抓重点。'
  },
  {
    name: 'PMO',
    persona: '工作上熟悉流程、人力池和项目治理，擅长看团队负载和风险汇总；生活里喜欢整理清单、安排聚会和复盘日常；说话有条理但不官腔，闲聊时会带一点冷幽默。'
  },
  {
    name: '后端开发',
    persona: '工作上熟悉服务、数据库、接口和业务逻辑，容易看到技术坑和边界条件；生活里爱折腾工具、游戏和硬件，也会吐槽需求变更；说话偏直白，闲聊时随意，聊技术时会给具体判断。'
  },
  {
    name: '前端开发',
    persona: '工作上关注页面体验、交互细节、兼容性和实现成本，能发现用户操作里的别扭点；生活里喜欢设计感强的东西、效率工具和好看的界面；说话有画面感，轻松，会把复杂问题讲得接地气。'
  },
  {
    name: '测试工程师',
    persona: '工作上关注质量、边界场景、回归成本和隐藏风险，习惯从异常路径看问题；生活里细心，爱找细节和反常识的点；说话不绕，偶尔吐槽，但不是故意挑刺，闲聊时也会自然接梗。'
  },
  {
    name: '架构师',
    persona: '工作上关注系统性能、扩展性、稳定性和长期演进，能识别重大技术风险；生活里爱研究复杂系统、历史和新技术趋势；说话沉稳但不摆架子，闲聊时会先顺着聊，必要时再抽象总结。'
  },
  {
    name: '业务负责人',
    persona: '工作上代表业务方，关注业务目标、成本收益和决策落地，能拍板取舍；生活里关注市场、客户、人情世故和现实约束；说话接地气，有判断力，闲聊时不打官腔，聊业务时会很明确。'
  }
]
const defaultMemberByName = new Map(members.map(member => [member.name, member]))

const groups = ref([])
const selectedGroupId = ref(MAIN_CHAT_ID)
const selectedGroup = computed(() => groups.value.find(g => g.id === selectedGroupId.value))
const isMainChat = computed(() => selectedGroupId.value === MAIN_CHAT_ID)
const currentUserPersona = computed({
  get() {
    return selectedGroup.value?.userPersona || ''
  },
  set(value) {
    if (!selectedGroup.value) return
    selectedGroup.value.userPersona = value
    saveGroups()
  }
})
const currentMaxRounds = computed({
  get() {
    return selectedGroup.value?.maxRounds || DEFAULT_MAX_ROUNDS
  },
  set(value) {
    if (!selectedGroup.value) return
    selectedGroup.value.maxRounds = normalizeMaxRounds(value)
    saveGroups()
  }
})

function normalizeMaxRounds(value) {
  return Math.min(100, Math.max(1, Number(value) || DEFAULT_MAX_ROUNDS))
}

function parseStoredJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

function normalizeMembers(groupMembers) {
  if (!Array.isArray(groupMembers)) return []

  return groupMembers.map(member => {
    const defaultMember = defaultMemberByName.get(member?.name)
    return defaultMember ? { ...member, persona: defaultMember.persona } : member
  })
}

function normalizeGroup(group, legacyPersonas, legacyMaxRounds) {
  return {
    ...group,
    userPersona:
      typeof group.userPersona === 'string'
        ? group.userPersona
        : legacyPersonas[group.id] || '',
    maxRounds: normalizeMaxRounds(
      group.maxRounds ?? legacyMaxRounds[group.id] ?? DEFAULT_MAX_ROUNDS
    ),
    members: normalizeMembers(group.members)
  }
}

function migrateGroups(rawGroups) {
  const legacyPersonas = parseStoredJson(LEGACY_PERSONA_STORAGE_KEY, {})
  const legacyMaxRounds = parseStoredJson(LEGACY_MAX_ROUNDS_STORAGE_KEY, {})
  const nextGroups = rawGroups.map(group => normalizeGroup(group, legacyPersonas, legacyMaxRounds))

  if (
    nextGroups.length !== rawGroups.length ||
    nextGroups.some((group, index) => {
      const rawGroup = rawGroups[index]
      return (
        group.userPersona !== rawGroup.userPersona ||
        group.maxRounds !== rawGroup.maxRounds ||
        group.members !== rawGroup.members
      )
    })
  ) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextGroups))
  }

  localStorage.removeItem(LEGACY_PERSONA_STORAGE_KEY)
  localStorage.removeItem(LEGACY_MAX_ROUNDS_STORAGE_KEY)

  return nextGroups
}

function createGroupConfig() {
  return {
    id: uuidv4(),
    name: groupName.value.trim(),
    intro: groupIntro.value.trim(),
    members: selectedMembers.value.map(idx => members[idx]),
    userPersona: '',
    maxRounds: DEFAULT_MAX_ROUNDS,
    createdAt: Date.now()
  }
}

function loadGroups() {
  const storedGroups = parseStoredJson(STORAGE_KEY, [])
  groups.value = Array.isArray(storedGroups) ? migrateGroups(storedGroups) : []
  selectedGroupId.value = MAIN_CHAT_ID
}

function saveGroups() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(groups.value))
}

function historyUrl(threadId) {
  const basePath = threadId === MAIN_CHAT_ID ? '/api/agent/history' : '/api/group-chat/history'
  return `${basePath}?thread_id=${encodeURIComponent(threadId)}`
}

function streamChatUrl(threadId) {
  return threadId === MAIN_CHAT_ID ? '/api/agent/chat' : '/api/group-chat/chat/stream'
}

function buildChatPayload(threadId, content) {
  if (threadId === MAIN_CHAT_ID) {
    return {
      thread_id: threadId,
      message: content
    }
  }

  const group = groups.value.find(item => item.id === threadId)
  return {
    thread_id: threadId,
    message: content,
    group_intro: group?.intro || '',
    user_persona: group?.userPersona || '',
    members: group?.members || [],
    max_rounds: group?.maxRounds || DEFAULT_MAX_ROUNDS
  }
}

const messages = ref([...DEFAULT_MESSAGES])
const messageInput = ref('')
const sendingThreadIds = ref([])
const deletingThreadIds = ref([])
const isLoadingHistory = ref(false)
let historyRequestId = 0

const showModal = ref(false)
const groupName = ref('')
const groupIntro = ref('')
const selectedMembers = ref([])

const showInviteModal = ref(false)
const inviteSelected = ref([])

const availableMembers = computed(() => {
  if (!selectedGroup.value) return []
  const existing = new Set(selectedGroup.value.members.map(m => m.name))
  return members.filter(m => !existing.has(m.name))
})
const isCurrentSending = computed(() => sendingThreadIds.value.includes(selectedGroupId.value))

function isDeletingThread(threadId) {
  return deletingThreadIds.value.includes(threadId)
}

function setThreadSending(threadId, sending) {
  if (sending) {
    if (!sendingThreadIds.value.includes(threadId)) {
      sendingThreadIds.value = [...sendingThreadIds.value, threadId]
    }
    return
  }

  sendingThreadIds.value = sendingThreadIds.value.filter(id => id !== threadId)
}

function setThreadDeleting(threadId, deleting) {
  if (deleting) {
    if (!deletingThreadIds.value.includes(threadId)) {
      deletingThreadIds.value = [...deletingThreadIds.value, threadId]
    }
    return
  }

  deletingThreadIds.value = deletingThreadIds.value.filter(id => id !== threadId)
}

function renderMarkdown(content) {
  return markdown.render(content || '')
}

function parseSseEvent(rawEvent) {
  const event = { type: 'message', data: '' }
  const dataLines = []

  for (const line of rawEvent.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      event.type = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }

  event.data = dataLines.join('\n')
  return event
}

async function handleGroupChatStream(response, threadId) {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('浏览器不支持流式响应')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary).trim()
      buffer = buffer.slice(boundary + 2)

      if (rawEvent) {
        const event = parseSseEvent(rawEvent)
        if (event.type === 'done') {
          return
        }

        if (event.type === 'error') {
          const data = JSON.parse(event.data)
          throw new Error(data.detail || '群聊流式响应失败')
        }

        if (event.type === 'message' && selectedGroupId.value === threadId) {
          messages.value.push(JSON.parse(event.data))
          await scrollMessagesToBottom()
        }
      }

      boundary = buffer.indexOf('\n\n')
    }

    if (done) break
  }
}

async function handleMainChatStream(response, threadId) {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('浏览器不支持流式响应')
  }

  const decoder = new TextDecoder()
  let buffer = ''
  let assistantIndex = -1

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary).trim()
      buffer = buffer.slice(boundary + 2)

      if (rawEvent) {
        const event = parseSseEvent(rawEvent)
        if (event.type === 'done') {
          return
        }

        const data = JSON.parse(event.data)

        if (event.type === 'error') {
          throw new Error(data.detail || '主对话流式响应失败')
        }

        if (selectedGroupId.value === threadId && event.type === 'token') {
          if (assistantIndex === -1) {
            messages.value.push({ role: 'assistant', content: '' })
            assistantIndex = messages.value.length - 1
          }
          messages.value[assistantIndex].content += data.token || ''
          await scrollMessagesToBottom()
        }

        if (selectedGroupId.value === threadId && event.type === 'message') {
          if (assistantIndex === -1) {
            messages.value.push(data)
            assistantIndex = messages.value.length - 1
          } else {
            messages.value[assistantIndex] = data
          }
          await scrollMessagesToBottom()
        }
      }

      boundary = buffer.indexOf('\n\n')
    }

    if (done) break
  }
}

async function scrollMessagesToBottom() {
  await nextTick()
  const container = document.querySelector('.chat-messages')
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

async function loadHistory(threadId) {
  const requestId = ++historyRequestId
  isLoadingHistory.value = true

  try {
    const response = await fetch(historyUrl(threadId))

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`)
    }

    const data = await response.json()
    if (requestId !== historyRequestId) return

    messages.value = data.messages.length > 0 ? data.messages : [...DEFAULT_MESSAGES]
    await scrollMessagesToBottom()
  } catch (error) {
    if (requestId !== historyRequestId) return

    messages.value = [
      {
        role: 'assistant',
        content: `聊天记录加载失败：${error instanceof Error ? error.message : '未知错误'}`
      }
    ]
  } finally {
    if (requestId === historyRequestId) {
      isLoadingHistory.value = false
    }
  }
}

function selectGroup(id) {
  if (selectedGroupId.value === id) return
  selectedGroupId.value = id
  messageInput.value = ''
  loadHistory(id)
}

function openModal() {
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  groupName.value = ''
  groupIntro.value = ''
  selectedMembers.value = []
}

function confirmCreate() {
  if (!groupName.value.trim()) return
  const newGroup = createGroupConfig()
  groups.value.push(newGroup)
  saveGroups()
  selectGroup(newGroup.id)
  closeModal()
}

function toggleMember(index) {
  const pos = selectedMembers.value.indexOf(index)
  if (pos > -1) {
    selectedMembers.value.splice(pos, 1)
  } else {
    selectedMembers.value.push(index)
  }
}

function openInviteModal() {
  inviteSelected.value = []
  showInviteModal.value = true
}

function closeInviteModal() {
  showInviteModal.value = false
  inviteSelected.value = []
}

function toggleInviteMember(name) {
  const pos = inviteSelected.value.indexOf(name)
  if (pos > -1) {
    inviteSelected.value.splice(pos, 1)
  } else {
    inviteSelected.value.push(name)
  }
}

function confirmInvite() {
  if (!selectedGroup.value || inviteSelected.value.length === 0) return
  const toAdd = availableMembers.value.filter(m => inviteSelected.value.includes(m.name))
  selectedGroup.value.members.push(...toAdd)
  saveGroups()
  closeInviteModal()
}

function removeMember(member) {
  if (!selectedGroup.value) return
  selectedGroup.value.members = selectedGroup.value.members.filter(m => m.name !== member.name)
  saveGroups()
}

async function deleteGroup(group) {
  if (isDeletingThread(group.id) || sendingThreadIds.value.includes(group.id)) return
  if (!window.confirm(`确认删除「${group.name}」及其聊天记录吗？`)) return

  setThreadDeleting(group.id, true)
  try {
    const response = await fetch(
      `/api/group-chat/history?thread_id=${encodeURIComponent(group.id)}`,
      { method: 'DELETE' }
    )
    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`)
    }

    groups.value = groups.value.filter(item => item.id !== group.id)
    saveGroups()

    if (selectedGroupId.value === group.id) {
      selectGroup(MAIN_CHAT_ID)
    }
  } catch (error) {
    window.alert(`删除失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    setThreadDeleting(group.id, false)
  }
}

async function sendMessage() {
  const content = messageInput.value.trim()
  if (!content || isCurrentSending.value || isLoadingHistory.value) return

  const threadId = selectedGroupId.value
  messages.value.push({ role: 'user', content })
  messageInput.value = ''
  setThreadSending(threadId, true)
  await scrollMessagesToBottom()

  try {
    const response = await fetch(streamChatUrl(threadId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildChatPayload(threadId, content))
    })

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`)
    }

    if (threadId === MAIN_CHAT_ID) {
      await handleMainChatStream(response, threadId)
    } else {
      await handleGroupChatStream(response, threadId)
    }
  } catch (error) {
    if (selectedGroupId.value === threadId) {
      messages.value.push({
        role: 'assistant',
        content: `发送失败：${error instanceof Error ? error.message : '未知错误'}`
      })
      await scrollMessagesToBottom()
    }
  } finally {
    setThreadSending(threadId, false)
  }
}

function handleMessageEnter(event) {
  if (event.isComposing) return

  event.preventDefault()
  sendMessage()
}

onMounted(() => {
  loadGroups()
  loadHistory(selectedGroupId.value)
})
</script>

<template>
  <div class="chat-layout">
    <header class="chat-header">聊天</header>
    <div class="chat-body">
      <aside class="chat-sidebar">
        <div class="sidebar-top">
          <button class="new-group" @click="openModal">+ 新建聊天群</button>
        </div>
        <div class="sidebar-bottom">
          <div
            class="group-tag"
            :class="{ active: isMainChat }"
            @click="selectGroup(MAIN_CHAT_ID)"
          >
            主对话
          </div>
          <div
            v-for="group in groups"
            :key="group.id"
            class="group-tag"
            :class="{ active: selectedGroupId === group.id }"
            @click="selectGroup(group.id)"
          >
            <span class="group-name">{{ group.name }}</span>
            <button
              class="delete-group-btn"
              :disabled="isDeletingThread(group.id) || sendingThreadIds.includes(group.id)"
              title="删除对话"
              @click.stop="deleteGroup(group)"
            >
              {{ isDeletingThread(group.id) ? '...' : '×' }}
            </button>
          </div>
        </div>
      </aside>
      <main class="chat-main">
        <div class="chat-content">
          <div class="chat-messages">
            <div v-if="isLoadingHistory" class="history-loading">加载聊天记录...</div>
            <div
              v-for="(msg, index) in messages"
              :key="index"
              class="message"
              :class="msg.role === 'user' ? 'message-right' : 'message-left'"
            >
              <div class="bubble">
                <div v-if="msg.name" class="speaker-name">{{ msg.name }}</div>
                <div
                  v-if="msg.role === 'assistant'"
                  class="markdown-body"
                  v-html="renderMarkdown(msg.content)"
                ></div>
                <template v-else>{{ msg.content }}</template>
              </div>
            </div>
          </div>
          <div class="chat-input">
            <textarea
              v-model="messageInput"
              placeholder="输入消息..."
              :disabled="isCurrentSending || isLoadingHistory"
              rows="2"
              @keydown.enter.exact="handleMessageEnter"
            ></textarea>
            <button
              :disabled="isCurrentSending || isLoadingHistory || !messageInput.trim()"
              @click="sendMessage"
            >
              {{ isCurrentSending ? '发送中...' : isLoadingHistory ? '加载中...' : '发送' }}
            </button>
          </div>
        </div>
        <aside v-if="isMainChat" class="group-info project-info">
          <h2>项目功能介绍</h2>
          <p class="project-summary">
            这是一个基于 Vue 3 和 Vite 构建的多角色聊天前端，用来创建聊天群并组织不同角色参与对话。
          </p>
          <ul class="project-features">
            <li>创建聊天群，填写群名称和简介</li>
            <li>选择产品、研发、测试等角色加入群聊</li>
            <li>向已有群聊邀请角色或移除群成员</li>
            <li>在浏览器本地保存群聊配置</li>
          </ul>
        </aside>
        <aside v-else-if="selectedGroup" class="group-info">
          <h2>{{ selectedGroup.name }}</h2>
          <p class="intro">{{ selectedGroup.intro || '暂无简介' }}</p>
          <div class="persona-section">
            <label for="user-persona">群聊主持控制</label>
            <textarea
              id="user-persona"
              v-model="currentUserPersona"
              rows="4"
              placeholder="例如：我是群聊主持人，负责控制节奏；跑题时拉回主题，需要结论时请大家简短表态。"
            ></textarea>
          </div>
          <div class="rounds-section">
            <div class="rounds-header">
              <label for="max-rounds">最大轮数</label>
              <span>{{ currentMaxRounds }}</span>
            </div>
            <input
              id="max-rounds"
              v-model.number="currentMaxRounds"
              type="range"
              min="1"
              max="100"
              step="1"
            />
            <div class="rounds-scale">
              <span>1</span>
              <span>100</span>
            </div>
          </div>
          <div class="members-section">
            <div class="members-title">群成员</div>
            <div class="member-tags">
              <span v-for="member in selectedGroup.members" :key="member.name" class="member-tag">
                {{ member.name }}
                <i class="remove-btn" @click.stop="removeMember(member)">&times;</i>
              </span>
            </div>
          </div>
          <button class="invite-btn" @click="openInviteModal">邀请好友</button>
        </aside>
      </main>
    </div>
  </div>

  <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
    <div class="modal">
      <h3>新建聊天群</h3>
      <div class="form-row">
        <label>群名称</label>
        <input v-model="groupName" type="text" placeholder="请输入群名称" />
      </div>
      <div class="form-row">
        <label>群简介</label>
        <textarea v-model="groupIntro" rows="3" placeholder="请输入群简介"></textarea>
      </div>
      <div class="form-row flex-row">
        <label>选择进群角色</label>
        <div class="member-list">
          <label v-for="(member, index) in members" :key="member.name" class="member-item">
            <input
              type="checkbox"
              :value="index"
              :checked="selectedMembers.includes(index)"
              @change="toggleMember(index)"
            />
            <div class="member-info">
              <span class="member-name">{{ member.name }}</span>
              <span class="member-persona">{{ member.persona }}</span>
            </div>
          </label>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn-cancel" @click="closeModal">取消</button>
        <button class="btn-confirm" @click="confirmCreate">确认</button>
      </div>
    </div>
  </div>

  <div v-if="showInviteModal" class="modal-overlay" @click.self="closeInviteModal">
    <div class="modal invite-modal">
      <h3>邀请好友</h3>
      <div v-if="availableMembers.length === 0" class="empty-tip">该群已包含所有角色</div>
      <div v-else class="invite-list">
        <label v-for="member in availableMembers" :key="member.name" class="invite-item">
          <input
            type="checkbox"
            :value="member.name"
            :checked="inviteSelected.includes(member.name)"
            @change="toggleInviteMember(member.name)"
          />
          <div class="invite-info">
            <span class="invite-name">{{ member.name }}</span>
            <span class="invite-persona">{{ member.persona }}</span>
          </div>
        </label>
      </div>
      <div class="modal-actions">
        <button class="btn-cancel" @click="closeInviteModal">取消</button>
        <button class="btn-confirm" @click="confirmInvite">确认</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
}

.chat-header {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 0 24px;
  border-bottom: 1px solid #374151;
  background: linear-gradient(90deg, #1f2937, #111827);
  font-size: 22px;
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
}

.chat-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.chat-sidebar {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--code-bg);
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.sidebar-top {
  padding: 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.new-group {
  width: 100%;
  padding: 12px 16px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--accent), #b056f5);
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(170, 59, 255, 0.25);
  transition: transform 0.15s, box-shadow 0.2s;
}

.new-group:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(170, 59, 255, 0.35);
}

.sidebar-bottom {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty-tip {
  padding: 16px;
  text-align: center;
  color: var(--text);
  font-size: 14px;
}

.group-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: var(--bg);
  color: var(--text-h);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: border-color 0.2s, background 0.2s, transform 0.15s;
}

.group-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-group-btn {
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}

.delete-group-btn:hover {
  background: var(--accent-bg);
  color: var(--accent);
}

.delete-group-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.group-tag:hover {
  border-color: var(--accent-border);
  transform: translateX(2px);
}

.group-tag.active {
  border-left: 3px solid var(--accent);
  background: var(--accent-bg);
  color: var(--accent);
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: row;
  min-width: 0;
  overflow: hidden;
}

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.history-loading {
  align-self: center;
  padding: 8px 14px;
  border-radius: 16px;
  background: var(--code-bg);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 13px;
}

.message {
  display: flex;
}

.message-left {
  justify-content: flex-start;
}

.message-right {
  justify-content: flex-end;
}

.bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 18px;
  line-height: 1.5;
  word-break: break-word;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}

.message-left .bubble {
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-h);
  border-bottom-left-radius: 4px;
}

.speaker-name {
  margin-bottom: 4px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
}

.message-right .bubble {
  background: linear-gradient(135deg, var(--accent), #b056f5);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.markdown-body :deep(*) {
  margin-top: 0;
}

.markdown-body :deep(*:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(p) {
  margin-bottom: 8px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin-bottom: 8px;
  padding-left: 20px;
}

.markdown-body :deep(li + li) {
  margin-top: 4px;
}

.markdown-body :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 5px;
  background: var(--code-bg);
  color: var(--text-h);
  font-size: 0.92em;
}

.markdown-body :deep(pre) {
  overflow-x: auto;
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #111827;
  color: #f9fafb;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}

.markdown-body :deep(blockquote) {
  margin-bottom: 8px;
  padding-left: 12px;
  border-left: 3px solid var(--accent-border);
  color: var(--text);
}

.message-right .markdown-body :deep(a),
.message-right .markdown-body :deep(code) {
  color: #fff;
}

.chat-input {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg);
  display: flex;
  align-items: flex-end;
  gap: 12px;
  box-sizing: border-box;
  flex-shrink: 0;
}

.chat-input textarea {
  flex: 1;
  padding: 12px 18px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 15px;
  line-height: 1.5;
  outline: none;
  min-height: 48px;
  max-height: 144px;
  resize: vertical;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.chat-input textarea::placeholder {
  color: var(--text);
}

.chat-input textarea:focus {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 3px var(--accent-bg);
}

.chat-input button {
  padding: 0 24px;
  border: none;
  border-radius: 24px;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.2s;
}

.chat-input button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(170, 59, 255, 0.25);
}

.chat-input textarea:disabled,
.chat-input button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.chat-input button:disabled:hover {
  transform: none;
  box-shadow: none;
}

.group-info {
  width: 300px;
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--code-bg);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
  box-sizing: border-box;
}

.group-info h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-h);
}

.group-info .intro {
  margin: 0;
  padding: 14px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  font-size: 14px;
  line-height: 1.6;
  color: var(--text);
}

.project-info {
  gap: 16px;
}

.project-summary {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
}

.project-features {
  margin: 0;
  padding: 16px 16px 16px 34px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.7;
}

.project-features li + li {
  margin-top: 8px;
}

.persona-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.persona-section label {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.persona-section textarea {
  width: 100%;
  resize: vertical;
  min-height: 92px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 14px;
  line-height: 1.5;
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.persona-section textarea::placeholder {
  color: var(--text);
}

.persona-section textarea:focus {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 3px var(--accent-bg);
}

.rounds-section {
  padding: 14px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
}

.rounds-header,
.rounds-scale {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rounds-header {
  margin-bottom: 12px;
}

.rounds-header label {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.rounds-header span {
  min-width: 36px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 13px;
  font-weight: 700;
  text-align: center;
}

.rounds-section input[type='range'] {
  width: 100%;
  accent-color: var(--accent);
  cursor: pointer;
}

.rounds-scale {
  margin-top: 4px;
  color: var(--text);
  font-size: 12px;
}

.members-section {
  padding: 14px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
}

.members-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 10px;
}

.member-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.member-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px 6px 12px;
  border-radius: 20px;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 13px;
  font-weight: 500;
  border: 1px solid var(--accent-border);
}

.remove-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  font-style: normal;
  font-size: 12px;
  line-height: 1;
  color: var(--accent);
  cursor: pointer;
  background: rgba(170, 59, 255, 0.12);
  transition: background 0.2s, color 0.2s;
}

.remove-btn:hover {
  background: var(--accent);
  color: #fff;
}

.invite-btn {
  margin-top: auto;
  padding: 12px;
  border: none;
  border-radius: 12px;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(170, 59, 255, 0.25);
  transition: transform 0.15s, box-shadow 0.2s;
}

.invite-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(170, 59, 255, 0.35);
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  width: 480px;
  max-width: 90%;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-radius: 20px;
  padding: 28px;
  border: 1px solid var(--border);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
  box-sizing: border-box;
}

.modal h3 {
  margin: 0 0 24px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-h);
  flex-shrink: 0;
}

.form-row {
  margin-bottom: 18px;
  flex-shrink: 0;
}

.form-row.flex-row {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  margin-bottom: 0;
}

.form-row label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  flex-shrink: 0;
}

.form-row input[type='text'],
.form-row textarea {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 15px;
  box-sizing: border-box;
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-row textarea {
  resize: vertical;
}

.form-row input[type='text']:focus,
.form-row textarea:focus {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 3px var(--accent-bg);
}

.member-list {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 8px;
  overflow-y: auto;
}

.member-item {
  display: flex !important;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.member-item:hover {
  border-color: var(--accent-border);
  background: var(--accent-bg);
}

.member-item input {
  margin-top: 3px;
  cursor: pointer;
}

.member-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.member-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-h);
}

.member-persona {
  font-size: 13px;
  line-height: 1.4;
  color: var(--text);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 18px;
  flex-shrink: 0;
}

.modal-actions button {
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: transform 0.15s, opacity 0.2s;
}

.modal-actions button:hover {
  transform: translateY(-1px);
  opacity: 0.9;
}

.btn-cancel {
  background: var(--code-bg);
  color: var(--text-h);
}

.btn-confirm {
  background: var(--accent);
  color: #fff;
}

.invite-modal {
  width: 560px;
}

.invite-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 380px;
  overflow-y: auto;
  margin-bottom: 16px;
}

.invite-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
  background: var(--bg);
  transition: border-color 0.2s, background 0.2s;
}

.invite-item:hover {
  border-color: var(--accent-border);
  background: var(--accent-bg);
}

.invite-item input {
  margin-top: 3px;
  cursor: pointer;
}

.invite-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.invite-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-h);
}

.invite-persona {
  font-size: 13px;
  line-height: 1.4;
  color: var(--text);
}
</style>
