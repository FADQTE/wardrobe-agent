# 智能衣橱一键启动脚本
# 用法: 在项目根目录执行  .\start.ps1
# 前提: Docker Desktop 运行中; JDK17 / Python3.10 / Node24 / pnpm 已安装

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
# 加载本机私有配置（local-env.ps1 已被 .gitignore 排除，不会提交；用于 JAVA_HOME 等机器相关变量）
if (Test-Path "$root\local-env.ps1") { . "$root\local-env.ps1" }
# uv / pnpm 的缓存目录统一固定到仓库内（不污染系统目录，也不把机器路径写进仓库）
$env:UV_CACHE_DIR = "$root\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$root\.uv-python"
$env:UV_LINK_MODE = 'copy'
$env:npm_config_store_dir = "$root\.pnpm-store"
$env:npm_config_cache_dir = "$root\.pnpm-cache"

Write-Host '== 1/5 启动基础设施 (MySQL + Elasticsearch) ==' -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host 'docker compose 失败，请确认 Docker Desktop 已启动' -ForegroundColor Red; exit 1 }

Write-Host '== 2/5 等待 MySQL / ES 就绪 ==' -ForegroundColor Cyan
$ready = $false
foreach ($i in 1..60) {
    $mysqlOk = $false; $esOk = $false
    try { $mysqlOk = (Test-NetConnection -ComputerName localhost -Port 16543 -InformationLevel Quiet -WarningAction SilentlyContinue) } catch {}
    try { $r = Invoke-WebRequest -Uri 'http://localhost:16544/_cluster/health' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop; $esOk = ($r.StatusCode -eq 200) } catch {}
    if ($mysqlOk -and $esOk) { $ready = $true; break }
    Write-Host "  等待中... ($i/60)" -ForegroundColor DarkGray
    Start-Sleep -Seconds 3
}
if (-not $ready) { Write-Host '基础设施未就绪，请检查 docker compose ps' -ForegroundColor Red; exit 1 }
Write-Host '  基础设施就绪' -ForegroundColor Green

Write-Host '== 3/5 准备 Agent 环境 (uv sync + 种子数据) ==' -ForegroundColor Cyan
if (-not (Test-Path "$root\agent-python\.venv")) {
    Write-Host '  使用 uv 创建环境并安装依赖（阿里云镜像，缓存位于 D 盘 .uv-cache）...' -ForegroundColor DarkGray
    Set-Location "$root\agent-python"
    uv sync
    if (-not (Test-Path .env)) { Copy-Item .env.example .env }
    Set-Location $root
}
# 仅空库初始化；禁止日常启动清空聊天、订单和 Session Memory。
Write-Host '  检查种子数据（仅空库初始化，保留现有聊天与订单）...' -ForegroundColor DarkGray
& "$root\agent-python\.venv\Scripts\python.exe" "$root\scripts\seed.py" --if-empty

Write-Host '== 4/5 启动后端服务 (Spring Boot :16545 / Agent :16546 / Netty WS :16547) ==' -ForegroundColor Cyan
if ($env:JAVA_HOME) {
    Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root\backend-java'; mvn '-Dmaven.repo.local=$root\.m2repo' -s '$root\.mvn\settings.xml' spring-boot:run"
} else {
    Write-Host '  未检测到 JAVA_HOME，跳过 Spring Boot 后端。' -ForegroundColor Yellow
    Write-Host '  修复：在项目根目录创建 local-env.ps1，写入 $env:JAVA_HOME = "本机JDK17路径"（该文件不会被提交），重新运行本脚本。' -ForegroundColor Yellow
}
Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root\agent-python'; uv run uvicorn app.main:app --host 0.0.0.0 --port 16546"

Write-Host '== 5/5 启动前端 (Vite :16548) ==' -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root\frontend'; pnpm dev"

Write-Host ''
Write-Host '完成! 打开 http://localhost:16548' -ForegroundColor Green
Write-Host '  后端健康: http://localhost:16545/api/health' -ForegroundColor DarkGray
Write-Host '  Agent健康: http://localhost:16546/health' -ForegroundColor DarkGray
Write-Host '  Netty WS:  ws://localhost:16547/ws/chat' -ForegroundColor DarkGray
