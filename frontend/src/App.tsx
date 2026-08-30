import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ConfigProvider, Layout, Menu, Avatar, Dropdown, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import {
  AppstoreOutlined,
  DashboardOutlined,
  HddOutlined,
  RobotOutlined,
  ScheduleOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import WardrobePage from './pages/WardrobePage'
import MallPage from './pages/MallPage'
import ChatPage from './pages/ChatPage'
import RulesPage from './pages/RulesPage'
import ObservePage from './pages/ObservePage'
import { createContext, useContext, useEffect, useState } from 'react'
import { clearAccessToken, getAccessToken, getCurrentUser, LoginResult, logout, User } from './api'
import LoginPage from './pages/LoginPage'

const { Sider, Header, Content } = Layout

export const UserContext = createContext<{ user: User | null; signOut: () => void }>({ user: null, signOut: () => {} })
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
  const [authReady, setAuthReady] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  // 当前菜单项 = 当前 URL 路径（刷新/前进后退/直接输入 URL 均保持一致）
  const current = location.pathname.startsWith('/chat') ? '/chat' : location.pathname

  useEffect(() => {
    let active = true
    const restore = async () => {
      if (!getAccessToken()) {
        setAuthReady(true)
        return
      }
      try {
        const restored = await getCurrentUser()
        if (active) setUser(restored)
      } catch {
        clearAccessToken()
      } finally {
        if (active) setAuthReady(true)
      }
    }
    const expired = () => setUser(null)
    window.addEventListener('app-auth-expired', expired)
    void restore()
    return () => {
      active = false
      window.removeEventListener('app-auth-expired', expired)
    }
  }, [])

  const handleAuthenticated = (result: LoginResult) => {
    setUser(result.user)
    setAuthReady(true)
  }

  const signOut = () => {
    void logout().catch(() => undefined).finally(() => {
      clearAccessToken()
      setUser(null)
      navigate('/chat', { replace: true })
    })
  }

  if (!authReady) {
    return <div className="app-loading"><Spin size="large" tip="正在恢复登录状态…" /></div>
  }

  if (!user) {
    return (
      <ConfigProvider locale={zhCN}>
        <LoginPage onAuthenticated={handleAuthenticated} />
      </ConfigProvider>
    )
  }

  return (
    <ConfigProvider locale={zhCN}>
      <UserContext.Provider value={{ user, signOut }}>
        <Layout style={{ minHeight: '100vh' }}>
          <Sider theme="light" width={176}>
            <div style={{ padding: '14px 16px', fontSize: 16, fontWeight: 700, color: '#1677ff' }}>
              智能衣橱
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
                {menuItems.find((m) => m.key === current)?.label ?? '智能衣橱'}
              </span>
              <Dropdown
                trigger={['click']}
                menu={{ items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: signOut }] }}
              >
                <button className="account-button" type="button">
                  <Avatar size="small" src={user.avatar} icon={<UserOutlined />} />
                  <span>{user.nickname || user.username}</span>
                  <span className="account-username">@{user.username}</span>
                </button>
              </Dropdown>
            </Header>
            <Content style={{ padding: 16, overflow: 'auto' }}>
              <Routes>
                <Route path="/" element={<Navigate to="/chat" replace />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/chat/:sessionId" element={<ChatPage />} />
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
