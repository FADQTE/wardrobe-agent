import { useEffect, useState } from 'react'
import {
  Button, Card, Empty, Input, Modal, Space, Table, Tag, Typography, message,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import PageHeader from '../components/PageHeader'
import { AfterSaleRow, adminListAfterSales, adminReviewAfterSale } from '../api'

const STATUS_TABS = [
  { value: 'pending', label: '待人工审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
]
const STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '待人工审核', color: 'orange' },
  approved: { text: '已通过', color: 'green' },
  rejected: { text: '已驳回', color: 'red' },
  completed: { text: '已完成', color: 'default' },
}
const TYPE_TEXT: Record<string, string> = {
  refund: '仅退款', return_refund: '退货退款', exchange: '换货',
}
const REVIEW_SOURCE: Record<string, { text: string; color: string }> = {
  auto: { text: '规则自动审核', color: 'blue' },
  manual: { text: '人工审核', color: 'purple' },
}

export default function AdminPage() {
  const [status, setStatus] = useState('pending')
  const [rows, setRows] = useState<AfterSaleRow[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      setRows(await adminListAfterSales(status))
    } catch (e: any) {
      message.error(e.message || '加载失败')
      setRows([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [status])

  const review = async (row: AfterSaleRow, action: 'approve' | 'reject') => {
    let reason = ''
    Modal.confirm({
      title: action === 'approve' ? '通过该售后申请' : '驳回该售后申请',
      content: (
        <Input
          placeholder={action === 'approve' ? '通过原因（可空）' : '驳回原因（建议填写）'}
          onChange={(e) => { reason = e.target.value }}
        />
      ),
      okText: action === 'approve' ? '确认通过' : '确认驳回',
      okButtonProps: { danger: action === 'reject' },
      onOk: async () => {
        try {
          await adminReviewAfterSale(row.sale.id, action, reason)
          message.success(action === 'approve' ? '已通过，退款已执行' : '已驳回')
          await load()
        } catch (e: any) {
          message.error(e.message || '操作失败')
        }
      },
    })
  }

  return (
    <div>
      <PageHeader
        title="人工客服工作台"
        description="AI 只能创建申请并通过符合规则的退款；其余转人工，在这里通过或驳回"
        extra={
          <Space>
            {STATUS_TABS.map((tab) => (
              <Button
                key={tab.value} size="small" type={status === tab.value ? 'primary' : 'default'}
                onClick={() => setStatus(tab.value)}
              >
                {tab.label}
              </Button>
            ))}
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
          </Space>
        }
      />
      <Card size="small" className="content-card">
        <Table<AfterSaleRow>
          rowKey={(row) => String(row.sale.id)}
          dataSource={rows} loading={loading} size="middle"
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          locale={{ emptyText: <Empty description="该状态下暂无售后单" /> }}
          columns={[
            { title: '申请单号', dataIndex: ['sale', 'requestNo'], width: 180,
              render: (v: string) => <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text> },
            { title: '订单号', dataIndex: ['order', 'orderNo'], width: 180,
              render: (v: string, row) => v || `订单 #${row.sale.orderId}` },
            { title: '类型', dataIndex: ['sale', 'type'], width: 100,
              render: (v: string) => <Tag>{TYPE_TEXT[v] ?? v}</Tag> },
            { title: '金额', dataIndex: ['sale', 'amount'], width: 100,
              render: (v: number) => `¥${v}` },
            { title: '状态', dataIndex: ['sale', 'status'], width: 110,
              render: (v: string) => <Tag color={STATUS_META[v]?.color}>{STATUS_META[v]?.text ?? v}</Tag> },
            {
              title: '审核判定', width: 220,
              render: (_, row) => (
                <Space size={4} wrap>
                  {row.sale.reviewSource && (
                    <Tag color={REVIEW_SOURCE[row.sale.reviewSource]?.color} style={{ fontSize: 10 }}>
                      {REVIEW_SOURCE[row.sale.reviewSource]?.text}
                    </Tag>
                  )}
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    {row.sale.reviewReason || row.sale.reason || '-'}
                  </Typography.Text>
                </Space>
              ),
            },
            { title: '申请时间', dataIndex: ['sale', 'createdAt'], width: 100,
              render: (v: string) => <span style={{ fontSize: 11, color: '#999' }}>{v}</span> },
            {
              title: '操作', fixed: 'right', width: 150,
              render: (_, row) => row.sale.status === 'pending' ? (
                <Space size={4}>
                  <Button size="small" type="primary" onClick={() => void review(row, 'approve')}>通过</Button>
                  <Button size="small" danger onClick={() => void review(row, 'reject')}>驳回</Button>
                </Space>
              ) : '-',
            },
          ]}
        />
      </Card>
    </div>
  )
}
