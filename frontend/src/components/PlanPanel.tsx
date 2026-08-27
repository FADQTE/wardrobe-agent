// 编排可视化面板：意图 JSON / DAG / 工具调用 / RAG 规则 / 会话记忆
import { Collapse, Empty, Progress, Space, Tag, Timeline, Typography } from 'antd'
import { Tabs } from 'antd'

export interface PlanData {
  intents?: any[]
  dag?: { tasks: { id: string; name: string; type: string; deps: string[] }[] }
  tools?: { name: string; args: any; ok: boolean; summary: string }[]
  ragRules?: { title: string; content: string; source: string; timeValid: boolean; version?: number }[]
  memory?: any
  statuses?: { text: string; stage: string }[]
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

export default function PlanPanel({ data }: { data: PlanData }) {
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
          key: 'memory', label: '会话记忆',
          children: data.memory ? (
            <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 8, borderRadius: 6 }}>
              {JSON.stringify(data.memory, null, 2)}
            </pre>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无" />,
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
