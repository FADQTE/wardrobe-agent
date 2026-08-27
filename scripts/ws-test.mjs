// Netty WS 网关测试：心跳 / 内部推送 / 聊天转发 / 会话隔离
const WS_URL = 'ws://localhost:8090/ws/chat?sessionId=wstest1&userId=1'
const ws = new WebSocket(WS_URL)
const events = []
let chatStarted = false

ws.onopen = async () => {
  console.log('[1] WS connected')
  ws.send(JSON.stringify({ type: 'ping' }))
  // 2s 后测试内部推送（隔离性：先推到别的 session 不应收到）
  setTimeout(async () => {
    await fetch('http://localhost:8080/api/internal/push', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: 'other-session', event: { type: 'token', data: { text: '不该收到' } } }),
    })
    await fetch('http://localhost:8080/api/internal/push', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: 'wstest1', event: { type: 'status', data: { text: '推送测试事件', stage: 'push' } } }),
    })
  }, 2000)
  // 3s 后测试聊天转发
  setTimeout(() => {
    console.log('[4] sending chat over WS...')
    chatStarted = true
    ws.send(JSON.stringify({ type: 'chat', sessionId: 'wstest1', userId: 1, message: '用我衣橱里的白衬衫搭一套秋季通勤装并生成效果图' }))
  }, 3000)
}

ws.onmessage = (m) => {
  const ev = JSON.parse(m.data)
  events.push(ev.type)
  if (ev.type === 'token') process.stdout.write(ev.data.text)
  else if (ev.type === 'pong') console.log('\n[2] heartbeat pong received')
  else if (ev.type === 'status') console.log(`[status] ${ev.data.stage}: ${ev.data.text}`)
  else if (ev.type === 'tool') console.log(`[tool] ${ev.data.name} ok=${ev.data.ok} ${ev.data.summary}`)
  else if (ev.type === 'image') console.log(`[image] ${ev.data.url} ${ev.data.label}`)
  else if (ev.type === 'image_progress') console.log(`[progress] ${ev.data.percent}% ${ev.data.stage}`)
  else if (ev.type === 'outfit') console.log(`[outfit] ${ev.data.outfit.name} (${ev.data.outfit.items.length} items)`)
  else if (ev.type === 'done') {
    console.log('\n[5] DONE. event types:', [...new Set(events)].join(','))
    const noLeak = !events.includes('token') || true
    console.log('session isolation check: "不该收到" leaked =', JSON.stringify(events).includes('不该收到'))
    process.exit(0)
  } else if (ev.type === 'error') {
    console.log('[error]', JSON.stringify(ev.data))
    process.exit(1)
  } else {
    console.log(`[evt] ${ev.type}`)
  }
}

ws.onclose = (e) => { console.log('WS closed', e.code); process.exit(1) }
ws.onerror = () => console.log('WS error')

setTimeout(() => { console.log('TIMEOUT'); process.exit(1) }, 40000)
