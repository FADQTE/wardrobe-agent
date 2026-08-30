import { useState } from 'react'
import { Button, Card, Form, Input, Segmented, Space, Typography, message } from 'antd'
import { LockOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import { LoginResult, login, register, saveAccessToken } from '../api'

interface Props {
  onAuthenticated: (result: LoginResult) => void
}

export default function LoginPage({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const submit = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const result = mode === 'login'
        ? await login(values.username, values.password)
        : await register(values.username, values.password, values.nickname)
      saveAccessToken(result.token)
      onAuthenticated(result)
      message.success(mode === 'login' ? '欢迎回来' : '账号创建成功')
    } catch (error: any) {
      message.error(error?.message || '操作失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-intro">
        <div className="login-logo"><RobotOutlined /></div>
        <Typography.Title level={1}>让每次穿搭，从一次对话开始</Typography.Title>
        <Typography.Paragraph>
          登录潮引，保存你的衣橱、偏好与每一段搭配灵感。历史会话会自动同步，随时接着聊。
        </Typography.Paragraph>
        <div className="login-feature-grid">
          <div><strong>智能搭配</strong><span>衣橱与商城混合推荐</span></div>
          <div><strong>会话同步</strong><span>多段灵感独立管理</span></div>
          <div><strong>专属记忆</strong><span>偏好只与你的账号关联</span></div>
        </div>
      </div>
      <Card className="login-card" bordered={false}>
        <Space direction="vertical" size={6} style={{ width: '100%', marginBottom: 24 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {mode === 'login' ? '登录潮引' : '创建账号'}
          </Typography.Title>
          <Typography.Text type="secondary">
            {mode === 'login' ? '继续你的专属穿搭旅程' : '建立属于你的智能衣橱'}
          </Typography.Text>
        </Space>
        <Segmented
          block value={mode}
          options={[{ label: '登录', value: 'login' }, { label: '注册', value: 'register' }]}
          onChange={(value) => { setMode(value as 'login' | 'register'); form.resetFields() }}
          style={{ marginBottom: 20 }}
        />
        <Form form={form} layout="vertical" onFinish={submit} initialValues={{ username: 'demo', password: 'demo123' }}>
          {mode === 'register' && (
            <Form.Item name="nickname" label="昵称" rules={[{ max: 32, message: '昵称最多 32 个字符' }]}>
              <Input size="large" placeholder="怎么称呼你（选填）" />
            </Form.Item>
          )}
          <Form.Item name="username" label="用户名" rules={[
            { required: true, message: '请输入用户名' },
            ...(mode === 'register' ? [{ pattern: /^[A-Za-z0-9_]{3,32}$/, message: '3-32 位字母、数字或下划线' }] : []),
          ]}>
            <Input size="large" prefix={<UserOutlined />} autoComplete="username" placeholder="请输入用户名" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少 6 位' },
          ]}>
            <Input.Password size="large" prefix={<LockOutlined />} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder="请输入密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
            {mode === 'login' ? '登录' : '注册并登录'}
          </Button>
        </Form>
        {mode === 'login' && <Typography.Text type="secondary" className="demo-account">演示账号：demo / demo123</Typography.Text>}
      </Card>
    </div>
  )
}
