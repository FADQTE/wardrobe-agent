// 编排过程面板（重设计版）：按阶段分组的事件流，每个事件可展开查看输入/输出明细。
// 阶段顺序 = 真实链路：安全边界 → 上下文 → 意图与编排 → 执行（工具/RAG） → 汇总与记忆
import { useState } from 'react'
import {
  Alert, Badge, Button, Collapse, Empty, Progress, Space, Tag, Timeline, Tooltip, Typography,
} from 'antd'
import { DownOutlined, QuestionCircleOutlined, UpOutlined } from '@ant-design/icons'

export interface PlanData {
  intents?: any
  dag?: { tasks: { id: string; name: string; type: string; deps: string[] }[] }
  tools?: { name: string; args: any; ok: boolean; summary: string; errorCategory?: string }[]
  ragRules?: { title: string; content: string; source: string; timeValid: boolean; version?: number;
    retrievalMode?: string; retrievalChannels?: string[]; rrfScore?: number }[]
  memory?: any
  statuses?: { text: string; stage: string }[]
  safety?: any
  context?: any
  handoff?: string
}

const typeColor: Record<string, string> = {
  wardrobe: 'blue', rag: 'purple', product: 'cyan', image: 'magenta',
  order: 'orange', favorite: 'gold', clarify: 'red', memory: 'default',
}

const PHASES = [
  { key: 'safety', title: '① 安全边界', desc: '外部文本扫描：注入/越权/隐私 → 拦截或放行', color: 'red' },
  { key: 'context', title: '② 上下文', desc: '多来源按可信度组装，冲突按系统事实裁决', color: 'gold' },
  { key: 'intent', title: '③ 意图与编排', desc: '结构化拆解 → 依赖 DAG（同层并行、依赖按拓扑序）', color: 'blue' },
  { key: 'execute', title: '④ 执行', desc: 'MCP 工具与 RAG 检索：实时事实 + 稳定知识', color: 'green' },
  { key: 'result', title: '⑤ 汇总与记忆', desc: '搭配结果、规则来源与跨轮记忆', color: 'purple' },
]

function JsonBlock({ data }: { data: any }) {
  return (
    <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 6, borderRadius: 4, margin: 0 }}>
      {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
    </pre>
  )
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

export default function PlanPanel({ data }: { data: PlanData }) {
  const [activeKeys, setActiveKeys] = useState<string[]>(['safety', 'context', 'intent', 'execute', 'result'])
  const allKeys = PHASES.map((p) => p.key)
  const totalEvents =
    (data.tools?.length ?? 0) + (data.ragRules?.length ?? 0) + (data.statuses?.length ?? 0) + 3

  const expandAll = () => setActiveKeys(allKeys)
  const collapseAll = () => setActiveKeys([])

  const dag = data.dag?.tasks?.length ? dagLevels(data.dag.tasks) : []

  const items = PHASES.map((phase) => {
    let children: React.ReactNode = <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本轮无此阶段数据" />
    let badge = 0

    if (phase.key === 'safety') {
      badge = data.safety ? 1 : 0
      children = data.safety ? (
        <div>
          <Alert
            type={data.safety.blocked ? 'error' : 'success'} showIcon
            message={data.safety.blocked ? '已拦截（拒答，不进入业务编排）' : `扫描通过（模式: ${data.safety.mode}）`}
            description={data.safety.blocked ? (
              <div style={{ fontSize: 12 }}>拒绝主题：{data.safety.refusedTopics?.join(', ')}</div>
            ) : undefined}
          />
          <JsonBlock data={data.safety} />
        </div>
      ) : children
    } else if (phase.key === 'context') {
      badge = data.context?.items?.length ?? 0
      children = data.context ? (
        <div>
          <Timeline
            items={(data.context.items ?? []).map((it: any) => ({
              color: it.trust_level === 'high' ? 'green' : it.trust_level === 'medium' ? 'gold' : 'gray',
              children: (
                <div style={{ fontSize: 12 }}>
                  <Space size={4}>
                    <Tag color={it.trust_level === 'high' ? 'green' : it.trust_level === 'medium' ? 'gold' : 'default'} style={{ fontSize: 10 }}>
                      {it.trust_level}
                    </Tag>
                    <Typography.Text code>{it.source}</Typography.Text>
                  </Space>
                  <div style={{ color: '#888' }}>{it.content}</div>
                </div>
              ),
            }))}
          />
          {(data.context.conflicts?.length ?? 0) > 0 && (
            <Alert type="warning" showIcon style={{ marginTop: 6 }} message="冲突解析（用户自称 vs 系统事实）"
              description={<JsonBlock data={data.context.conflicts} />} />
          )}
        </div>
      ) : children
    } else if (phase.key === 'intent') {
      badge = (data.dag?.tasks?.length ?? 0)
      children = data.intents ? (
        <div>
          {data.dag && (
            <div style={{ marginBottom: 8 }}>
              {dag.map((level, li) => (
                <div key={li} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 4 }}>
                  <Space wrap style={{ justifyContent: 'center' }}>
                    {level.map((t) => (
                      <Tooltip key={t.id} title={`deps: ${t.deps.join(', ') || '无'}`}>
                        <Tag color={typeColor[t.type] ?? 'default'} style={{ marginInlineEnd: 4 }}>{t.name}</Tag>
                      </Tooltip>
                    ))}
                  </Space>
                  {li < dag.length - 1 && <div style={{ color: '#999', fontSize: 12 }}>↓（依赖拓扑排序，同层并行）</div>}
                </div>
              ))}
            </div>
          )}
          <JsonBlock data={data.intents} />
        </div>
      ) : children
    } else if (phase.key === 'execute') {
      badge = (data.tools?.length ?? 0) + (data.ragRules?.length ?? 0)
      children = (data.statuses?.length || data.tools?.length || data.ragRules?.length) ? (
        <div>
          <Timeline
            items={(data.statuses ?? []).map((s) => ({
              color: s.stage === 'handoff' ? 'red' : 'gray',
              children: <span style={{ fontSize: 12 }}>{s.text}</span>,
            }))}
          />
          {(data.tools ?? []).map((t, i) => (
            <div key={`t${i}`} style={{ fontSize: 12, marginBottom: 6, paddingLeft: 16 }}>
              <Space size={4} wrap>
                <Badge status={t.ok ? 'success' : 'error'} />
                <Typography.Text strong>{t.name}</Typography.Text>
                {t.errorCategory && <Tag color="volcano" style={{ fontSize: 10 }}>{t.errorCategory}</Tag>}
              </Space>
              <div style={{ color: '#666' }}>{t.summary}</div>
              <Collapse
                size="small" ghost items={[{
                  key: `t${i}d`,
                  label: <span style={{ fontSize: 11, color: '#999' }}>输入参数</span>,
                  children: <JsonBlock data={t.args} />,
                }]}
              />
            </div>
          ))}
          {(data.ragRules ?? []).map((r, i) => (
            <div key={`r${i}`} style={{ fontSize: 12, marginBottom: 6, paddingLeft: 16 }}>
              <Space size={4} wrap>
                <Tag color="purple" style={{ fontSize: 10 }}>RAG</Tag>
                <span>{r.title}</span>
                <Tag color={r.timeValid ? 'green' : 'red'} style={{ fontSize: 10 }}>{r.timeValid ? '时间窗内' : '已过滤'}</Tag>
                {r.retrievalMode && <Tag color="blue" style={{ fontSize: 10 }}>{r.retrievalMode}</Tag>}
                {(r.retrievalChannels?.length ?? 0) > 0 && (
                  <Tag style={{ fontSize: 10 }}>{r.retrievalChannels?.join(' + ')}</Tag>
                )}
                <span style={{ color: '#999' }}>· {r.source}</span>
              </Space>
              <div style={{ color: '#888' }}>{r.content}</div>
            </div>
          ))}
        </div>
      ) : children
    } else if (phase.key === 'result') {
      badge = data.memory ? 1 : 0
      children = (
        <div>
          {data.handoff && <Alert type="warning" showIcon message="已转人工（关键事实不可用，不猜答案）" description={data.handoff} style={{ marginBottom: 8 }} />}
          <JsonBlock data={data.memory ?? { note: '本轮无记忆更新' }} />
        </div>
      )
    }

    return {
      key: phase.key,
      label: (
        <Space size={6}>
          <Typography.Text strong style={{ fontSize: 13 }}>{phase.title}</Typography.Text>
          <Badge count={badge} size="small" showZero={false} color={phase.color} />
          <Typography.Text type="secondary" style={{ fontSize: 11, fontWeight: 400 }}>{phase.desc}</Typography.Text>
        </Space>
      ),
      children,
    }
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <Space size={4}>
          <Typography.Text strong style={{ fontSize: 13 }}>本轮编排过程</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>共 {totalEvents} 项</Typography.Text>
          <Tooltip title="面板按真实链路分五阶段：安全扫描 → 上下文组装 → 意图/DAG → 工具与RAG执行 → 汇总与记忆。每项可展开查看输入/输出明细，帮助你理解 Agent 每一步在做什么。">
            <QuestionCircleOutlined style={{ color: '#999' }} />
          </Tooltip>
        </Space>
        <Space size={4}>
          <Button size="small" type="text" icon={<DownOutlined />} onClick={expandAll} title="全部展开" />
          <Button size="small" type="text" icon={<UpOutlined />} onClick={collapseAll} title="全部收起" />
        </Space>
      </div>
      <div style={{ flex: 1, overflow: 'auto', paddingRight: 2 }}>
        <Collapse
          size="small" activeKey={activeKeys} onChange={(k) => setActiveKeys(k as string[])}
          items={items}
        />
      </div>
    </div>
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
