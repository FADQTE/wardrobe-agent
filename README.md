一个包含用户系统、会话管理、个人衣物管理、服装商城和穿搭助手的项目。

## 功能

- 用户注册、登录、退出和登录状态恢复。
- Bearer Token 鉴权，密码使用 BCrypt 保存。
- 新建、搜索、切换、重命名和删除会话。
- 聊天消息持久化，并按用户和会话隔离。
- 衣橱单品的新增、编辑、查询和删除。
- 商品搜索、收藏、购物车、订单、物流和售后申请。
- 穿搭意图识别、规则检索、工具调用和流式回复。
- WebSocket 实时推送，连接不可用时自动使用 SSE。

## 技术栈

| 模块 | 技术 |
|---|---|
| 前端 | React、TypeScript、Vite、Ant Design |
| Java 服务 | Spring Boot、MyBatis-Plus、Netty、Spring AI MCP |
| Agent 服务 | FastAPI、LangGraph、LangChain |
| 数据存储 | MySQL、Elasticsearch |

## 项目结构

```text
.
├─ frontend/           # 前端页面
├─ backend-java/       # 用户、会话和业务接口
├─ agent-python/       # 对话编排与检索服务
├─ scripts/            # 初始化脚本
├─ docker-compose.yml  # MySQL、Elasticsearch 和可选 Ollama
└─ start.ps1           # Windows 启动脚本
```

## 快速启动

准备以下环境：

- Docker Desktop
- JDK 17
- Maven
- Node.js 与 pnpm
- uv

在项目根目录运行：

```powershell
.\start.ps1
```

脚本会启动 MySQL、Elasticsearch、Java 服务、Agent 服务和前端。已有数据库不会被清空。

首次初始化会创建账号：

```text
用户名：user
密码：user123
```

也可以在登录页直接注册新账号。已有数据库继续使用原有账号。

访问地址：

- 前端：http://localhost:16548
- Java 服务：http://localhost:16545
- Agent 服务：http://localhost:16546
- WebSocket：ws://localhost:16547/ws/chat
- Redis（会话缓存）：localhost:16549
- RocketMQ（namesrv / broker）：localhost:16550 / 16551

## 高并发与缓存

C 端并发的两条主线，均不影响既有接口契约：

- **RocketMQ lite topic 削峰**：WS 聊天轮次不再由 4 线程池同步转发，而是发送到固定主题
  `chat_turn_topic`（不做每会话独立 topic，避免 topic 爆炸），发送时以 `sessionId` 为
  shardingKey 哈希选队列——同一会话严格 FIFO，不同会话分散到 8 个队列并行；消费端
  （ORDERLY）按队列数限速驱动 Agent，高峰期请求排队而不是把 LLM 打挂。入队即回推
  「排队处理中」状态事件；MQ 关闭（`CHAT_MQ_ENABLED=false`）或发送失败自动降级为
  线程池同步转发，SSE 直连路径保持不变。
- **Redis 会话缓存**：会话历史缓存于 `chat:hist:{userId}:{sessionId}`，用户读历史与
  Agent 装载记忆共用。隐私三原则：① 键绑定服务端身份（userId 只来自 token/会话行，
  绝不接受客户端自报）；② 归属校验前置（`requireOwned` 先于任何缓存读取，缓存只是
  加速层不是授权层）；③ 写即失效 + 短 TTL（append/delete 立刻 evict 本人键，默认
  TTL 10 分钟）。Redis 不可用时全量降级回源 DB。

## 手动启动

基础服务：

```powershell
docker compose up -d
```

Java 服务：

```powershell
cd backend-java
mvn -s ..\.mvn\settings.xml spring-boot:run
```

Agent 服务：

```powershell
cd agent-python
uv sync
Copy-Item .env.example .env
uv run uvicorn app.main:app --port 16546
```

前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

## 配置

Agent 配置文件为 `agent-python/.env`。常用配置如下：

```ini
MOCK_AGENT=true
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
EMBEDDING_MODE=none
TRYON_MODE=mock
APP_INTERNAL_API_KEY=local-internal-key
```

`APP_INTERNAL_API_KEY` 必须在 Java 服务和 Agent 服务中配置为相同值。非本地环境应替换默认值，并通过 HTTPS 对外提供服务。

## 测试

前端构建：

```powershell
cd frontend
npm run build
```

Java 测试：

```powershell
cd backend-java
mvn -s ..\.mvn\settings.xml test
```

Python 测试：

```powershell
cd agent-python
uv run --with pytest pytest -q
```

Docker Compose 配置检查：

```powershell
docker compose config --quiet
```

## 数据与安全

- 原始登录令牌只保存在浏览器，服务端仅保存 SHA-256 摘要。
- 业务接口根据登录令牌识别用户，不接受客户端指定的用户身份。
- 会话、消息、衣橱和订单数据均按用户隔离。
- Java 与 Agent 之间的内部接口使用独立密钥鉴权。
- 生产环境需要自行配置数据库密码、内部接口密钥、模型密钥和 HTTPS。
