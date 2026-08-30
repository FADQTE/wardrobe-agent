import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge, Button, Card, Col, Descriptions, Divider, Drawer, Empty, Input, InputNumber,
  List, message, Modal, Pagination, Row, Select, Space, Spin, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, ExperimentOutlined, EyeOutlined, HeartOutlined, InboxOutlined,
  SearchOutlined, ShoppingCartOutlined, StarFilled,
} from '@ant-design/icons'
import { useUser } from '../App'
import {
  AfterSale, Order, OrderDetail, Product, addFavorite, applyAfterSale, cancelOrder,
  createOrder, esSearchProducts, getOrderDetail, listFavorites, listOrders, payOrder,
  removeFavorite, searchProducts,
} from '../api'

const CATEGORY_OPTIONS = [
  { value: 'top', label: '上装' }, { value: 'bottom', label: '下装' }, { value: 'outerwear', label: '外套' },
  { value: 'dress', label: '连衣裙' }, { value: 'shoes', label: '鞋履' }, { value: 'accessory', label: '配饰' },
]
const COLOR_OPTIONS = ['白色', '黑色', '浅蓝', '深蓝', '藏青', '灰色', '卡其', '米色', '粉色', '碎花', '墨绿', '酒红', '棕色']
const SEASON_OPTIONS = ['春', '夏', '秋', '冬', '春秋', '秋冬', '春夏', '四季']
const STYLE_OPTIONS = ['通勤', '休闲', '运动', '约会', '正式']
const PAGE_SIZE = 24

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

const AFTER_SALE_STATUS: Record<string, { text: string; color: string }> = {
  pending: { text: '待人工审核', color: 'processing' },
  approved: { text: '审核通过', color: 'success' },
  rejected: { text: '审核拒绝', color: 'error' },
  completed: { text: '售后完成', color: 'default' },
}

interface CartLine { product: Product; quantity: number }

export default function MallPage() {
  const { user } = useUser()
  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [searchMode, setSearchMode] = useState<'es' | 'mysql'>('es')
  const [keyword, setKeyword] = useState('')
  const [filters, setFilters] = useState<Record<string, string | number | undefined>>({})
  const [detail, setDetail] = useState<Product | null>(null)
  const [ordersOpen, setOrdersOpen] = useState(false)
  const [orders, setOrders] = useState<Order[]>([])
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null)
  const [favoritesOpen, setFavoritesOpen] = useState(false)
  const [favorites, setFavorites] = useState<Product[]>([])
  const [cartOpen, setCartOpen] = useState(false)
  const [cart, setCart] = useState<CartLine[]>([])
  const [submitting, setSubmitting] = useState(false)
  const cartLoaded = useRef(false)

  const cartKey = `cy_cart_${user?.id ?? 'guest'}`
  const cartCount = cart.reduce((sum, line) => sum + line.quantity, 0)
  const cartTotal = useMemo(
    () => cart.reduce((sum, line) => sum + Number(line.product.price) * line.quantity, 0),
    [cart],
  )

  const doSearch = async (
    nextPage = page,
    nextKeyword = keyword,
    nextFilters = filters,
  ) => {
    setLoading(true)
    const params = { keyword: nextKeyword, ...nextFilters, page: nextPage, size: PAGE_SIZE }
    try {
      const res = await esSearchProducts(params)
      setProducts(res.data.products)
      setTotal(res.data.total)
      setSearchMode('es')
    } catch {
      const res = await searchProducts(params)
      setProducts(res.records)
      setTotal(res.total)
      setSearchMode('mysql')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void doSearch(1, '', {}) }, [])

  useEffect(() => {
    cartLoaded.current = false
    try {
      setCart(JSON.parse(localStorage.getItem(cartKey) || '[]'))
    } catch {
      setCart([])
    }
    cartLoaded.current = true
  }, [cartKey])

  useEffect(() => {
    if (cartLoaded.current) localStorage.setItem(cartKey, JSON.stringify(cart))
  }, [cart, cartKey])

  const searchNow = (value = keyword) => {
    setKeyword(value)
    setPage(1)
    void doSearch(1, value, filters)
  }

  const addCart = (product: Product, quantity = 1) => {
    if (product.stock < 1) {
      message.warning(`「${product.name}」暂时无货`)
      return
    }
    const safeQuantity = Math.max(1, Math.min(quantity, product.stock))
    setCart((current) => {
      const found = current.find((line) => line.product.id === product.id)
      if (found) {
        return current.map((line) => line.product.id === product.id
          ? { ...line, quantity: Math.min(line.quantity + safeQuantity, product.stock) }
          : line)
      }
      return [...current, { product, quantity: safeQuantity }]
    })
    message.success(`已将「${product.name}」加入购物车`)
  }

  const updateQuantity = (productId: number, quantity: number | null) => {
    if (!quantity || quantity < 1) {
      setCart((current) => current.filter((line) => line.product.id !== productId))
      return
    }
    setCart((current) => current.map((line) => line.product.id === productId
      ? { ...line, quantity: Math.min(quantity, line.product.stock || quantity) }
      : line))
  }

  const createPendingOrder = async (lines: CartLine[]) => {
    if (!user || !lines.length) return
    setSubmitting(true)
    try {
      const order = await createOrder(user.id, lines.map((line) => ({
        productId: line.product.id, quantity: line.quantity,
      })))
      const purchased = new Set(lines.map((line) => line.product.id))
      setCart((current) => current.filter((line) => !purchased.has(line.product.id)))
      setCartOpen(false)
      message.success(`订单 ${order.orderNo} 已创建，请在“我的订单”中确认支付`)
      await loadOrders()
    } catch (e: any) {
      message.error(e.message || '创建订单失败')
    } finally {
      setSubmitting(false)
    }
  }

  const fav = async (product: Product) => {
    if (!user) return
    try {
      await addFavorite(user.id, product.id)
      message.success('已收藏')
    } catch (e: any) {
      message.error(e.message || '收藏失败')
    }
  }

  const loadFavorites = async () => {
    if (!user) return
    setFavorites(await listFavorites(user.id))
    setFavoritesOpen(true)
  }

  const deleteFavorite = async (productId: number) => {
    if (!user) return
    await removeFavorite(user.id, productId)
    setFavorites((current) => current.filter((product) => product.id !== productId))
    message.success('已取消收藏')
  }

  const tryOn = (product: Product) => {
    const preset = `用商城在售的「${product.name}」帮我搭一套，并生成换装效果图`
    sessionStorage.setItem('cy_preset_message', preset)
    window.location.pathname = '/chat'
  }

  async function loadOrders() {
    if (!user) return
    setOrders(await listOrders(user.id))
    setOrdersOpen(true)
  }

  const viewOrder = async (order: Order) => {
    if (!user) return
    setOrderDetail(await getOrderDetail(order.id, user.id))
  }

  const confirmPay = (order: Order) => {
    if (!user) return
    Modal.confirm({
      title: `确认模拟支付 ¥${order.totalAmount}？`,
      content: '这是演示支付，不会产生真实资金扣款。',
      okText: '确认支付', cancelText: '暂不支付',
      onOk: async () => {
        await payOrder(order.id, user.id)
        message.success('模拟支付成功')
        await loadOrders()
        if (orderDetail?.order.id === order.id) await viewOrder(order)
      },
    })
  }

  const confirmCancel = (order: Order) => {
    if (!user) return
    Modal.confirm({
      title: `取消订单 ${order.orderNo}？`,
      content: '仅待支付订单可以取消，取消后库存会自动恢复。',
      okText: '确认取消', okButtonProps: { danger: true }, cancelText: '保留订单',
      onOk: async () => {
        await cancelOrder(order.id, user.id)
        message.success('订单已取消，库存已恢复')
        setOrderDetail(null)
        await loadOrders()
      },
    })
  }

  const confirmAfterSale = (order: Order) => {
    if (!user) return
    Modal.confirm({
      title: `为订单 ${order.orderNo} 申请退款？`,
      content: '提交后进入人工审核；系统不会在此步骤直接退款或承诺到账。',
      okText: '提交申请', cancelText: '暂不申请',
      onOk: async () => {
        const type = order.status === 'shipped' || order.status === 'done' ? 'return_refund' : 'refund'
        const result = await applyAfterSale(user.id, order.id, type)
        message.success(`售后单 ${result.requestNo} 已提交，等待人工审核`)
        await viewOrder(order)
      },
    })
  }

  const orderActions = (order: Order, hasAfterSale = false) => (
    <Space size={4} wrap>
      <Button size="small" icon={<EyeOutlined />} onClick={() => void viewOrder(order)}>详情</Button>
      {order.status === 'pending' && <Button size="small" type="primary" onClick={() => confirmPay(order)}>模拟支付</Button>}
      {order.status === 'pending' && <Button size="small" danger onClick={() => confirmCancel(order)}>取消</Button>}
      {!hasAfterSale && ['paid', 'shipped', 'done'].includes(order.status) && (
        <Button size="small" onClick={() => confirmAfterSale(order)}>申请退款</Button>
      )}
    </Space>
  )

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索商品，如：白色衬衫" allowClear style={{ width: 260 }}
            enterButton={<SearchOutlined />} value={keyword}
            onSearch={searchNow} onChange={(event) => setKeyword(event.target.value)}
          />
          <Select allowClear placeholder="类目" style={{ width: 110 }}
            onChange={(value) => setFilters((current) => ({ ...current, category: value }))} options={CATEGORY_OPTIONS} />
          <Select allowClear placeholder="颜色" style={{ width: 100 }}
            onChange={(value) => setFilters((current) => ({ ...current, color: value }))}
            options={COLOR_OPTIONS.map((value) => ({ value, label: value }))} />
          <Select allowClear placeholder="季节" style={{ width: 100 }}
            onChange={(value) => setFilters((current) => ({ ...current, season: value }))}
            options={SEASON_OPTIONS.map((value) => ({ value, label: value }))} />
          <Select allowClear placeholder="风格" style={{ width: 100 }}
            onChange={(value) => setFilters((current) => ({ ...current, style: value }))}
            options={STYLE_OPTIONS.map((value) => ({ value, label: value }))} />
          <InputNumber placeholder="最高价" min={0} style={{ width: 110 }}
            onChange={(value) => setFilters((current) => ({ ...current, maxPrice: value ?? undefined }))} />
          <Button type="primary" icon={<SearchOutlined />} onClick={() => searchNow()}>搜索</Button>
          <Button icon={<StarFilled />} onClick={() => void loadFavorites()}>收藏夹</Button>
          <Button icon={<InboxOutlined />} onClick={() => void loadOrders()}>我的订单</Button>
          <Badge count={cartCount} size="small">
            <Button icon={<ShoppingCartOutlined />} onClick={() => setCartOpen(true)}>购物车</Button>
          </Badge>
        </Space>
      </Card>

      <div style={{ marginBottom: 8, color: '#777', fontSize: 12 }}>
        检索引擎：<Tag color={searchMode === 'es' ? 'green' : 'orange'}>
          {searchMode === 'es' ? 'Elasticsearch 混合检索' : 'MySQL 兜底'}
        </Tag>
        共 {total} 件商品
      </div>

      <Spin spinning={loading}>
        {products.length === 0 ? <Empty description="暂无商品" /> : (
          <Row gutter={[12, 12]}>
            {products.map((product) => (
              <Col key={product.id} xs={24} sm={12} md={8} lg={6} xl={4}>
                <Card hoverable cover={
                  <img alt={product.name} src={product.imageUrl} style={{ height: 200, objectFit: 'cover' }}
                    onClick={() => setDetail(product)}
                    onError={(event) => { (event.target as HTMLImageElement).src = '/seed-images/product_1.svg' }} />
                }>
                  <Card.Meta
                    title={<Tooltip title={product.name}><span style={{ fontSize: 13 }}>{product.name}</span></Tooltip>}
                    description={<>
                      <span style={{ color: '#f5222d', fontWeight: 600 }}>¥{product.price}</span>
                      <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>库存 {product.stock}</span>
                      <div style={{ marginTop: 4 }}>
                        {[product.color, product.season, product.style].filter(Boolean).map((tag) => (
                          <Tag key={tag} style={{ fontSize: 11 }}>{tag}</Tag>
                        ))}
                      </div>
                    </>}
                  />
                  <Space style={{ marginTop: 10 }} size={4} wrap>
                    <Button size="small" onClick={() => setDetail(product)}>详情</Button>
                    <Tooltip title="收藏"><Button size="small" icon={<HeartOutlined />} onClick={() => void fav(product)} /></Tooltip>
                    <Button size="small" icon={<ExperimentOutlined />} onClick={() => tryOn(product)}>试穿</Button>
                    <Button size="small" type="primary" icon={<ShoppingCartOutlined />} disabled={product.stock < 1}
                      onClick={() => addCart(product)}>加购</Button>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      {total > PAGE_SIZE && (
        <Pagination current={page} pageSize={PAGE_SIZE} total={total} showSizeChanger={false}
          style={{ marginTop: 20, textAlign: 'center' }}
          onChange={(next) => { setPage(next); void doSearch(next) }} />
      )}

      <Drawer title="商品详情" open={!!detail} onClose={() => setDetail(null)} width={440}>
        {detail && <>
          <img alt={detail.name} src={detail.imageUrl} style={{ width: '100%', borderRadius: 8 }} />
          <h3 style={{ marginTop: 12 }}>{detail.name}</h3>
          <Space size={4} wrap>
            <Tag color="blue">{CATEGORY_OPTIONS.find((item) => item.value === detail.category)?.label}</Tag>
            {[detail.color, detail.season, detail.style].filter(Boolean).map((tag) => <Tag key={tag}>{tag}</Tag>)}
            {parseTags(detail.tags).map((tag) => <Tag key={tag} color="purple">{tag}</Tag>)}
          </Space>
          <p style={{ color: '#666' }}>{detail.detail}</p>
          <p><Typography.Text type="secondary">支持 7 天无理由退换，具体以售后政策与商品状态为准。</Typography.Text></p>
          <p>
            <span style={{ color: '#f5222d', fontSize: 24, fontWeight: 700 }}>¥{detail.price}</span>
            <span style={{ color: '#999', marginLeft: 12 }}>库存 {detail.stock} · 销量 {detail.sales}</span>
          </p>
          <Space wrap>
            <Button type="primary" icon={<ShoppingCartOutlined />} disabled={detail.stock < 1}
              onClick={() => addCart(detail)}>加入购物车</Button>
            <Button onClick={() => void createPendingOrder([{ product: detail, quantity: 1 }])}
              disabled={detail.stock < 1} loading={submitting}>立即购买</Button>
            <Button icon={<StarFilled />} onClick={() => void fav(detail)}>收藏</Button>
            <Button icon={<ExperimentOutlined />} onClick={() => tryOn(detail)}>AI 换装</Button>
          </Space>
        </>}
      </Drawer>

      <Drawer title={`购物车（${cartCount} 件）`} open={cartOpen} onClose={() => setCartOpen(false)} width={520}>
        {cart.length === 0 ? <Empty description="购物车还是空的" /> : <>
          <List dataSource={cart} renderItem={(line) => (
            <List.Item actions={[
              <InputNumber key="qty" min={1} max={line.product.stock} value={line.quantity} size="small"
                onChange={(value) => updateQuantity(line.product.id, value)} />,
              <Button key="delete" type="text" danger icon={<DeleteOutlined />}
                onClick={() => updateQuantity(line.product.id, 0)} />,
            ]}>
              <List.Item.Meta avatar={<img src={line.product.imageUrl} style={{ width: 64, height: 80, objectFit: 'cover', borderRadius: 6 }} />}
                title={line.product.name}
                description={`¥${line.product.price} × ${line.quantity} = ¥${(Number(line.product.price) * line.quantity).toFixed(2)}`} />
            </List.Item>
          )} />
          <Divider />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography.Title level={4} style={{ margin: 0 }}>合计 ¥{cartTotal.toFixed(2)}</Typography.Title>
            <Button type="primary" size="large" loading={submitting} onClick={() => void createPendingOrder(cart)}>创建订单</Button>
          </div>
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            创建后为待支付订单；支付、取消和售后均需在“我的订单”中再次确认。
          </Typography.Paragraph>
        </>}
      </Drawer>

      <Drawer title="我的收藏" open={favoritesOpen} onClose={() => setFavoritesOpen(false)} width={720}>
        {favorites.length === 0 ? <Empty description="暂无收藏商品" /> : (
          <Row gutter={[12, 12]}>{favorites.map((product) => (
            <Col span={12} key={product.id}><Card size="small" cover={<img src={product.imageUrl} style={{ height: 160, objectFit: 'cover' }} />}>
              <Card.Meta title={product.name} description={`¥${product.price}`} />
              <Space style={{ marginTop: 10 }}>
                <Button size="small" type="primary" onClick={() => addCart(product)}>加入购物车</Button>
                <Button size="small" danger onClick={() => void deleteFavorite(product.id)}>取消收藏</Button>
              </Space>
            </Card></Col>
          ))}</Row>
        )}
      </Drawer>

      <Drawer title="我的订单" open={ordersOpen} onClose={() => setOrdersOpen(false)} width={900}>
        <Table rowKey="id" dataSource={orders} pagination={{ pageSize: 8 }} size="small" scroll={{ x: 760 }}
          columns={[
            { title: '订单号', dataIndex: 'orderNo', width: 190 },
            { title: '金额', dataIndex: 'totalAmount', width: 90, render: (value) => `¥${value}` },
            { title: '状态', dataIndex: 'status', width: 110, render: (status) => <Tag color={ORDER_STATUS[status]?.color}>{ORDER_STATUS[status]?.text ?? status}</Tag> },
            { title: '物流', dataIndex: 'logisticsNo', width: 140, render: (value) => value || '-' },
            { title: '操作', fixed: 'right', width: 250, render: (_, order: Order) => orderActions(order) },
          ]} />
      </Drawer>

      <Drawer title="订单详情" open={!!orderDetail} onClose={() => setOrderDetail(null)} width={700}>
        {orderDetail && <>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="订单号">{orderDetail.order.orderNo}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color={ORDER_STATUS[orderDetail.order.status]?.color}>{ORDER_STATUS[orderDetail.order.status]?.text}</Tag></Descriptions.Item>
            <Descriptions.Item label="金额">¥{orderDetail.order.totalAmount}</Descriptions.Item>
            <Descriptions.Item label="物流">{orderDetail.order.logisticsNo || '暂未生成'}</Descriptions.Item>
            <Descriptions.Item label="收货人">{orderDetail.order.receiverName || '-'}</Descriptions.Item>
            <Descriptions.Item label="联系电话">{orderDetail.order.receiverPhone || '-'}</Descriptions.Item>
            <Descriptions.Item label="收货地址" span={2}>{orderDetail.order.receiverAddress || '-'}</Descriptions.Item>
          </Descriptions>
          <Divider orientation="left">商品明细</Divider>
          <Table rowKey="id" dataSource={orderDetail.items} pagination={false} size="small"
            columns={[
              { title: '商品', dataIndex: 'productName' },
              { title: '单价', dataIndex: 'price', render: (value) => `¥${value}` },
              { title: '数量', dataIndex: 'quantity' },
              { title: '小计', render: (_, row) => `¥${(Number(row.price) * row.quantity).toFixed(2)}` },
            ]} />
          <Divider orientation="left">售后</Divider>
          {orderDetail.afterSale ? <AfterSaleView value={orderDetail.afterSale} /> : (
            <Typography.Paragraph type="secondary">暂无售后申请。提交退款后只会进入人工审核，不会自动退款。</Typography.Paragraph>
          )}
          <Space>{orderActions(orderDetail.order, !!orderDetail.afterSale)}</Space>
        </>}
      </Drawer>
    </div>
  )
}

function AfterSaleView({ value }: { value: AfterSale }) {
  const state = AFTER_SALE_STATUS[value.status] || { text: value.status, color: 'default' }
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Space wrap>
        <Typography.Text strong>售后单 {value.requestNo}</Typography.Text>
        <Tag color={state.color}>{state.text}</Tag>
        <Typography.Text>申请金额 ¥{value.amount}</Typography.Text>
      </Space>
      <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
        {value.reason || '用户申请售后'}
      </Typography.Paragraph>
    </Card>
  )
}
