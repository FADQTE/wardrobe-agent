import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Col, Empty, Image as AntImage, Input, Row, Space, Tag, Typography,
} from 'antd'
import { ExperimentOutlined, RobotOutlined, SendOutlined, UserOutlined } from '@ant-design/icons'
import { useUser } from '../App'
import { Product } from '../api'
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
  error?: boolean
  thinking?: boolean
}

const WELCOME: ChatMsg = {
  id: 0,
  role: 'assistant',
  text:
    '你好，我是潮引穿搭小助手 🧥\n我可以：\n· 用你衣橱里的单品搭配（含在售商品混合搭配）\n· 按季节/场景/风格推荐，并给出规则来源\n· 生成 AI 换装效果图（mock）\n· 查询商城活动与商品，收藏/下单\n回复与进度经 Netty WS 实时推送（断线自动重连，失败降级 SSE）。\n试试下面的快捷问题，右侧面板会实时展示意图识别与编排 DAG。',
}

const EXAMPLES = [
  '用我衣橱里的白衬衫搭一套秋季通勤装',
  '裤子换成商城在售的，预算 300 以内',
  '生成一张效果图看看',
  '现在商城有什么活动？',
  '帮我看看这件衣服',
]

let msgId = 1

export default function ChatPage() {
  const { user } = useUser()
  const [messages, setMessages] = useState<ChatMsg[]>([WELCOME])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [plan, setPlan] = useState<PlanData>({})
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>('closed')
  const listRef = useRef<HTMLDivElement>(null)
  const sessionRef = useRef<string>(localStorage.getItem('cy_session_id') || '')
  const userRef = useRef(user)
  userRef.current = user
  const asstIdRef = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const hbRef = useRef<number | undefined>(undefined)
  const retryRef = useRef<number | undefined>(undefined)
  const attemptRef = useRef(0)

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
    const ws = new WebSocket(
      `${proto}://${location.host}/ws/chat?sessionId=${encodeURIComponent(sessionRef.current)}&userId=${userRef.current?.id ?? 1}`,
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

  useEffect(() => {
    if (!sessionRef.current) {
      sessionRef.current = 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
      localStorage.setItem('cy_session_id', sessionRef.current)
    }
    connectWs()
    const preset = sessionStorage.getItem('cy_preset_message')
    if (preset) {
      sessionStorage.removeItem('cy_preset_message')
      setTimeout(() => send(preset), 600)
    }
    return () => {
      window.clearTimeout(retryRef.current)
      window.clearInterval(hbRef.current)
      wsRef.current?.close()
    }
  }, [])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const send = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || sending) return
    setInput('')
    setSending(true)
    setPlan({})
    const uid = userRef.current?.id ?? 1
    const userMsg: ChatMsg = { id: msgId++, role: 'user', text: content }
    const asst: ChatMsg = { id: msgId++, role: 'assistant', text: '', thinking: true }
    asstIdRef.current = asst.id
    setMessages((m) => [...m, userMsg, asst])

    // WS 已连接 → 全双工走 Netty（发送 + 推送）；断开 → 降级 SSE
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', sessionId: sessionRef.current, userId: uid, message: content }))
      return
    }

    try {
      const res = await fetch('/agent/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionRef.current, user_id: uid, message: content, transport: 'sse' }),
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
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <div style={{ maxWidth: '72%', background: '#1677ff', color: '#fff', padding: '8px 12px', borderRadius: 10 }}>
            <Typography.Text style={{ color: '#fff', whiteSpace: 'pre-wrap' }}>{m.text}</Typography.Text>
          </div>
          <span style={{ marginLeft: 8 }}><UserOutlined /></span>
        </div>
      )
    }
    return (
      <div style={{ display: 'flex', marginBottom: 12 }}>
        <span style={{ marginRight: 8, color: '#1677ff', fontSize: 18 }}><RobotOutlined /></span>
        <div style={{ maxWidth: '86%', flex: 1 }}>
          <div style={{ background: '#f5f7fa', padding: '8px 12px', borderRadius: 10 }}>
            {m.thinking && !m.text ? <Typography.Text type="secondary">思考中…</Typography.Text> : null}
            {m.text && <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{m.text}</Typography.Text>}
            {m.products && (
              <div style={{ marginTop: 8 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{m.productTitle}：</Typography.Text>
                <Row gutter={[8, 8]} style={{ marginTop: 4 }}>
                  {m.products.map((p) => (
                    <Col key={p.id} xs={12} sm={8}>
                      <Card size="small" hoverable
                        onClick={() => { sessionStorage.setItem('cy_preset_message', `看看商品「${p.name}」的详情`); window.location.pathname = '/mall' }}>
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
    <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 120px)' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, border: '1px solid #f0f0f0' }}>
        <div ref={listRef} style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          {messages.map(renderMsg)}
        </div>
        {messages.length <= 1 && (
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
          </Space>
          <Button icon={<ExperimentOutlined />} onClick={() => send('基于当前搭配生成一张换装效果图')} disabled={sending}>
            生成效果图
          </Button>
          <Input.TextArea
            value={input} autoSize={{ minRows: 1, maxRows: 4 }} placeholder="描述你的穿搭需求，如：用衣橱里的白衬衫搭一套秋季通勤装"
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
          />
          <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={() => send()}>发送</Button>
        </div>
      </div>
      <div style={{ width: 400, background: '#fff', borderRadius: 8, border: '1px solid #f0f0f0', padding: 12, overflow: 'auto' }}>
        <Typography.Text strong style={{ fontSize: 13 }}>Agent 编排过程</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ fontSize: 11, marginBottom: 8 }}>
          意图识别 → 依赖 DAG（无依赖并行/依赖按拓扑顺序）→ 工具调用（MCP/RAG）→ 汇总回复
        </Typography.Paragraph>
        <PlanPanel data={plan} />
      </div>
    </div>
  )
}
