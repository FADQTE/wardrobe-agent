import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ConfigProvider, Layout, Menu, Avatar, message } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import {
  AppstoreOutlined,
  DashboardOutlined,
  HddOutlined,
  RobotOutlined,
  ScheduleOutlined,
  UserOutlined,
} from '@ant-design/icons'
import WardrobePage from './pages/WardrobePage'
import MallPage from './pages/MallPage'
import ChatPage from './pages/ChatPage'
import RulesPage from './pages/RulesPage'
import ObservePage from './pages/ObservePage'
import { createContext, useContext, useEffect, useState } from 'react'
import { login, User } from './api'

const { Sider, Header, Content } = Layout

export const UserContext = createContext<{ user: User | null }>({ user: null })
export const useUser = () => useContext(UserContext)

const menuItems = [
  { key: '/chat', icon: <RobotOutlined />, label: 'AI 穿搭客服' },
  { key: '/wardrobe', icon: <HddOutlined />, label: '我的衣橱' },
  { key: '/mall', icon: <AppstoreOutlined />, label: '服饰商城' },
  { key: '/rules', icon: <ScheduleOutlined />, label: '规则管理' },
  { key: '/observe', icon: <DashboardOutlined />, label: '可观测' },
]

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const location = useLocation()
  const navigate = useNavigate()
  // 当前菜单项 = 当前 URL 路径（刷新/前进后退/直接输入 URL 均保持一致）
  const current = location.pathname

  useEffect(() => {
    login('demo', 'demo123')
      .then((u) => setUser(u))
      .catch(() => message.warning('自动登录失败，请检查后端服务'))
  }, [])

  return (
    <ConfigProvider locale={zhCN}>
      <UserContext.Provider value={{ user }}>
        <Layout style={{ minHeight: '100vh' }}>
          <Sider theme="light" width={176}>
            <div style={{ padding: '14px 16px', fontSize: 16, fontWeight: 700, color: '#1677ff' }}>
              潮引衣橱商城
            </div>
            <Menu
              mode="inline"
              selectedKeys={[current]}
              items={menuItems}
              onClick={({ key }) => navigate(key)}
            />
          </Sider>
          <Layout>
            <Header
              style={{
                background: '#fff',
                padding: '0 24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                borderBottom: '1px solid #f0f0f0',
              }}
            >
              <span style={{ fontSize: 15, fontWeight: 600 }}>
                {menuItems.find((m) => m.key === current)?.label ?? '潮引智能衣橱商城'}
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#666' }}>
                <Avatar size="small" icon={<UserOutlined />} />
                {user?.nickname ?? '未登录'}（演示账号 demo）
              </span>
            </Header>
            <Content style={{ padding: 16, overflow: 'auto' }}>
              <Routes>
                <Route path="/" element={<Navigate to="/chat" replace />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/wardrobe" element={<WardrobePage />} />
                <Route path="/mall" element={<MallPage />} />
                <Route path="/rules" element={<RulesPage />} />
                <Route path="/observe" element={<ObservePage />} />
              </Routes>
            </Content>
          </Layout>
        </Layout>
      </UserContext.Provider>
    </ConfigProvider>
  )
}
