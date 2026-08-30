// 前端 API 封装：/api → Java 8080，/agent → Python 8000（vite 代理）
export const AUTH_TOKEN_KEY = 'app_auth_token'
export const getAccessToken = () => localStorage.getItem(AUTH_TOKEN_KEY) || ''
export const saveAccessToken = (token: string) => localStorage.setItem(AUTH_TOKEN_KEY, token)
export const clearAccessToken = () => localStorage.removeItem(AUTH_TOKEN_KEY)

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken()
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  })
  const body = await res.json().catch(() => null)
  if (!res.ok || body?.code !== 0) {
    const code = body?.code ?? res.status
    if (code === 401) {
      clearAccessToken()
      window.dispatchEvent(new Event('app-auth-expired'))
    }
    throw new Error(body?.msg || `HTTP ${res.status}`)
  }
  return body.data as T
}

export interface User {
  id: number
  username: string
  nickname: string
  avatar?: string
}

export interface WardrobeItem {
  id: number
  userId: number
  name: string
  imageUrl?: string
  category: string
  color?: string
  season?: string
  style?: string
  tags?: string
  note?: string
  source?: string
  createdAt?: string
}

export interface Product {
  id: number
  name: string
  imageUrl?: string
  category: string
  color?: string
  season?: string
  style?: string
  tags?: string
  price: number
  stock: number
  sales?: number
  detail?: string
}

export interface Rule {
  id: number
  type: 'activity' | 'outfit'
  title: string
  content: string
  tags?: string
  version: number
  effectiveFrom?: string
  effectiveTo?: string
  publishStatus: 'draft' | 'published' | 'offline'
  source?: string
  updatedAt?: string
}

export interface Order {
  id: number
  orderNo: string
  userId: number
  totalAmount: number
  status: string
  logisticsNo?: string
  receiverName?: string
  receiverPhone?: string
  receiverAddress?: string
  createdAt?: string
}

export interface LoginResult {
  token: string
  user: User
  expiresAt: string
}

export interface ChatSession {
  id: string
  userId: number
  title: string
  state?: string
  createdAt?: string
  updatedAt?: string
}

export interface OrderItem {
  id: number
  orderId: number
  productId: number
  productName: string
  price: number
  quantity: number
}

export interface AfterSale {
  id: number
  requestNo: string
  orderId: number
  userId: number
  type: 'refund' | 'return_refund' | 'exchange'
  status: 'pending' | 'approved' | 'rejected' | 'completed'
  reason?: string
  amount: number
  createdAt?: string
}

export interface OrderDetail {
  order: Order
  items: OrderItem[]
  afterSale?: AfterSale
}

export interface PersistedChatMessage {
  id: number
  sessionId: string
  role: 'user' | 'assistant'
  content: string
  meta?: string
  createdAt?: string
}

// ---- 业务 API ----
export const login = (username: string, password: string) =>
  api<LoginResult>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })

export const register = (username: string, password: string, nickname?: string) =>
  api<LoginResult>('/api/auth/register', {
    method: 'POST', body: JSON.stringify({ username, password, nickname }),
  })

export const getCurrentUser = () => api<User>('/api/auth/me')
export const logout = () => api<void>('/api/auth/logout', { method: 'POST' })

export const listWardrobe = (userId: number) => api<WardrobeItem[]>(`/api/wardrobe?userId=${userId}`)

export const addWardrobeItem = (item: Partial<WardrobeItem>) =>
  api<WardrobeItem>('/api/wardrobe', { method: 'POST', body: JSON.stringify(item) })

export const updateWardrobeItem = (id: number, item: Partial<WardrobeItem>) =>
  api<WardrobeItem>(`/api/wardrobe/${id}`, { method: 'PUT', body: JSON.stringify(item) })

export const deleteWardrobeItem = (id: number) =>
  api<void>(`/api/wardrobe/${id}`, { method: 'DELETE' })

export const searchProducts = (params: Record<string, string | number | undefined>) => {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && qs.set(k, String(v)))
  return api<any>(`/api/products?${qs.toString()}`)
}

// ES 混合检索（agent-python），失败时由调用方降级到 MySQL
export const esSearchProducts = (params: Record<string, string | number | undefined>) => {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && qs.set(k, String(v)))
  return fetch(`/agent/api/products/search?${qs.toString()}`).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  })
}

export const getProduct = (id: number) => api<Product>(`/api/products/${id}`)

export const listRules = (type?: string, status?: string) => {
  const qs = new URLSearchParams()
  if (type) qs.set('type', type)
  if (status) qs.set('status', status)
  return api<Rule[]>(`/api/rules?${qs.toString()}`)
}

export const saveRule = (rule: Partial<Rule>, id?: number) =>
  api<Rule>(id ? `/api/rules/${id}` : '/api/rules', {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify(rule),
  })

export const publishRule = (id: number) => api<Rule>(`/api/rules/${id}/publish`, { method: 'POST' })
export const offlineRule = (id: number) => api<Rule>(`/api/rules/${id}/offline`, { method: 'POST' })

export const addFavorite = (userId: number, productId: number) =>
  api('/api/favorites', { method: 'POST', body: JSON.stringify({ userId, productId }) })

export const listFavorites = (userId: number) => api<Product[]>(`/api/favorites?userId=${userId}`)

export const removeFavorite = (userId: number, productId: number) =>
  api<void>(`/api/favorites/${productId}?userId=${userId}`, { method: 'DELETE' })

export const createOrder = (userId: number, items: { productId: number; quantity: number }[]) =>
  api<Order>('/api/orders', {
    method: 'POST',
    body: JSON.stringify({
      userId,
      items,
      receiverName: '小潮',
      receiverPhone: '13800000000',
      receiverAddress: '上海市徐汇区漕河泾开发区',
    }),
  })

export const payOrder = (id: number, userId: number) =>
  api<void>(`/api/orders/${id}/pay?userId=${userId}`, { method: 'POST' })
export const listOrders = (userId: number) => api<Order[]>(`/api/orders?userId=${userId}`)

export const getOrderDetail = (id: number, userId: number) =>
  api<OrderDetail>(`/api/orders/${id}?userId=${userId}`)

export const cancelOrder = (id: number, userId: number) =>
  api<void>(`/api/orders/${id}/cancel?userId=${userId}`, { method: 'POST' })

export const applyAfterSale = (userId: number, orderId: number, type = 'refund', reason = '') =>
  api<AfterSale>('/api/after-sales', {
    method: 'POST',
    body: JSON.stringify({ userId, orderId, type, reason }),
  })

export const getChatMessages = (sessionId: string) =>
  api<PersistedChatMessage[]>(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`)

export const listChatSessions = () => api<ChatSession[]>('/api/chat/sessions')
export const createChatSession = () => api<ChatSession>('/api/chat/sessions', { method: 'POST' })
export const renameChatSession = (sessionId: string, title: string) =>
  api<ChatSession>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH', body: JSON.stringify({ title }),
  })
export const deleteChatSession = (sessionId: string) =>
  api<void>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })

export const uploadFile = async (file: File): Promise<string> => {
  const fd = new FormData()
  fd.append('file', file)
  const token = getAccessToken()
  const res = await fetch('/api/upload', {
    method: 'POST', body: fd,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  const body = await res.json()
  if (body.code !== 0) throw new Error(body.msg || '上传失败')
  return body.data.url
}

// ---- 生产级证据链 ----
export interface TraceEvent {
  id: number
  sessionId: string
  eventType: string
  category: string
  payload: string
  createdAt: string
}

export const getTrace = (sessionId: string, limit = 200) =>
  api<TraceEvent[]>(`/api/internal/trace/${sessionId}?limit=${limit}`)

export interface TraceSession {
  sessionId: string
  eventCount: number
  firstAt: string
  lastAt: string
}

export const getTraceSessions = () => api<TraceSession[]>('/api/internal/trace/sessions')

export const runEval = () =>
  fetch('/agent/eval/run', { method: 'POST' }).then((r) => r.json())

export const getAgentHealth = () => fetch('/agent/health').then((r) => r.json())
