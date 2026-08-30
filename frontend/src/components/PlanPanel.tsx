// 编排可视化面板：意图 / DAG / 工具 / RAG / 记忆 / 安全 / 上下文 / Trace（生产级证据链）
import { useEffect, useState } from 'react'
import { Alert, Button, Collapse, Empty, Progress, Space, Tag, Timeline, Typography } from 'antd'
import { Tabs } from 'antd'
import { getTrace, TraceEvent } from '../api'

export interface PlanData {
  intents?: any
  dag?: { tasks: { id: string; name: string; type: string; deps: string[] }[] }
  tools?: { name: string; args: any; ok: boolean; summary: string; errorCategory?: string }[]
  ragRules?: { title: string; content: string; source: string; timeValid: boolean; version?: number }[]
  memory?: any
  statuses?: { text: string; stage: string }[]
  safety?: any
  context?: any
  handoff?: string
}

function dagLevels(tasks: { id: string; name: string; type: string; deps: string[] }[]) {
  const levels: Record<string, number> = {}
  const resolve = (t: { id: string; deps: string[] }): number => {
    if (levels[t.id] !== undefined) return levels[t.id]
    const l = t.deps.length === 0 ? 0 : Math.max(...t.deps.map((d) => resolve(tasks.find((x) => x.id === d)!))) + 1
    levels[t.id] = l
    return l
  }
  tasks.forEach(resolve)
  const byLevel: Record<number, typeof tasks> = {}
  tasks.forEach((t) => { (byLevel[levels[t.id]] ??= []).push(t) })
  return Object.keys(byLevel).sort((a, b) => Number(a) - Number(b)).map((k) => byLevel[Number(k)])
}

const typeColor: Record<string, string> = {
  wardrobe: 'blue', rag: 'purple', product: 'cyan', image: 'magenta',
  order: 'orange', favorite: 'gold', clarify: 'red', memory: 'default',
}

const CATEGORY_COLOR: Record<string, string> = {
  entry: 'blue', fact: 'cyan', knowledge: 'purple', control: 'orange',
  result: 'green', safety: 'red', cost: 'gold',
}

function TraceTab({ sessionId }: { sessionId: string }) {
  const [events, setEvents] = useState<TraceEvent[] | null>(null)
  const [loading, setLoading] = useState(false)
  const load = async () => {
    setLoading(true)
    try { setEvents(await getTrace(sessionId)) } catch { setEvents([]) }
    setLoading(false)
  }
  useEffect(() => { load() }, [sessionId])
  return (
    <div>
      <Button size="small" loading={loading} onClick={load} style={{ marginBottom: 8 }}>
        刷新 Trace（共 {events?.length ?? 0} 条）
      </Button>
      {events && events.length > 0 ? (
        <Timeline
          items={events.map((e) => ({
            color: 'gray',
            children: (
              <div style={{ fontSize: 11 }}>
                <Space size={4}>
                  <Tag color={CATEGORY_COLOR[e.category] ?? 'default'} style={{ fontSize: 10 }}>{e.category}</Tag>
                  <Typography.Text code>{e.eventType}</Typography.Text>
                </Space>
                <div style={{ color: '#999' }}>{e.payload?.slice(0, 120)}</div>
              </div>
            ),
          }))}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 Trace 记录" />
      )}
    </div>
  )
}

export default function PlanPanel({ data, sessionId }: { data: PlanData; sessionId: string }) {
  const levels = data.dag?.tasks?.length ? dagLevels(data.dag.tasks) : []
  return (
    <Tabs
      size="small" items={[
        {
          key: 'dag', label: '编排 DAG',
          children: data.dag ? (
            <div style={{ padding: 4 }}>
              {levels.map((level, li) => (
                <div key={li} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <Space wrap style={{ justifyContent: 'center' }}>
                    {level.map((t) => (
                      <Tag key={t.id} color={typeColor[t.type] ?? 'default'} style={{ marginInlineEnd: 4 }}>
                        {t.name}
                      </Tag>
                    ))}
                  </Space>
                  {li < levels.length - 1 && <div style={{ color: '#999', fontSize: 14 }}>↓（依赖拓扑排序，同层并行）</div>}
                </div>
              ))}
            </div>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无编排数据" />,
        },
        {
          key: 'intent', label: '意图识别',
          children: data.intents ? (
            <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 8, borderRadius: 6 }}>
              {JSON.stringify(data.intents, null, 2)}
            </pre>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无" />,
        },
        {
          key: 'tools', label: `工具调用 (${data.tools?.length ?? 0})`,
          children: data.tools?.length ? (
            <Timeline
              items={data.tools.map((t) => ({
                color: t.ok ? 'green' : 'red',
                children: (
                  <div style={{ fontSize: 12 }}>
                    <Space size={4} wrap>
                      <Typography.Text strong>{t.name}</Typography.Text>
                      <Tag color={t.ok ? 'green' : 'red'}>{t.ok ? '成功' : '失败'}</Tag>
                      {t.errorCategory && <Tag color="volcano">{t.errorCategory}</Tag>}
                    </Space>
                    <div style={{ color: '#666' }}>{t.summary}</div>
                    <pre style={{ fontSize: 11, background: '#fafafa', padding: 4, borderRadius: 4, maxHeight: 80, overflow: 'auto' }}>
                      {JSON.stringify(t.args, null, 2)}
                    </pre>
                  </div>
                ),
              }))}
            />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工具调用" />,
        },
        {
          key: 'rag', label: 'RAG 规则',
          children: data.ragRules?.length ? (
            <Collapse
              size="small"
              items={data.ragRules.map((r, i) => ({
                key: String(i),
                label: (
                  <Space size={4}>
                    <span style={{ fontSize: 12 }}>{r.title}</span>
                    <Tag color={r.timeValid ? 'green' : 'red'}>{r.timeValid ? '时间窗内' : '已过滤'}</Tag>
                  </Space>
                ),
                children: <div style={{ fontSize: 12, color: '#666' }}>{r.content}<br />来源: {r.source}{r.version ? ` · v${r.version}` : ''}</div>,
              }))}
            />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无规则召回" />,
        },
        {
          key: 'safety', label: '安全边界',
          children: data.safety ? (
            <div>
              <Alert
                type={data.safety.blocked ? 'error' : 'success'}
                message={data.safety.blocked ? '已拦截：拒绝泄露系统信息/覆盖指令' : `安全扫描通过（模式: ${data.safety.mode}）`}
                description={
                  <div style={{ fontSize: 12 }}>
                    {data.safety.refusedTopics?.length ? <div>拒绝主题: {data.safety.refusedTopics.join(', ')}</div> : null}
                    <pre style={{ background: '#fafafa', padding: 4, borderRadius: 4, marginTop: 4 }}>
                      {JSON.stringify(data.safety.scans ?? data.safety, null, 2)}
                    </pre>
                  </div>
                }
              />
            </div>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无安全扫描结果" />,
        },
        {
          key: 'context', label: '上下文',
          children: data.context ? (
            <div>
              <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>{data.context.rules}</div>
              {data.context.items?.map((it: any, i: number) => (
                <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
                  <Space size={4}>
                    <Tag color={it.trust_level === 'high' ? 'green' : it.trust_level === 'medium' ? 'gold' : 'default'}
                      style={{ fontSize: 10 }}>{it.trust_level}</Tag>
                    <Typography.Text code>{it.source}</Typography.Text>
                  </Space>
                  <span style={{ color: '#888' }}>{it.content}</span>
                </div>
              ))}
              {(data.context.conflicts?.length ?? 0) > 0 && (
                <Alert type="warning" style={{ marginTop: 6 }} message="冲突解析" description={
                  <pre style={{ fontSize: 11, margin: 0 }}>{JSON.stringify(data.context.conflicts, null, 2)}</pre>
                } />
              )}
            </div>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无上下文组装信息" />,
        },
        {
          key: 'memory', label: '会话记忆',
          children: data.memory ? (
            <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 8, borderRadius: 6 }}>
              {JSON.stringify(data.memory, null, 2)}
            </pre>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无" />,
        },
        {
          key: 'trace', label: 'Trace 证据',
          children: <TraceTab sessionId={sessionId} />,
        },
        {
          key: 'status', label: '执行状态',
          children: data.statuses?.length ? (
            <Timeline items={data.statuses.map((s) => ({ children: <span style={{ fontSize: 12 }}>{s.text}</span> }))} />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无" />,
        },
      ]}
    />
  )
}

export function ProgressLine({ percent, stage }: { percent: number; stage: string }) {
  return (
    <div style={{ padding: '6px 0' }}>
      <Space><Typography.Text type="secondary" style={{ fontSize: 12 }}>{stage}</Typography.Text></Space>
      <Progress percent={percent} size="small" status={percent >= 100 ? 'success' : 'active'} />
    </div>
  )
}
