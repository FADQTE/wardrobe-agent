import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, Empty, Form, Input, Modal, Popconfirm, Row, Select,
  Space, Tag, Upload, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { useUser } from '../App'
import {
  WardrobeItem, addWardrobeItem, deleteWardrobeItem, listWardrobe, updateWardrobeItem, uploadFile,
} from '../api'

const CATEGORY_MAP: Record<string, string> = {
  top: '上装', bottom: '下装', outerwear: '外套', dress: '连衣裙', shoes: '鞋履', accessory: '配饰',
}
const COLOR_OPTIONS = ['白色', '黑色', '浅蓝', '深蓝', '藏青', '灰色', '卡其', '米色', '粉色', '碎花', '墨绿', '酒红', '棕色', '银色', '黄色', '红色', '紫色', '橙色', '驼色']
const SEASON_OPTIONS = ['春', '夏', '秋', '冬', '春秋', '秋冬', '春夏', '四季']
const STYLE_OPTIONS = ['通勤', '休闲', '运动', '约会', '正式']

const parseTags = (tags?: string): string[] => {
  if (!tags) return []
  try { return JSON.parse(tags) } catch { return [] }
}

export default function WardrobePage() {
  const { user } = useUser()
  const [items, setItems] = useState<WardrobeItem[]>([])
  const [loading, setLoading] = useState(false)
  const [catFilter, setCatFilter] = useState<string>('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<WardrobeItem | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    if (!user) return
    setLoading(true)
    try { setItems(await listWardrobe(user.id)) } catch { /* 后端未启动 */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [user])

  const filtered = useMemo(
    () => (catFilter ? items.filter((i) => i.category === catFilter) : items),
    [items, catFilter],
  )

  const openAdd = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ category: 'top', season: '四季', style: '休闲' })
    setModalOpen(true)
  }

  const openEdit = (item: WardrobeItem) => {
    setEditing(item)
    form.setFieldsValue({ ...item, tags: parseTags(item.tags) })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    const payload = { ...values, tags: JSON.stringify(values.tags ?? []) }
    if (editing) await updateWardrobeItem(editing.id, { ...payload, userId: editing.userId })
    else await addWardrobeItem({ ...payload, userId: user!.id })
    message.success(editing ? '已更新' : '已添加')
    setModalOpen(false)
    load()
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Select
          allowClear placeholder="按类目筛选" style={{ width: 140 }} value={catFilter || undefined}
          onChange={(v) => setCatFilter(v ?? '')}
          options={Object.entries(CATEGORY_MAP).map(([k, v]) => ({ value: k, label: v }))}
        />
        <span style={{ color: '#999' }}>共 {filtered.length} 件单品 · 标签与商城商品同构，支持“已有单品+在售商品”混合搭配</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>添加单品</Button>
      </Space>
      {filtered.length === 0 && !loading ? (
        <Empty description="衣橱空空如也，添加一件单品吧" />
      ) : (
        <Row gutter={[12, 12]}>
          {filtered.map((item) => (
            <Col key={item.id} xs={12} sm={8} md={6} lg={4}>
              <Card
                hoverable
                cover={
                  <img
                    alt={item.name} src={item.imageUrl || '/seed-images/wardrobe_1.svg'}
                    style={{ height: 180, objectFit: 'cover' }}
                    onError={(e) => { (e.target as HTMLImageElement).src = '/seed-images/wardrobe_1.svg' }}
                  />
                }
                actions={[
                  <EditOutlined key="edit" onClick={() => openEdit(item)} />,
                  <Popconfirm key="del" title="删除这件单品？" onConfirm={async () => { await deleteWardrobeItem(item.id); load() }}>
                    <DeleteOutlined />
                  </Popconfirm>,
                ]}
              >
                <Card.Meta
                  title={<span style={{ fontSize: 13 }}>{item.name}</span>}
                  description={
                    <Space size={4} wrap>
                      <Tag color="blue">{CATEGORY_MAP[item.category] ?? item.category}</Tag>
                      {item.color && <Tag>{item.color}</Tag>}
                      {item.season && <Tag>{item.season}</Tag>}
                      {item.style && <Tag color="purple">{item.style}</Tag>}
                    </Space>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title={editing ? '编辑单品' : '添加单品'} open={modalOpen}
        onOk={submit} onCancel={() => setModalOpen(false)} destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：白色基础衬衫" />
          </Form.Item>
          <Space size={8} wrap>
            <Form.Item name="category" label="类目" rules={[{ required: true }]}>
              <Select style={{ width: 110 }} options={Object.entries(CATEGORY_MAP).map(([k, v]) => ({ value: k, label: v }))} />
            </Form.Item>
            <Form.Item name="color" label="颜色">
              <Select style={{ width: 100 }} options={COLOR_OPTIONS.map((c) => ({ value: c, label: c }))} />
            </Form.Item>
            <Form.Item name="season" label="季节">
              <Select style={{ width: 100 }} options={SEASON_OPTIONS.map((c) => ({ value: c, label: c }))} />
            </Form.Item>
            <Form.Item name="style" label="风格">
              <Select style={{ width: 100 }} options={STYLE_OPTIONS.map((c) => ({ value: c, label: c }))} />
            </Form.Item>
          </Space>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="回车添加自定义标签" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input placeholder="购买渠道/尺码等" />
          </Form.Item>
          <Form.Item label="图片">
            <Upload
              showUploadList={false} customRequest={async ({ file, onSuccess, onError }) => {
                try {
                  const url = await uploadFile(file as File)
                  form.setFieldsValue({ imageUrl: url })
                  onSuccess?.(url)
                  message.success('上传成功')
                } catch (e) { onError?.(e as Error) }
              }}
            >
              <Button icon={<UploadOutlined />}>上传图片（可选，默认占位图）</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="imageUrl" noStyle><Input type="hidden" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
