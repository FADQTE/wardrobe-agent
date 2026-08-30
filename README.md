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
- Redis（会话缓存）：127.0.0.1:16549
- RocketMQ（namesrv / broker）：localhost:16550 / 16551

## AI 执行能力与退款安全边界

AI 不只能查，还能在安全边界内执行写操作：

- **退货/退款**：对话里说「我想退货订单 CY…」→ 创建售后申请（**产物验证**：创建后回查
  申请单必须真实存在，验证失败转人工，绝不谎报已退款）→ 自动审核引擎判定：
  符合规则（类型与订单状态匹配且金额 ≤ ¥1000）自动通过并**真正落地退款**——订单状态
  更新为「已退款」、库存恢复；不符合（类型不匹配/超额）转人工并记录可解释原因；
  待支付订单给明确指引（直接取消）而非笼统转人工。
- **购物车**：购物车落库（cart_item 表），商城页与 AI 共享同一份数据；对话「帮我把
  白色衬衫加入购物车」→ 检索定位 Top1 商品 → 加购 → **回查验证**后答复。
- **人工客服工作台**：侧栏「人工客服」→ 输入管理密钥（APP_INTERNAL_API_KEY）→
  处理转人工的售后单（通过/驳回，带原因）。售后状态 AI 随时可查，回复带审核判定说明。
- 安全原则：AI 永远不直接操作资金，只创建申请/触发规则审核；所有写操作先验证产物
  再答复；验证失败或执行异常一律转人工。

## 高并发与缓存

C 端并发的两条主线，均不影响既有接口契约：

- **RocketMQ lite topic 削峰**：WS 聊天轮次不再由 4 线程池同步转发，而是发送到固定主题
  `chat_turn_topic`（不做每会话独立 topic，避免 topic 爆炸），发送时以 `sessionId` 为
  shardingKey 哈希选队列——同一会话严格 FIFO，不同会话分散到 8 个队列并行；消费端
  （ORDERLY）按队列数限速驱动 Agent，高峰期请求排队而不是把 LLM 打挂。入队即回推
  「排队处理中」状态事件；MQ 关闭（`CHAT_MQ_ENABLED=false`）或发送失败自动降级为
  线程池同步转发，SSE 直连路径保持不变。
- **Redis 缓存（两层，物理隔离在不同 DB）**：
  - **L1 会话历史缓存（私有，DB0）**：`chat:hist:{userId}:{sessionId}`，用户读历史与
    Agent 装载记忆共用，防「同一用户反复读历史打 DB」。隐私三原则：① 键绑定服务端
    身份（userId 只来自 token/会话行，绝不接受客户端自报）；② 归属校验前置
    （`requireOwned` 先于任何缓存读取，缓存只是加速层不是授权层）；③ 写即失效 +
    短 TTL（append/delete 立刻 evict 本人键，默认 TTL 10 分钟）。Redis 不可用时
    全量降级回源 DB。
  - **L2 公共答案缓存（跨用户共享，DB1）**：C 端大量用户会问相同/相近的全局问题
    （「现在有什么优惠活动」），逐个走 LLM 纯烧 token。L2 把「纯全局知识轮次」的
    回答放入共享池，其他用户问相近问题直接复用：精确（归一化文本 O(1)）+ 语义
    （embedding 余弦 ≥ 0.80，实测同义改写 0.78~0.99、无关问题 ~0.62，可用
    `ANSWER_CACHE_SEMANTIC_THRESHOLD` 调节）。命中跳过意图/工具/LLM（实测从 ~8s
    降到 ~2s），回复照常落会话历史并带 `fromCache` 标记。

### L2 跨用户共享的隐私隔离

谁能进公共池（写入三道闸，任一不过不入池）：
1. 任务类型白名单——本轮任务必须 ⊆ {活动查询, 穿搭规则检索}，答案才是全局事实；
   混入任何个人类任务（衣橱/订单/物流/售后/收藏/试穿）整轮不入池；
2. 个人标识扫描——问题与回答都扫描订单号（CY…）、手机号、用户昵称；
3. 澄清/转人工/安全拦截轮不入池。

谁可以查公共池（读取预分类）：
4. 问题必须含活动/优惠/搭配等公共词，且不含「我的/衣橱/订单/退款」等个人词——
   个人问题根本不会查公共池，从源头杜绝把公共答案错配给个人场景。

时效与失效：活动类 TTL 5 分钟（活动会过期）、规则类 6 小时；规则发布/下线时清空
活动池（`/internal/rules/reindex`、`/internal/rules/fullsync` 联动）。Redis 或
Embedding 任何异常都静默降级为完整链路。

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
