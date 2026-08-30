import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Dropdown, Empty, Image as AntImage, Input, Modal, Row, Space, Spin, Tag, Typography, message,
} from 'antd'
import {
  AuditOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, MessageOutlined,
  MoreOutlined, PlusOutlined, RobotOutlined, SearchOutlined, SendOutlined, UserOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useUser } from '../App'
import {
  ChatSession, createChatSession, deleteChatSession, getAccessToken, getChatMessages,
  listChatSessions, PersistedChatMessage, Product, renameChatSession,
} from '../api'
import PlanPanel, { PlanData, ProgressLine } from '../components/PlanPanel'

interface ChatMsg {
  id: number
  role: 'user' | 'assistant'
  text: string
  products?: Product[]
  productTitle?: string
  outfit?: { name: string; items: { name: string; imageUrl?: string; source: string; price?: number }[]; reason?: string; ruleSources?: string[] }
  image?: { url: string; label: string; taskId?: number }
  progress?: { percent: number; stage: string }
  handoff?: string
  error?: boolean
  thinking?: boolean
}

const WELCOME: ChatMsg = {
  id: 0,
  role: 'assistant',
  text:
    '你好，我是穿搭助手 🧥\n我可以：\n· 用你衣橱里的单品搭配\n· 按季节、场景和风格提供建议\n· 生成换装效果图\n· 查询商品、收藏和下单\n你可以直接描述想要的穿搭。',
}

const EXAMPLES = [
  '用我衣橱里的白衬衫搭一套秋季通勤装',
  '裤子换成商城在售的，预算 300 以内',
  '生成一张效果图看看',
  '现在商城有什么活动？',
  '帮我看看这件衣服',
]

let msgId = 1

function restoreMessage(message: PersistedChatMessage): ChatMsg {
  let meta: Partial<ChatMsg> = {}
  if (message.meta) {
    try { meta = JSON.parse(message.meta) as Partial<ChatMsg> } catch { /* 兼容旧的空/无效 meta */ }
  }
  return {
    ...meta,
    id: message.id,
    role: message.role,
    text: message.content || '',
    thinking: false,
  }
}

function MarkdownText({ text }: { text: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

export default function ChatPage() {
  const { user } = useUser()
  const { sessionId: routeSessionId } = useParams()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [search, setSearch] = useState('')
  const [renameTarget, setRenameTarget] = useState<ChatSession | null>(null)
  const [renameTitle, setRenameTitle] = useState('')

  const selectSession = (session: ChatSession, replace = false) => {
    setActiveSession(session)
    if (user) localStorage.setItem(`app_session_id_${user.id}`, session.id)
    navigate(`/chat/${session.id}`, { replace })
  }

  useEffect(() => {
    if (!user) return
    let active = true
    const initialize = async () => {
      setLoading(true)
      try {
        let rows = await listChatSessions()
        // React StrictMode 会在开发环境重放 effect；失活的首轮不能再创建空会话。
        if (!active) return
        if (!rows.length) rows = [await createChatSession()]
        if (!active) return
        setSessions(rows)
        const remembered = localStorage.getItem(`app_session_id_${user.id}`)
        const selected = rows.find((item) => item.id === routeSessionId)
          ?? rows.find((item) => item.id === remembered)
          ?? rows[0]
        selectSession(selected, routeSessionId !== selected.id)
      } catch (error: any) {
        message.error(error?.message || '会话加载失败')
      } finally {
        if (active) setLoading(false)
      }
    }
    void initialize()
    return () => { active = false }
  }, [user?.id])

  useEffect(() => {
    if (!routeSessionId || !sessions.length) return
    const target = sessions.find((item) => item.id === routeSessionId)
    if (target && target.id !== activeSession?.id) setActiveSession(target)
  }, [routeSessionId, sessions])

  const createNew = async () => {
    if (creating) return
    setCreating(true)
    try {
      const created = await createChatSession()
      setSessions((current) => [created, ...current])
      selectSession(created)
    } catch (error: any) {
      message.error(error?.message || '新建对话失败')
    } finally {
      setCreating(false)
    }
  }

  const saveRename = async () => {
    if (!renameTarget) return
    try {
      const updated = await renameChatSession(renameTarget.id, renameTitle)
      setSessions((current) => current.map((item) => item.id === updated.id ? updated : item))
      if (activeSession?.id === updated.id) setActiveSession(updated)
      setRenameTarget(null)
    } catch (error: any) {
      message.error(error?.message || '重命名失败')
    }
  }

  const confirmDelete = (session: ChatSession) => {
    Modal.confirm({
      title: '删除这段对话？',
      content: `“${session.title || '新对话'}”及其全部消息将被永久删除。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await deleteChatSession(session.id)
        let remaining = sessions.filter((item) => item.id !== session.id)
        if (!remaining.length) remaining = [await createChatSession()]
        setSessions(remaining)
        if (activeSession?.id === session.id) selectSession(remaining[0], true)
        message.success('会话已删除')
      },
    })
  }

  const visibleSessions = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return keyword ? sessions.filter((item) => (item.title || '新对话').toLowerCase().includes(keyword)) : sessions
  }, [sessions, search])

  const updateSession = (updated: ChatSession) => {
    setSessions((current) => current.map((item) => item.id === updated.id ? updated : item))
    if (activeSession?.id === updated.id) setActiveSession(updated)
  }

  return (
    <div className="chat-page-shell">
      <aside className="session-sidebar">
        <Button type="primary" icon={<PlusOutlined />} block size="large" loading={creating} onClick={createNew}>
          新建对话
        </Button>
        <Input
          allowClear prefix={<SearchOutlined />} placeholder="搜索会话"
          value={search} onChange={(event) => setSearch(event.target.value)}
        />
        <div className="session-list">
          {loading ? (
            <div className="session-loading"><Spin size="small" /></div>
          ) : visibleSessions.length ? visibleSessions.map((session) => (
            <button
              type="button" key={session.id}
              className={`session-item ${activeSession?.id === session.id ? 'active' : ''}`}
              onClick={() => selectSession(session)}
            >
              <MessageOutlined className="session-icon" />
              <span className="session-copy">
                <span className="session-title">{session.title || '新对话'}</span>
                <span className="session-time">
                  {session.updatedAt ? new Date(session.updatedAt).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : '刚刚'}
                </span>
              </span>
              <Dropdown
                trigger={['click']}
                menu={{
                  onClick: ({ key, domEvent }) => {
                    domEvent.stopPropagation()
                    if (key === 'rename') {
                      setRenameTarget(session)
                      setRenameTitle(session.title || '新对话')
                    } else if (key === 'delete') confirmDelete(session)
                  },
                  items: [
                    { key: 'rename', icon: <EditOutlined />, label: '重命名' },
                    { type: 'divider' },
                    { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除' },
                  ],
                }}
              >
                <span className="session-more" role="button" onClick={(event) => event.stopPropagation()}><MoreOutlined /></span>
              </Dropdown>
            </button>
          )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的会话" />}
        </div>
      </aside>

      <main className="chat-workspace-host">
        {activeSession ? (
          <ChatWorkspace key={activeSession.id} session={activeSession} onSessionChanged={updateSession} />
        ) : (
          <div className="chat-empty"><Spin tip="正在准备新对话…" /></div>
        )}
      </main>

      <Modal
        title="重命名会话" open={!!renameTarget} okText="保存" cancelText="取消"
        onOk={saveRename} onCancel={() => setRenameTarget(null)}
      >
        <Input
          autoFocus maxLength={60} showCount value={renameTitle}
          onChange={(event) => setRenameTitle(event.target.value)}
          onPressEnter={() => void saveRename()}
        />
      </Modal>
    </div>
  )
}

interface ChatWorkspaceProps {
  session: ChatSession
  onSessionChanged: (session: ChatSession) => void
}

function ChatWorkspace({ session, onSessionChanged }: ChatWorkspaceProps) {
  const { user } = useUser()
  const [messages, setMessages] = useState<ChatMsg[]>([WELCOME])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [plan, setPlan] = useState<PlanData>({})
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>('closed')
  const [panelWidth, setPanelWidth] = useState(440)
  const navigate = useNavigate()
  const listRef = useRef<HTMLDivElement>(null)
  const sessionRef = useRef<string>(session.id)
  const userRef = useRef(user)
  userRef.current = user
  const asstIdRef = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const hbRef = useRef<number | undefined>(undefined)
  const retryRef = useRef<number | undefined>(undefined)
  const historyRetryRef = useRef<number | undefined>(undefined)
  const attemptRef = useRef(0)
  const readyRef = useRef(false)
  const pendingHistoryIdRef = useRef(0)

  // ---- 统一事件处理（WS 与 SSE 共用） ----
  const handleEvent = (ev: any) => {
    const asstId = asstIdRef.current
    const patch = (p: Partial<ChatMsg>) =>
      setMessages((m) => m.map((x) => (x.id === asstId ? { ...x, ...p } : x)))
    const patchText = (t: string, extra: Partial<ChatMsg> = {}) =>
      setMessages((m) => m.map((x) => (x.id === asstId ? { ...x, text: x.text + t, thinking: false, ...extra } : x)))
    const patchPlan = (p: Partial<PlanData>) =>
      setPlan((prev) => ({
        ...prev, ...p,
        statuses: [...(prev.statuses ?? []), ...(p.statuses ?? [])],
        tools: [...(prev.tools ?? []), ...(p.tools ?? [])],
        ragRules: [...(prev.ragRules ?? []), ...(p.ragRules ?? [])],
      }))
    switch (ev.type) {
      case 'plan':
        patchPlan({ intents: ev.data?.intents, dag: ev.data?.dag })
        break
      case 'status':
        patchPlan({ statuses: [{ text: ev.data.text, stage: ev.data.stage }] })
        break
      case 'tool':
        patchPlan({ tools: [{ name: ev.data.name, args: ev.data.args ?? {}, ok: !!ev.data.ok, summary: ev.data.summary ?? '' }] })
        break
      case 'rag':
        patchPlan({ ragRules: ev.data?.rules ?? [] })
        break
      case 'product':
        patch({ products: ev.data.products ?? [], productTitle: ev.data.title ?? '商城在售候选' })
        break
      case 'outfit':
        patch({ outfit: ev.data.outfit })
        break
      case 'image_progress':
        patch({ progress: { percent: ev.data.percent ?? 0, stage: ev.data.stage ?? '生成中' } })
        break
      case 'image':
        patch({ image: { url: ev.data.url, label: ev.data.label ?? '换装效果图', taskId: ev.data.taskId } })
        break
      case 'memory':
        patchPlan({ memory: ev.data?.memory ?? ev.data })
        break
      case 'safety':
        patchPlan({ safety: ev.data })
        break
      case 'context':
        patchPlan({ context: ev.data })
        break
      case 'handoff':
        patch({ handoff: ev.data.reason })
        patchPlan({ handoff: ev.data.reason })
        break
      case 'token':
        patchText(ev.data.text)
        break
      case 'error':
        patchText('\n⚠️ ' + ev.data.text, { error: true })
        setSending(false)
        break
      case 'done':
        patch({ thinking: false })
        setSending(false)
        break
      case 'pong':
      case 'welcome':
        break // WS 基础设施帧
      default:
        break
    }
  }

  // ---- Netty WS 连接：心跳 + 自动重连 + 会话隔离 ----
  const connectWs = () => {
    if (!sessionRef.current) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const token = getAccessToken()
    const ws = new WebSocket(
      `${proto}://${location.host}/ws/chat?sessionId=${encodeURIComponent(sessionRef.current)}&userId=${userRef.current?.id ?? 1}&token=${encodeURIComponent(token)}`,
    )
    wsRef.current = ws
    setWsState('connecting')
    ws.onopen = () => {
      attemptRef.current = 0
      setWsState('open')
      window.clearInterval(hbRef.current)
      hbRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, 25000)
    }
    ws.onmessage = (m) => {
      try { handleEvent(JSON.parse(m.data)) } catch { /* 忽略坏帧 */ }
    }
    ws.onclose = () => {
      setWsState('closed')
      window.clearInterval(hbRef.current)
      scheduleReconnect()
    }
    ws.onerror = () => {
      try { ws.close() } catch { /* ignore */ }
    }
  }

  const scheduleReconnect = () => {
    window.clearTimeout(retryRef.current)
    const delay = Math.min(1000 * 2 ** attemptRef.current++, 10000)
    retryRef.current = window.setTimeout(connectWs, delay)
  }

  // 右侧面板宽度拖拽调整（340~680px）
  const startDrag = (e: React.MouseEvent) => {
    const startX = e.clientX
    const startW = panelWidth
    const onMove = (ev: MouseEvent) => {
      setPanelWidth(Math.min(680, Math.max(340, startW + (startX - ev.clientX))))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  useEffect(() => {
    let active = true

    const loadHistory = async (attempt = 0): Promise<boolean> => {
      try {
        const history = await getChatMessages(sessionRef.current)
        if (!active) return false
        const restored = history
          .filter((item) => item.role === 'user' || item.role === 'assistant')
          .map(restoreMessage)
        const maxId = restored.reduce((max, item) => Math.max(max, item.id), 0)
        msgId = Math.max(msgId, maxId + 1)
        const waitingForAssistant = restored[restored.length - 1]?.role === 'user'
        if (waitingForAssistant) {
          if (!pendingHistoryIdRef.current) pendingHistoryIdRef.current = msgId++
          const pending: ChatMsg = { id: pendingHistoryIdRef.current, role: 'assistant', text: '', thinking: true }
          asstIdRef.current = pending.id
          setMessages((current) => {
            const livePending = current.find((item) => item.id === pending.id)
            if (attempt >= 30) {
              return [...restored, {
                ...(livePending ?? pending),
                text: livePending?.text || '回复仍在后台处理中，请稍后重新进入本页查看完整结果。',
                thinking: false,
                error: true,
              }]
            }
            return [...restored, livePending ?? pending]
          })
          setSending(attempt < 30)
          if (attempt < 30) {
            historyRetryRef.current = window.setTimeout(() => loadHistory(attempt + 1), 1000)
          }
        } else {
          pendingHistoryIdRef.current = 0
          asstIdRef.current = 0
          setMessages(restored.length ? restored : [WELCOME])
          setSending(false)
        }
        return waitingForAssistant
      } catch {
        if (active) setMessages([WELCOME])
        return false
      } finally {
        if (active && attempt === 0) {
          readyRef.current = true
          setHistoryLoading(false)
        }
      }
    }

    const initialize = async () => {
      const waitingForAssistant = await loadHistory()
      if (!active) return
      connectWs()
      const preset = sessionStorage.getItem('app_preset_message')
      if (preset && !waitingForAssistant) {
        sessionStorage.removeItem('app_preset_message')
        window.setTimeout(() => send(preset), 300)
      }
    }
    initialize()

    return () => {
      active = false
      readyRef.current = false
      window.clearTimeout(retryRef.current)
      window.clearTimeout(historyRetryRef.current)
      window.clearInterval(hbRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
    }
  }, [])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const send = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || sending || !readyRef.current) return
    setInput('')
    setSending(true)
    setPlan({})
    const uid = userRef.current?.id ?? 1
    const userMsg: ChatMsg = { id: msgId++, role: 'user', text: content }
    const asst: ChatMsg = { id: msgId++, role: 'assistant', text: '', thinking: true }
    asstIdRef.current = asst.id
    setMessages((m) => [...m, userMsg, asst])
    if (session.title === '新对话') {
      const title = content.replace(/\s+/g, ' ').slice(0, 30)
      void renameChatSession(session.id, title)
        .then(onSessionChanged)
        .catch(() => undefined)
    } else {
      onSessionChanged({ ...session, updatedAt: new Date().toISOString() })
    }

    // WS 已连接 → 全双工走 Netty（发送 + 推送）；断开 → 降级 SSE
    const ws = wsRef.current
    // Runtime Context：服务端可信字段（会员等级/风险等级/页面上下文），不由用户输入产生
    const runtime = { memberLevel: 'silver', riskLevel: 'low', pageContext: { page: 'chat' } }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', sessionId: sessionRef.current, userId: uid, message: content, ...runtime }))
      return
    }

    try {
      const res = await fetch('/agent/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getAccessToken()}`,
        },
        body: JSON.stringify({
          session_id: sessionRef.current, user_id: uid, message: content, transport: 'sse',
          member_level: runtime.memberLevel, risk_level: runtime.riskLevel, page_context: runtime.pageContext,
        }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try { handleEvent(JSON.parse(line.slice(5).trim())) } catch { /* ignore */ }
        }
      }
    } catch (e: any) {
      handleEvent({ type: 'error', data: { text: `请求失败：${e.message || e}（请确认 Agent 服务已启动）` } })
    }
    setSending(false)
  }

  const renderMsg = (m: ChatMsg) => {
    if (m.role === 'user') {
      return (
        <div key={m.id} style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <div style={{ maxWidth: '72%', background: '#1677ff', color: '#fff', padding: '8px 12px', borderRadius: 10 }}>
            <Typography.Text style={{ color: '#fff', whiteSpace: 'pre-wrap' }}>{m.text}</Typography.Text>
          </div>
          <span style={{ marginLeft: 8 }}><UserOutlined /></span>
        </div>
      )
    }
    return (
      <div key={m.id} style={{ display: 'flex', marginBottom: 12 }}>
        <span style={{ marginRight: 8, color: '#1677ff', fontSize: 18 }}><RobotOutlined /></span>
        <div style={{ maxWidth: '86%', flex: 1 }}>
          <div style={{ background: '#f5f7fa', padding: '8px 12px', borderRadius: 10 }}>
            {m.thinking && !m.text ? <Typography.Text type="secondary">思考中…</Typography.Text> : null}
            {m.text && <MarkdownText text={m.text} />}
            {m.products && (
              <div style={{ marginTop: 8 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{m.productTitle}：</Typography.Text>
                <Row gutter={[8, 8]} style={{ marginTop: 4 }}>
                  {m.products.map((p) => (
                    <Col key={p.id} xs={12} sm={8}>
                      <Card size="small" hoverable
                        onClick={() => { sessionStorage.setItem('app_preset_message', `看看商品「${p.name}」的详情`); window.location.pathname = '/mall' }}>
                        <img alt={p.name} src={p.imageUrl || '/seed-images/product_1.svg'} style={{ width: '100%', height: 90, objectFit: 'cover', borderRadius: 6 }}
                          onError={(e) => { (e.target as HTMLImageElement).src = '/seed-images/product_1.svg' }} />
                        <div style={{ fontSize: 12, marginTop: 4 }}>{p.name}</div>
                        <div><span style={{ color: '#f5222d', fontWeight: 600, fontSize: 12 }}>¥{p.price}</span>
                          <span style={{ color: '#999', fontSize: 11, marginLeft: 6 }}>{p.category === 'top' ? '上装' : p.category === 'bottom' ? '下装' : p.category === 'outerwear' ? '外套' : p.category === 'dress' ? '连衣裙' : p.category === 'shoes' ? '鞋履' : '配饰'} · {p.color}</span>
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </div>
            )}
            {m.outfit && (
              <div style={{ marginTop: 8 }}>
                <Space size={4} wrap>
                  <Typography.Text strong style={{ fontSize: 13 }}>👗 {m.outfit.name}</Typography.Text>
                  {(m.outfit.ruleSources ?? []).map((s) => <Tag key={s} color="purple" style={{ fontSize: 11 }}>规则: {s}</Tag>)}
                </Space>
                <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                  {m.outfit.items.map((it, i) => (
                    <div key={i} style={{ width: 96, textAlign: 'center' }}>
                      <img alt={it.name} src={it.imageUrl || '/seed-images/wardrobe_1.svg'}
                        style={{ width: 96, height: 96, objectFit: 'cover', borderRadius: 8 }}
                        onError={(e) => { (e.target as HTMLImageElement).src = '/seed-images/wardrobe_1.svg' }} />
                      <div style={{ fontSize: 11, marginTop: 2 }}>{it.name}</div>
                      <Tag style={{ fontSize: 10 }} color={it.source === 'mall' ? 'blue' : 'green'}>
                        {it.source === 'mall' ? `商城 ¥${it.price}` : '衣橱'}
                      </Tag>
                    </div>
                  ))}
                </div>
                {m.outfit.reason && <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>{m.outfit.reason}</Typography.Text>}
              </div>
            )}
            {m.progress && <ProgressLine percent={m.progress.percent} stage={m.progress.stage} />}
            {m.handoff && (
              <div style={{ marginTop: 8 }}>
                <Tag color="volcano">已转人工</Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{m.handoff}</Typography.Text>
              </div>
            )}
            {m.image && (
              <div style={{ marginTop: 8 }}>
                <AntImage src={m.image.url} width={240} style={{ borderRadius: 8 }} />
                <div style={{ marginTop: 4 }}>
                  <Tag color="magenta">{m.image.label}</Tag>
                  <Button size="small" type="link" onClick={() => send('基于这张效果图继续调整：换一条裤子')}>
                    基于此图继续调整 →
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 12, height: '100%' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, border: '1px solid #f0f0f0' }}>
        <div ref={listRef} style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          {historyLoading
            ? <div style={{ minHeight: 180, display: 'grid', placeItems: 'center' }}><Spin aria-label="正在恢复对话记录" /></div>
            : messages.map(renderMsg)}
        </div>
        {!historyLoading && messages.length <= 1 && (
          <div style={{ padding: '0 16px 8px' }}>
            <Space wrap>
              {EXAMPLES.map((e) => (
                <Tag key={e} style={{ cursor: 'pointer', padding: '4px 8px' }} color="blue"
                  onClick={() => send(e)}>{e}</Tag>
              ))}
            </Space>
          </div>
        )}
        <div style={{ borderTop: '1px solid #f0f0f0', padding: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Space size={4}>
            {wsState === 'open' && <Tag color="green">Netty WS 已连接</Tag>}
            {wsState === 'connecting' && <Tag color="orange">WS 连接中…</Tag>}
            {wsState === 'closed' && <Tag>SSE 降级模式</Tag>}
            <Button size="small" icon={<AuditOutlined />} onClick={() => navigate('/observe')}>可观测</Button>
          </Space>
          <Button icon={<ExperimentOutlined />} onClick={() => send('基于当前搭配生成一张换装效果图')} disabled={sending}>
            生成效果图
          </Button>
          <Input.TextArea
            value={input} autoSize={{ minRows: 1, maxRows: 4 }} placeholder="描述你的穿搭需求，如：用衣橱里的白衬衫搭一套秋季通勤装"
            disabled={historyLoading}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
          />
          <Button type="primary" icon={<SendOutlined />} loading={sending} disabled={historyLoading} onClick={() => send()}>发送</Button>
        </div>
      </div>
      {/* 拖拽手柄 */}
      <div
        onMouseDown={startDrag}
        style={{ width: 6, cursor: 'col-resize', background: 'transparent', borderRadius: 4 }}
        title="拖动调整面板宽度"
      />
      <div style={{ width: panelWidth, flexShrink: 0, background: '#fff', borderRadius: 8, border: '1px solid #f0f0f0', padding: 12, display: 'flex', flexDirection: 'column' }}>
        <PlanPanel data={plan} />
        <div style={{ marginTop: 8, borderTop: '1px solid #f0f0f0', paddingTop: 8, fontSize: 12 }}>
          <a onClick={() => navigate('/observe')}>完整 Trace · 回归评测 · 模型配置 → 可观测页</a>
        </div>
      </div>
    </div>
  )
}
