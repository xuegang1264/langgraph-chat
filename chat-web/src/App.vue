<script setup>
import { ref, computed, onMounted } from 'vue'
import { v4 as uuidv4 } from 'uuid'

const STORAGE_KEY = 'chatGroups'
const MAIN_CHAT_ID = 'e6ead6c0-9188-4fdd-b82d-51dbeeb283b3'

const members = [
  { name: '产品经理', persona: '关注用户需求，输出产品方案，把控需求范围，说话务实，会平衡业务和技术可行性。' },
  { name: '项目经理', persona: '关注项目进度、排期、风险，协调各方资源，善于识别延期风险，说话直接。' },
  { name: 'PMO', persona: '掌握公司人力池情况，评估团队负载，管控项目流程，输出项目风险汇总。' },
  { name: '后端开发', persona: '熟悉服务、数据库，评估接口与业务逻辑开发工作量，提出技术难点与坑点。' },
  { name: '前端开发', persona: '关注页面交互、兼容性，评估前端实现成本，提出交互实现上的问题。' },
  { name: '测试工程师', persona: '关注质量，会提出测试风险，思考边界场景、回归工作量。' },
  { name: '架构师', persona: '做技术方案评审，评估系统性能、扩展性，识别重大技术风险。' },
  { name: '业务负责人', persona: '代表业务方，阐述业务目标，做业务决策，关注业务价值。' }
]

const groups = ref([])
const selectedGroupId = ref(MAIN_CHAT_ID)
const selectedGroup = computed(() => groups.value.find(g => g.id === selectedGroupId.value))
const isMainChat = computed(() => selectedGroupId.value === MAIN_CHAT_ID)

const messages = ref([
  { role: 'assistant', content: '你好，有什么可以帮你的？' }
])
const messageInput = ref('')
const isSending = ref(false)

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

function loadGroups() {
  const raw = localStorage.getItem(STORAGE_KEY)
  groups.value = raw ? JSON.parse(raw) : []
  selectedGroupId.value = MAIN_CHAT_ID
}

function saveGroups() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(groups.value))
}

function selectGroup(id) {
  selectedGroupId.value = id
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
  const newGroup = {
    id: uuidv4(),
    name: groupName.value.trim(),
    intro: groupIntro.value.trim(),
    members: selectedMembers.value.map(idx => members[idx]),
    createdAt: Date.now()
  }
  groups.value.push(newGroup)
  saveGroups()
  selectedGroupId.value = newGroup.id
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

async function sendMessage() {
  const content = messageInput.value.trim()
  if (!content || isSending.value || !isMainChat.value) return

  messages.value.push({ role: 'user', content })
  messageInput.value = ''
  isSending.value = true

  try {
    const response = await fetch('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: MAIN_CHAT_ID,
        message: content
      })
    })

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`)
    }

    const data = await response.json()
    messages.value.push(data.message)
  } catch (error) {
    messages.value.push({
      role: 'assistant',
      content: `发送失败：${error instanceof Error ? error.message : '未知错误'}`
    })
  } finally {
    isSending.value = false
  }
}

onMounted(loadGroups)
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
            {{ group.name }}
          </div>
        </div>
      </aside>
      <main class="chat-main">
        <div class="chat-content">
          <div class="chat-messages">
            <div
              v-for="(msg, index) in messages"
              :key="index"
              class="message"
              :class="msg.role === 'user' ? 'message-right' : 'message-left'"
            >
              <div class="bubble">{{ msg.content }}</div>
            </div>
          </div>
          <div class="chat-input">
            <input
              v-model="messageInput"
              type="text"
              placeholder="输入消息..."
              :disabled="isSending || !isMainChat"
              @keyup.enter="sendMessage"
            />
            <button
              :disabled="isSending || !messageInput.trim() || !isMainChat"
              @click="sendMessage"
            >
              {{ isSending ? '发送中...' : '发送' }}
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

.message-right .bubble {
  background: linear-gradient(135deg, var(--accent), #b056f5);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.chat-input {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg);
  display: flex;
  gap: 12px;
  box-sizing: border-box;
  flex-shrink: 0;
}

.chat-input input {
  flex: 1;
  padding: 12px 18px;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 15px;
  outline: none;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.chat-input input::placeholder {
  color: var(--text);
}

.chat-input input:focus {
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

.chat-input input:disabled,
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
