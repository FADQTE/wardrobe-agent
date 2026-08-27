import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Col, Drawer, Empty, Input, InputNumber, message, Row, Select,
  Space, Spin, Table, Tag, Tooltip,
} from 'antd'
import { SearchOutlined, ShoppingCartOutlined, StarFilled, ExperimentOutlined } from '@ant-design/icons'
import { useUser } from '../App'
import {
  Order, Product, addFavorite, createOrder, esSearchProducts, listOrders, payOrder, searchProducts,
} from '../api'

const CATEGORY_OPTIONS = [
  { value: 'top', label: '上装' }, { value: 'bottom', label: '下装' }, { value: 'outerwear', label: '外套' },
  { value: 'dress', label: '连衣裙' }, { value: 'shoes', label: '鞋履' }, { value: 'accessory', label: '配饰' },
]
const COLOR_OPTIONS = ['白色', '黑色', '浅蓝', '深蓝', '藏青', '灰色', '卡其', '米色', '粉色', '碎花', '墨绿', '酒红', '棕色']
const SEASON_OPTIONS = ['春', '夏', '秋', '冬', '春秋', '秋冬', '春夏', '四季']
const STYLE_OPTIONS = ['通勤', '休闲', '运动', '约会', '正式']

const parseTags = (tags?: string): string[] => {
  if (!tags) return []
  try { return JSON.parse(tags) } catch { return [] }
}

const ORDER_STATUS: Record<string, { text: string; color: string }> = {
  pending: { text: '待支付', color: 'orange' },
  paid: { text: '已支付', color: 'blue' },
  shipped: { text: '已发货', color: 'geekblue' },
  done: { text: '已完成', color: 'green' },
  cancelled: { text: '已取消', color: 'default' },
}

export default function MallPage() {
  const { user } = useUser()
  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [searchMode, setSearchMode] = useState<'es' | 'mysql'>('es')
  const [keyword, setKeyword] = useState('')
  const [filters, setFilters] = useState<Record<string, string | number | undefined>>({})
  const [detail, setDetail] = useState<Product | null>(null)
  const [ordersOpen, setOrdersOpen] = useState(false)
  const [orders, setOrders] = useState<Order[]>([])
  const [buying, setBuying] = useState(false)
  const userRef = useRef(user)
  userRef.current = user

  const doSearch = async (kw?: string, flt?: Record<string, string | number | undefined>) => {
    setLoading(true)
    const params = { keyword: kw ?? keyword, ...(flt ?? filters), page: 1, size: 24 }
    try {
      const res = await esSearchProducts(params) // ES 混合检索（BM25 + 向量 + 标签过滤）
      setProducts(res.data.products)
      setTotal(res.data.total)
      setSearchMode('es')
    } catch {
      const res = await searchProducts(params) // MySQL 兜底
      setProducts(res.records)
      setTotal(res.total)
      setSearchMode('mysql')
    }
    setLoading(false)
  }

  useEffect(() => { doSearch('', {}) }, [])

  const buy = async (p: Product) => {
    if (!user) return
    setBuying(true)
    try {
      const order = await createOrder(user.id, [{ productId: p.id, quantity: 1 }])
      const paid = await payOrder(order.id).then(() => true).catch(() => false)
      message.success(`下单成功，订单号 ${order.orderNo}（${paid ? '已模拟支付' : '待支付'}）`)
    } catch (e: any) {
      message.error(e.message || '下单失败')
    }
    setBuying(false)
  }

  const fav = async (p: Product) => {
    if (!user) return
    await addFavorite(user.id, p.id)
    message.success('已收藏')
  }

  const tryOn = (p: Product) => {
    const msg = `用商城在售的「${p.name}」帮我搭一套，并生成换装效果图`
    sessionStorage.setItem('cy_preset_message', msg)
    window.location.pathname = '/chat'
  }

  const loadOrders = async () => {
    if (!user) return
    setOrders(await listOrders(user.id))
    setOrdersOpen(true)
  }

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="搜索商品，如：白色衬衫" allowClear style={{ width: 240 }}
          enterButton={<SearchOutlined />} onSearch={(v) => doSearch(v)}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select allowClear placeholder="类目" style={{ width: 110 }}
          onChange={(v) => setFilters((f) => ({ ...f, category: v }))} options={CATEGORY_OPTIONS} />
        <Select allowClear placeholder="颜色" style={{ width: 100 }}
          onChange={(v) => setFilters((f) => ({ ...f, color: v }))} options={COLOR_OPTIONS.map((c) => ({ value: c, label: c }))} />
        <Select allowClear placeholder="季节" style={{ width: 100 }}
          onChange={(v) => setFilters((f) => ({ ...f, season: v }))} options={SEASON_OPTIONS.map((c) => ({ value: c, label: c }))} />
        <Select allowClear placeholder="风格" style={{ width: 100 }}
          onChange={(v) => setFilters((f) => ({ ...f, style: v }))} options={STYLE_OPTIONS.map((c) => ({ value: c, label: c }))} />
        <InputNumber
          placeholder="最高价" min={0} style={{ width: 110 }}
          onChange={(v) => setFilters((f) => ({ ...f, maxPrice: v ?? undefined }))}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={() => doSearch()}>搜索</Button>
        <Button onClick={loadOrders}>我的订单</Button>
      </Space>
      <div style={{ marginBottom: 8, color: '#999', fontSize: 12 }}>
        检索引擎：<Tag color={searchMode === 'es' ? 'green' : 'orange'}>{searchMode === 'es' ? 'Elasticsearch 混合检索' : 'MySQL 兜底'}</Tag>
        共 {total} 件商品
      </div>
      <Spin spinning={loading}>
        {products.length === 0 ? (
          <Empty description="暂无商品" />
        ) : (
          <Row gutter={[12, 12]}>
            {products.map((p) => (
              <Col key={p.id} xs={12} sm={8} md={6} lg={4}>
                <Card
                  hoverable
                  cover={
                    <img alt={p.name} src={p.imageUrl} style={{ height: 180, objectFit: 'cover' }}
                      onClick={() => setDetail(p)}
                      onError={(e) => { (e.target as HTMLImageElement).src = '/seed-images/product_1.svg' }} />
                  }
                >
                  <Card.Meta
                    title={<Tooltip title={p.name}><span style={{ fontSize: 13 }}>{p.name}</span></Tooltip>}
                    description={
                      <div>
                        <span style={{ color: '#f5222d', fontWeight: 600 }}>¥{p.price}</span>
                        <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>库存 {p.stock}</span>
                        <div style={{ marginTop: 4 }}>
                          {[p.category, p.color, p.season, p.style].filter(Boolean).map((t) => (
                            <Tag key={t} style={{ fontSize: 11 }}>{t}</Tag>
                          ))}
                        </div>
                      </div>
                    }
                  />
                  <Space style={{ marginTop: 8 }} size={4}>
                    <Button size="small" onClick={() => setDetail(p)}>详情</Button>
                    <Button size="small" icon={<StarFilled />} onClick={() => fav(p)} />
                    <Button size="small" icon={<ExperimentOutlined />} onClick={() => tryOn(p)}>试穿</Button>
                    <Button size="small" type="primary" icon={<ShoppingCartOutlined />} loading={buying} onClick={() => buy(p)}>购买</Button>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      <Drawer title="商品详情" open={!!detail} onClose={() => setDetail(null)} width={420}>
        {detail && (
          <div>
            <img alt={detail.name} src={detail.imageUrl} style={{ width: '100%', borderRadius: 8 }} />
            <h3 style={{ marginTop: 12 }}>{detail.name}</h3>
            <Space size={4} wrap>
              <Tag color="blue">{CATEGORY_OPTIONS.find((c) => c.value === detail.category)?.label}</Tag>
              {[detail.color, detail.season, detail.style].filter(Boolean).map((t) => <Tag key={t}>{t}</Tag>)}
              {parseTags(detail.tags).map((t) => <Tag key={t} color="purple">{t}</Tag>)}
            </Space>
            <p style={{ color: '#666' }}>{detail.detail}</p>
            <p>
              <span style={{ color: '#f5222d', fontSize: 24, fontWeight: 700 }}>¥{detail.price}</span>
              <span style={{ color: '#999', marginLeft: 12 }}>库存 {detail.stock} · 销量 {detail.sales}</span>
            </p>
            <Space>
              <Button type="primary" icon={<ShoppingCartOutlined />} loading={buying} onClick={() => buy(detail)}>立即购买</Button>
              <Button icon={<StarFilled />} onClick={() => fav(detail)}>收藏</Button>
              <Button icon={<ExperimentOutlined />} onClick={() => tryOn(detail)}>AI 换装试穿</Button>
            </Space>
          </div>
        )}
      </Drawer>

      <Drawer title="我的订单" open={ordersOpen} onClose={() => setOrdersOpen(false)} width={560}>
        <Table
          rowKey="id" dataSource={orders} pagination={false} size="small"
          columns={[
            { title: '订单号', dataIndex: 'orderNo' },
            { title: '金额', dataIndex: 'totalAmount', render: (v) => `¥${v}` },
            { title: '状态', dataIndex: 'status', render: (s) => <Tag color={ORDER_STATUS[s]?.color}>{ORDER_STATUS[s]?.text ?? s}</Tag> },
            { title: '物流', dataIndex: 'logisticsNo', render: (v) => v || '-' },
            {
              title: '操作', render: (_, r: Order) =>
                r.status === 'pending' ? (
                  <Button size="small" onClick={async () => { await payOrder(r.id); loadOrders(); message.success('已模拟支付') }}>模拟支付</Button>
                ) : null,
            },
          ]}
        />
      </Drawer>
    </div>
  )
}
