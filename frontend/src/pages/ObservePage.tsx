import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Collapse, Empty, Row, Space, Statistic, Table, Tag,
  Timeline, Typography,
} from 'antd'
import { ReloadOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { TraceEvent, TraceSession, getAgentHealth, getTrace, getTraceSessions, runEval } from '../api'

const CATEGORY_META: Record<string, { label: string; color: string; desc: string }> = {
  entry: { label: '入口', color: 'blue', desc: '请求身份与运行时信息（谁在什么页面问的）' },
  fact: { label: '实时事实', color: 'cyan', desc: '工具调用与结果摘要——订单/库存/商品等不能靠模型猜' },
  knowledge: { label: '稳定知识', color: 'purple', desc: 'RAG 命中与引用——政策/规则必须有依据' },
  control: { label: '控制流', color: 'orange', desc: '意图路由/编排/降级/转人工——系统走了哪条路径' },
  result: { label: '结果', color: 'green', desc: '最终回答/搭配/生图结果——与工具和引用对账' },
  safety: { label: '安全', color: 'red', desc: '注入扫描/拒答/脱敏——安全边界是否守住' },
  cost: { label: '成本', color: 'gold', desc: '路径与 token 摘要——这轮为什么贵' },
}

function TraceViewer() {
  const [sessions, setSessions] = useState<TraceSession[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [events, setEvents] = useState<TraceEvent[] | null>(null)
  const [loading, setLoading] = useState(false)

  const loadSessions = async () => {
    try { setSessions(await getTraceSessions()) } catch { setSessions([]) }
  }
  useEffect(() => { loadSessions() }, [])

  const loadEvents = async (sid: string) => {
    setLoading(true)
    setSessionId(sid)
    try { setEvents(await getTrace(sid)) } catch { setEvents([]) }
    setLoading(false)
  }

  const parse = (p: string) => {
    try { return JSON.parse(p) } catch { return p }
  }

  return (
    <Card
      title={<span>Trace 查看器 <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 12 }}>
        · 每轮决策的公开证据链：谁进来 → 走了哪条路径 → 查了什么事实/知识 → 结果与安全边界（不含系统提示词/CoT/隐私原文）</Typography.Text></span>}
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadSessions}>刷新会话</Button>}
    >
      <Row gutter={12}>
        <Col span={8}>
          <Table<TraceSession>
            size="small" rowKey="sessionId" dataSource={sessions} loading={!sessions.length}
            pagination={false}
            onRow={(r) => ({ onClick: () => loadEvents(r.sessionId), style: { cursor: 'pointer' } })}
            rowClassName={(r) => (r.sessionId === sessionId ? 'ant-table-row-selected' : '')}
            columns={[
              { title: '会话', dataIndex: 'sessionId', ellipsis: true },
              { title: '事件数', dataIndex: 'eventCount', width: 70 },
            ]}
          />
        </Col>
        <Col span={16}>
          {events ? (
            events.length === 0 ? <Empty description="该会话暂无 Trace 记录" /> : (
              <Timeline
                items={events.map((e) => {
                  const meta = CATEGORY_META[e.category] ?? { label: e.category, color: 'default', desc: '' }
                  const payload = parse(e.payload)
                  return {
                    color: meta.color === 'red' ? 'red' : meta.color === 'green' ? 'green' : 'gray',
                    children: (
                      <div style={{ fontSize: 12 }}>
                        <Space size={4}>
                          <Tag color={meta.color} style={{ fontSize: 10 }}>{meta.label}</Tag>
                          <Typography.Text code>{e.eventType}</Typography.Text>
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                            {new Date(e.createdAt).toLocaleTimeString('zh-CN')}
                          </Typography.Text>
                        </Space>
                        <Collapse
                          size="small" ghost items={[{
                            key: String(e.id),
                            label: <span style={{ fontSize: 11, color: '#999' }}>输入/输出明细</span>,
                            children: <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 6, borderRadius: 4, margin: 0 }}>
                              {JSON.stringify(payload, null, 2)}
                            </pre>,
                          }]}
                        />
                      </div>
                    ),
                  }
                })}
              />
            )
          ) : <Empty description="点击左侧会话查看事件流" />}
        </Col>
      </Row>
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
        · 固定事故剧本断言"事件/工具/引用/禁用文本"，证明改 Prompt/工具后没有顾此失彼</Typography.Text></span>}
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
                  <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 6, borderRadius: 4 }}>
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
    <div style={{ maxWidth: 1200 }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 12 }}
        message="为什么需要可观测性？"
        description={
          <div style={{ fontSize: 12 }}>
            一个可交付的 Agent 不能只回答得"像人"，还要能证明它按边界工作：实时事实走工具、稳定知识带引用、
            高风险动作有安全边界、每轮路径可复盘。Trace 是证据（发生了什么），Eval 是回归（改动后没坏），
            成本是治理（哪条路径贵）。改 Prompt/RAG/工具后先跑一遍评测再上线。
          </div>
        }
      />
      <Card title="模型与基础设施配置（agent-python/.env）" size="small" style={{ marginBottom: 12 }}>
        <Row gutter={16}>
          <Col span={6}><Statistic title="当前 LLM" value={health?.llm ?? '未知'} valueStyle={{ fontSize: 16 }} /></Col>
          <Col span={6}><Statistic title="模式" value={health?.mockAgent ? 'Mock 脚本（未配 Key）' : '真实模型'} valueStyle={{ fontSize: 16, color: health?.mockAgent ? '#d46b08' : '#3f8600' }} /></Col>
          <Col span={6}><Statistic title="Embedding" value={health?.embedding ?? '未知'} valueStyle={{ fontSize: 16 }} /></Col>
          <Col span={6}><Statistic title="ES" value={health?.es ? '已连接' : '不可用'} valueStyle={{ fontSize: 16, color: health?.es ? '#3f8600' : '#cf1322' }} /></Col>
        </Row>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
          接入真实模型：编辑 agent-python/.env → LLM_BASE_URL / LLM_API_KEY / LLM_MODEL（OpenAI 兼容：DeepSeek/通义/Kimi/Ollama），
          MOCK_AGENT 改 false → 重启 Agent。Embedding 可选：none=纯 BM25；api=需支持 embedding 的服务（如通义 text-embedding-v3），
          改完后重跑 scripts/seed.py 重建索引。详细步骤见 docs/README.md。
        </Typography.Paragraph>
      </Card>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <TraceViewer />
        <EvalRunner />
      </Space>
    </div>
  )
}
