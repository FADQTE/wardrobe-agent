import { useEffect, useState, type ReactNode } from 'react'
import {
  Button, Card, Col, Collapse, Empty, Row, Space, Statistic, Table, Tag,
  Typography,
} from 'antd'
import { ReloadOutlined, PlayCircleOutlined } from '@ant-design/icons'
import PageHeader from '../components/PageHeader'
import { TraceEvent, TraceSession, getAgentHealth, getTrace, getTraceSessions, runEval } from '../api'

const CATEGORY_META: Record<string, { label: string; color: string; desc: string }> = {
  entry: { label: '输入', color: 'blue', desc: '本轮入口：用户消息摘要与运行时通道' },
  fact: { label: '实时事实', color: 'cyan', desc: '工具调用与结果摘要——订单/库存/商品等不能靠模型猜' },
  knowledge: { label: '稳定知识', color: 'purple', desc: 'RAG 命中与引用——政策/规则必须有依据' },
  control: { label: '控制流', color: 'orange', desc: '意图路由/编排/降级/转人工——系统走了哪条路径' },
  result: { label: '结果', color: 'green', desc: '最终回答/搭配/生图结果——与工具和引用对账' },
  safety: { label: '安全', color: 'red', desc: '注入扫描/拒答/脱敏——安全边界是否守住' },
  cost: { label: '成本', color: 'gold', desc: '路径与 token 摘要——这轮为什么贵' },
}

const CATEGORY_COLOR: Record<string, string> = {
  blue: '#1677ff', cyan: '#13c2c2', purple: '#722ed1', orange: '#fa8c16',
  green: '#52c41a', red: '#ff4d4f', gold: '#faad14', default: '#d9d9d9',
}

const join = (v: unknown, fallback = ''): string | null => {
  const s = Array.isArray(v) ? v.filter((x) => x !== null && x !== undefined).join('、') : ''
  return s || fallback || null
}

/** 把事件 payload 翻译成「一句话摘要 + 关键字段行」，按事件类型分别渲染 */
function summarize(e: TraceEvent): { headline: ReactNode; fields: [string, ReactNode][] } {
  let p: any = {}
  try { p = typeof e.payload === 'string' ? JSON.parse(e.payload) : (e.payload ?? {}) } catch { p = { raw: e.payload } }
  const pair = (k: string, v: unknown): [string, ReactNode] | null => {
    if (v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length)) return null
    return [k, Array.isArray(v) ? join(v)! : String(v)]
  }
  switch (e.eventType) {
    case 'entry':
      return {
        headline: <span className="trace-msg">「{p.message || '（空消息）'}」</span>,
        fields: [pair('通道', p.transport), pair('会员等级', p.memberLevel)]
          .filter(Boolean) as [string, ReactNode][],
      }
    case 'done':
      return {
        headline: <span className="trace-msg">{p.reply || '（空回复）'}</span>,
        fields: [pair('耗时', p.latencyMs != null ? `${p.latencyMs} ms` : null)].filter(Boolean) as [string, ReactNode][],
      }
    case 'tool':
      return {
        headline: <span>{p.ok === false ? <Tag color="red">失败</Tag> : null}{p.summary || p.name}</span>,
        fields: [pair('工具', p.name)].filter(Boolean) as [string, ReactNode][],
      }
    case 'rag': {
      const fields: [string, ReactNode][] = []
      const q = pair('查询', p.query); if (q) fields.push(q)
      if (p.statusNotice) fields.push(['状态核验', <Tag color="gold" style={{ fontSize: 10 }}>{p.statusNotice.title} = {p.statusNotice.status}</Tag>])
      const c = pair('引用', p.citations); if (c) fields.push(c)
      return { headline: `ES 混合检索 · 命中 ${p.hits ?? 0} 条规则`, fields }
    }
    case 'plan':
      return {
        headline: p.summary || '意图规划',
        fields: [
          pair('置信度', p.confidence),
          pair('任务链', (p.tasks || []).map((t: any) => (Array.isArray(t) ? t[0] : t?.type)).join(' → ')),
        ].filter(Boolean) as [string, ReactNode][],
      }
    case 'product':
      return {
        headline: `${p.title || '商品检索'} · 命中 ${p.hits ?? 0}`,
        fields: [pair('候选', p.names)].filter(Boolean) as [string, ReactNode][],
      }
    case 'outfit':
      return {
        headline: p.name || '搭配推荐',
        fields: [pair('单品', p.items), pair('规则来源', p.ruleSources)].filter(Boolean) as [string, ReactNode][],
      }
    case 'image':
      return {
        headline: <span>生成「{p.label}」{p.isSimulation ? <Tag color="gold" style={{ fontSize: 10 }}>模拟预览</Tag> : null}</span>,
        fields: [pair('provider', p.provider), pair('服饰', p.garments)].filter(Boolean) as [string, ReactNode][],
      }
    case 'memory':
      return {
        headline: '会话记忆更新',
        fields: [
          pair('已选单品', p.selected), pair('候选单品', p.candidates),
          pair('澄清轮次', p.clarifyCount), pair('长期事实', p.longFacts),
        ].filter(Boolean) as [string, ReactNode][],
      }
    case 'safety':
      return {
        headline: p.blocked ? <span style={{ color: '#cf1322' }}>已拦截：拒绝泄露系统信息</span> : '安全扫描通过',
        fields: [pair('模式', p.mode), pair('拒答主题', p.refusedTopics)].filter(Boolean) as [string, ReactNode][],
      }
    case 'handoff':
      return { headline: <span style={{ color: '#d46b08' }}>转人工：{p.reason}</span>, fields: [] }
    case 'context':
      return {
        headline: `运行时上下文 ${p.items ?? 0} 项`,
        fields: [pair('冲突', p.conflicts)].filter(Boolean) as [string, ReactNode][],
      }
    case 'error':
      return { headline: <span style={{ color: '#cf1322' }}>{p.text || '执行异常'}</span>, fields: [] }
    case 'status':
      return { headline: p.text, fields: [] }
    default: {
      const fields = typeof p === 'object' && p !== null
        ? Object.entries(p).map(([k, v]) => pair(k, v)).filter(Boolean) as [string, ReactNode][]
        : []
      return { headline: null, fields }
    }
  }
}

/** 按需展开的原始 JSON：默认收起，展开后限高滚动，不再撑出一条长块 */
function PayloadDetails({ payload }: { payload: unknown }) {
  const [open, setOpen] = useState(false)
  const empty = payload == null || (typeof payload === 'object' && Object.keys(payload as object).length === 0)
  if (empty) return null
  return (
    <div style={{ marginTop: 4 }}>
      <a onClick={() => setOpen(!open)} style={{ fontSize: 11 }}>
        {open ? '▾ 收起原始数据' : '▸ 原始数据'}
      </a>
      {open && (
        <pre className="trace-json">
          {typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2)}
        </pre>
      )}
    </div>
  )
}

function TraceViewer() {
  const [sessions, setSessions] = useState<TraceSession[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [events, setEvents] = useState<TraceEvent[] | null>(null)
  const [loading, setLoading] = useState(false)

  const loadSessions = async () => {
    try {
      const list = await getTraceSessions()
      setSessions(list)
      // 默认选中最近一轮，右侧不落空
      if (list.length) void loadEvents(list[0].sessionId)
    } catch { setSessions([]) }
  }
  useEffect(() => { loadSessions() }, [])

  const loadEvents = async (sid: string) => {
    setLoading(true)
    setSessionId(sid)
    try { setEvents(await getTrace(sid)) } catch { setEvents([]) }
    setLoading(false)
  }

  return (
    <Card
      title={<span>Trace 查看器 <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 12 }}>
        · 每轮决策的公开证据链：输入 → 路径 → 事实/知识 → 输出与安全边界（不含系统提示词/CoT/隐私原文）</Typography.Text></span>}
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadSessions}>刷新会话</Button>}
    >
      <div className="trace-layout">
        <div className="trace-sessions">
          <Table<TraceSession>
            size="small" rowKey="sessionId" dataSource={sessions} loading={!sessions.length}
            pagination={{ pageSize: 12, size: 'small', hideOnSinglePage: true }}
            onRow={(r) => ({ onClick: () => loadEvents(r.sessionId), style: { cursor: 'pointer' } })}
            rowClassName={(r) => (r.sessionId === sessionId ? 'ant-table-row-selected' : '')}
            columns={[
              {
                title: '会话', dataIndex: 'sessionId', ellipsis: true,
                render: (v: string) => <Typography.Text code style={{ fontSize: 11 }}>{v}</Typography.Text>,
              },
              { title: '事件', dataIndex: 'eventCount', width: 52, align: 'right' },
              {
                title: '最近', dataIndex: 'lastAt', width: 92,
                render: (v: string) => <span style={{ fontSize: 11, color: '#999' }}>{new Date(v).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>,
              },
            ]}
          />
        </div>
        <div className="trace-events">
          {events ? (
            events.length === 0 ? <Empty description="该会话暂无 Trace 记录" /> : (
              <div className="trace-flow">
                {events.map((e) => {
                  const meta = CATEGORY_META[e.category] ?? { label: e.category, color: 'default', desc: '' }
                  let payload: unknown = null
                  try { payload = JSON.parse(e.payload) } catch { payload = e.payload }
                  const { headline, fields } = summarize(e)
                  return (
                    <div key={e.id} className="trace-item">
                      <span className="trace-dot" style={{ background: CATEGORY_COLOR[meta.color] ?? '#d9d9d9' }} />
                      <div className="trace-body">
                        <div className="trace-head">
                          <Tag color={meta.color} style={{ fontSize: 10, lineHeight: '16px', marginInlineEnd: 6 }} title={meta.desc}>{meta.label}</Tag>
                          <Typography.Text code style={{ fontSize: 11 }}>{e.eventType}</Typography.Text>
                          <span className="trace-time">{new Date(e.createdAt).toLocaleTimeString('zh-CN')}</span>
                        </div>
                        {headline != null && <div className="trace-headline">{headline}</div>}
                        {fields.length > 0 && (
                          <div className="trace-fields">
                            {fields.map(([k, v]) => (
                              <div key={k} className="trace-field">
                                <span className="trace-k">{k}</span>
                                <span className="trace-v">{v}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {!headline && fields.length === 0 && <span className="trace-none">（无载荷）</span>}
                        <PayloadDetails payload={payload} />
                      </div>
                    </div>
                  )
                })}
              </div>
            )
          ) : <Empty description="加载中…" />}
        </div>
      </div>
    </Card>
  )
}

function EvalRunner() {
  const [report, setReport] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const run = async () => {
    setLoading(true)
    try { setReport((await runEval()).data) } catch { setReport(null) }
    setLoading(false)
  }
  return (
    <Card
      title={<span>回归评测 <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 12 }}>
        · 固定异常用例断言"事件/工具/引用/禁用文本"，用于检查 Prompt 或工具调整后的行为</Typography.Text></span>}
      extra={<Button type="primary" size="small" icon={<PlayCircleOutlined />} loading={loading} onClick={run}>
        运行评测（约 10 秒）
      </Button>}
    >
      {!report ? (
        <Empty description="点击「运行评测」执行 eval_report（走真实 ES/MCP/Java 链路）" />
      ) : (
        <div>
          <Space style={{ marginBottom: 8 }}>
            <Statistic title="通过" value={report.passed} valueStyle={{ color: report.failed === 0 ? '#3f8600' : '#cf1322' }} />
            <Statistic title="失败" value={report.failed} />
            <Statistic title="总数" value={report.total} />
          </Space>
          <Collapse
            size="small"
            items={(report.cases ?? []).map((c: any) => ({
              key: c.id,
              label: (
                <Space size={6}>
                  <Tag color={c.passed ? 'green' : 'red'}>{c.passed ? 'PASS' : 'FAIL'}</Tag>
                  <span style={{ fontSize: 12 }}>{c.name}</span>
                  {c.failures?.map((f: string) => <Tag key={f} color="volcano" style={{ fontSize: 10 }}>{f}</Tag>)}
                </Space>
              ),
              children: (
                <div style={{ fontSize: 12 }}>
                  <div><Typography.Text strong>输入（用户消息）：</Typography.Text>「{c.message}」</div>
                  <div style={{ marginTop: 4 }}><Typography.Text strong>输出证据：</Typography.Text></div>
                  <pre className="trace-json">
                    {JSON.stringify(c.evidence, null, 2)}
                  </pre>
                </div>
              ),
            }))}
          />
        </div>
      )}
    </Card>
  )
}

export default function ObservePage() {
  const [health, setHealth] = useState<any>(null)
  useEffect(() => { getAgentHealth().then(setHealth).catch(() => setHealth(null)) }, [])

  return (
    <div>
      <PageHeader
        title="可观测"
        description="Trace 是证据（发生了什么），Eval 是回归（改动后没坏）——每轮决策的输入、路径、事实/知识与输出都可复盘"
      />
      <Collapse
        size="small" ghost className="observe-intro"
        items={[{
          key: 'why',
          label: <span style={{ fontSize: 12, color: '#1677ff' }}>为什么需要可观测性？一个可交付的 Agent 还要能证明它按边界工作</span>,
          children: (
            <div style={{ fontSize: 12, color: '#666' }}>
              实时事实走工具、稳定知识带引用、高风险动作有安全边界、每轮路径可复盘。
              改 Prompt/RAG/工具后先跑一遍回归评测再上线。
            </div>
          ),
        }]}
      />
      <Card title="模型与基础设施配置（agent-python/.env）" size="small" className="content-card" style={{ marginBottom: 12 }}>
        <Row gutter={16}>
          <Col span={5}><Statistic title="当前 LLM" value={health?.llm ?? '未知'} valueStyle={{ fontSize: 15 }} /></Col>
          <Col span={4}><Statistic title="模式" value={health?.mockAgent ? 'Mock' : '真实模型'} valueStyle={{ fontSize: 15, color: health?.mockAgent ? '#d46b08' : '#3f8600' }} /></Col>
          <Col span={6}><Statistic title="Embedding" value={health?.embedding === 'none' ? 'none（纯BM25）' : `${health?.embeddingModel ?? ''}`} valueStyle={{ fontSize: 13 }} /></Col>
          <Col span={5}><Statistic title="Reranker" value={health?.rerank?.enabled ? (health.rerank.state === 'ready' ? '已就绪' : health.rerank.state ?? '待加载') : '关闭'} valueStyle={{ fontSize: 13, color: health?.rerank?.enabled && health?.rerank?.state === 'ready' ? '#3f8600' : '#999' }} /></Col>
          <Col span={4}><Statistic title="ES" value={health?.es ? '已连接' : '不可用'} valueStyle={{ fontSize: 15, color: health?.es ? '#3f8600' : '#cf1322' }} /></Col>
        </Row>
        <Space wrap style={{ marginTop: 10 }}>
          <Tag color={health?.indices?.product_index?.exists ? 'green' : 'red'}>
            product_index：{health?.indices?.product_index?.documents ?? 0} 文档 / {health?.indices?.product_index?.vectorDocuments ?? 0} 向量
          </Tag>
          <Tag color={health?.indices?.rule_index?.exists ? 'green' : 'red'}>
            rule_index：{health?.indices?.rule_index?.documents ?? 0} 文档 / {health?.indices?.rule_index?.vectorDocuments ?? 0} 向量
          </Tag>
          <Tag color="blue">
            Hybrid：{health?.hybridRag?.fusion === 'weighted_rrf' ? 'BM25 + kNN → 加权 RRF' : '未知'}
          </Tag>
          <Tag color={health?.tryon?.mode === 'http' && health?.tryon?.providerConfigured ? 'green' : 'gold'}>
            虚拟试衣：{health?.tryon?.mode === 'http'
              ? (health?.tryon?.providerConfigured ? 'HTTP 生图服务' : 'HTTP 模式但未配 TRYON_PROVIDER_URL')
              : 'mock 本地预设图'}
          </Tag>
          <Tag>向量维度：{health?.indices?.product_index?.vectorDims ?? '-'}</Tag>
        </Space>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
          接入真实模型：编辑 agent-python/.env → LLM_BASE_URL / LLM_API_KEY / LLM_MODEL（OpenAI 兼容：DeepSeek/通义/Kimi/Ollama），
          MOCK_AGENT 改 false → 重启 Agent。本地向量检索：EMBEDDING_MODE=ollama + docker compose --profile ollama up -d +
          拉取 qwen3-embedding:0.6b，重跑 scripts/seed.py 重建索引。Reranker 在代码内本地部署（Qwen3-Reranker-0.6B，
          首次自动从 ModelScope 下载，Ollama 不支持 rerank）。详细步骤见 docs/README.md。
        </Typography.Paragraph>
      </Card>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <TraceViewer />
        <EvalRunner />
      </Space>
    </div>
  )
}
