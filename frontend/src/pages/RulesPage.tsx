import { useEffect, useState } from 'react'
import {
  Button, Card, DatePicker, Form, Input, InputNumber, Modal, Popconfirm, Select, Space,
  Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import PageHeader from '../components/PageHeader'
import { Rule, listRules, offlineRule, publishRule, saveRule } from '../api'

const STATUS_META: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'orange' },
  published: { text: '已发布', color: 'green' },
  offline: { text: '已下线', color: 'default' },
}

const expired = (r: Rule) => r.effectiveTo && dayjs(r.effectiveTo).isBefore(dayjs())

// 生效时间列：ISO 串太长易换行，统一压成「MM-DD HH:mm ~ MM-DD HH:mm」
const fmtSpan = (from?: string | null, to?: string | null) => {
  const f = (v?: string | null) => (v ? dayjs(v).format('MM-DD HH:mm') : '-')
  return `${f(from)} ~ ${f(to)}`
}

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([])
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string>()
  const [statusFilter, setStatusFilter] = useState<string>()
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Rule | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setRules(await listRules(typeFilter, statusFilter)) } catch { /* 后端未启动 */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [typeFilter, statusFilter])

  const openAdd = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ type: 'outfit', version: 1, publishStatus: 'draft' })
    setModalOpen(true)
  }

  const openEdit = (r: Rule) => {
    setEditing(r)
    form.setFieldsValue({
      ...r,
      tags: (() => { try { return JSON.parse(r.tags || '[]') } catch { return [] } })(),
      effectiveFrom: r.effectiveFrom ? dayjs(r.effectiveFrom) : null,
      effectiveTo: r.effectiveTo ? dayjs(r.effectiveTo) : null,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    const payload = {
      ...v,
      tags: JSON.stringify(v.tags ?? []),
      effectiveFrom: v.effectiveFrom ? v.effectiveFrom.format('YYYY-MM-DD HH:mm:ss') : null,
      effectiveTo: v.effectiveTo ? v.effectiveTo.format('YYYY-MM-DD HH:mm:ss') : null,
    }
    if (editing) {
      await saveRule(payload, editing.id)
      message.success('已保存')
    } else {
      await saveRule(payload)
      message.success('已创建草稿')
    }
    setModalOpen(false)
    load()
  }

  const pub = async (id: number) => {
    await publishRule(id)
    message.success('已发布：ES 索引已增量更新，旧版本已下架')
    load()
  }

  const off = async (id: number) => {
    await offlineRule(id)
    message.success('已下线，索引与缓存已同步失效')
    load()
  }

  return (
    <div>
      <PageHeader
        title="规则管理"
        description="活动与穿搭规则的发布、下线和版本管理；查询侧按当前时间窗过滤，过期/未生效/未发布的规则不会被 AI 客服召回"
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新建规则</Button>}
      />
      <Card size="small" className="toolbar-card">
        <Space wrap>
          <Select allowClear placeholder="类型" style={{ width: 120 }} value={typeFilter}
            onChange={setTypeFilter}
            options={[{ value: 'activity', label: '活动规则' }, { value: 'outfit', label: '穿搭规则' }]} />
          <Select allowClear placeholder="状态" style={{ width: 120 }} value={statusFilter}
            onChange={setStatusFilter}
            options={[{ value: 'published', label: '已发布' }, { value: 'draft', label: '草稿' }, { value: 'offline', label: '已下线' }]} />
          <span style={{ color: '#999', fontSize: 12 }}>共 {rules.length} 条</span>
        </Space>
      </Card>
      <Card size="small" className="content-card">
        <Table
        rowKey="id" dataSource={rules} loading={loading} size="middle"
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '标题', dataIndex: 'title', width: 200 },
          { title: '类型', dataIndex: 'type', width: 90, render: (t) => (t === 'activity' ? <Tag color="blue">活动</Tag> : <Tag color="purple">穿搭</Tag>) },
          { title: '版本', dataIndex: 'version', width: 60, render: (v) => `v${v}` },
          { title: '生效时间', width: 190, render: (_, r) => <span style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{fmtSpan(r.effectiveFrom, r.effectiveTo)}</span> },
          {
            title: '状态', width: 110, render: (_, r) => (
              <Space size={4}>
                <Tag color={STATUS_META[r.publishStatus]?.color}>{STATUS_META[r.publishStatus]?.text}</Tag>
                {r.publishStatus === 'published' && expired(r) && <Tag color="red">已过期</Tag>}
                {r.publishStatus === 'published' && r.effectiveFrom && dayjs(r.effectiveFrom).isAfter(dayjs()) && <Tag color="gold">未生效</Tag>}
              </Space>
            ),
          },
          { title: '内容', dataIndex: 'content', ellipsis: true },
          { title: '来源', dataIndex: 'source', width: 100 },
          {
            title: '操作', width: 160, render: (_, r) => (
              <Space size={4}>
                <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                {r.publishStatus !== 'published' && (
                  <Button size="small" type="primary" onClick={() => pub(r.id)}>发布</Button>
                )}
                {r.publishStatus === 'published' && (
                  <Popconfirm title="下线该规则？" onConfirm={() => off(r.id)}>
                    <Button size="small" danger>下线</Button>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />
      </Card>

      <Modal
        title={editing ? `编辑规则 #${editing.id}` : '新建规则'} open={modalOpen} width={560}
        onOk={submit} onCancel={() => setModalOpen(false)} destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Space size={8}>
            <Form.Item name="type" label="类型" rules={[{ required: true }]}>
              <Select style={{ width: 130 }} options={[{ value: 'activity', label: '活动规则' }, { value: 'outfit', label: '穿搭规则' }]} />
            </Form.Item>
            <Form.Item name="version" label="版本" rules={[{ required: true }]}>
              <InputNumber min={1} style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="publishStatus" label="发布状态">
              <Select style={{ width: 110 }} options={[{ value: 'draft', label: '草稿' }, { value: 'published', label: '已发布' }, { value: 'offline', label: '已下线' }]} />
            </Form.Item>
            <Form.Item name="source" label="来源">
              <Input style={{ width: 130 }} placeholder="运营平台/穿搭师团队" />
            </Form.Item>
          </Space>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="如：秋季通勤焕新季" />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="规则内容，将进入 ES rule_index 供 RAG 召回" />
          </Form.Item>
          <Form.Item name="tags" label="标签（参与检索过滤）">
            <Select mode="tags" placeholder="如：秋、通勤、满减" open={false} suffixIcon={null} />
          </Form.Item>
          <Space size={8}>
            <Form.Item name="effectiveFrom" label="生效时间">
              <DatePicker showTime style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="effectiveTo" label="失效时间">
              <DatePicker showTime style={{ width: 200 }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
