# 潮引智能衣橱商城 Demo 一键启动脚本
# 用法: 在项目根目录执行  .\start.ps1
# 前提: Docker Desktop 运行中; JDK17 / Python3.10 / Node24 / pnpm 已安装

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
# uv 缓存与 Python 安装目录固定到 D 盘（不写 C 盘）
$env:UV_CACHE_DIR = "$root\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$root\.uv-python"
$env:UV_LINK_MODE = 'copy'

Write-Host '== 1/5 启动基础设施 (MySQL + Elasticsearch) ==' -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host 'docker compose 失败，请确认 Docker Desktop 已启动' -ForegroundColor Red; exit 1 }

Write-Host '== 2/5 等待 MySQL / ES 就绪 ==' -ForegroundColor Cyan
$ready = $false
foreach ($i in 1..60) {
    $mysqlOk = $false; $esOk = $false
    try { $mysqlOk = (Test-NetConnection -ComputerName localhost -Port 3307 -InformationLevel Quiet -WarningAction SilentlyContinue) } catch {}
    try { $r = Invoke-WebRequest -Uri 'http://localhost:9200/_cluster/health' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop; $esOk = ($r.StatusCode -eq 200) } catch {}
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

Write-Host '== 4/5 启动后端服务 (Spring Boot :8080 / Agent :8000 / Netty WS :8090) ==' -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-Command',"`$env:JAVA_HOME='D:\jdk17'; Set-Location '$root\backend-java'; mvn -s '$root\.mvn\settings.xml' spring-boot:run"
Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root\agent-python'; uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"

Write-Host '== 5/5 启动前端 (Vite :5173) ==' -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$root\frontend'; pnpm dev"

Write-Host ''
Write-Host '完成! 打开 http://localhost:5173' -ForegroundColor Green
Write-Host '  后端健康: http://localhost:8080/api/health' -ForegroundColor DarkGray
Write-Host '  Agent健康: http://localhost:8000/health' -ForegroundColor DarkGray
Write-Host '  Netty WS:  ws://localhost:8090/ws/chat' -ForegroundColor DarkGray
