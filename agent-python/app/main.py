"""潮引智能衣橱商城 - AI 穿搭客服 Agent 服务（FastAPI + LangGraph）。"""
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router

app = FastAPI(title="chaoyin-agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def repair_rule_index_on_startup():
    """Java/Agent 并行启动时短暂重试，全量修复可能漏掉的规则增量通知。"""
    import httpx

    from .api import rules_fullsync
    from . import config

    async def run():
        for delay in (2, 5, 10):
            await asyncio.sleep(delay)
            result = await rules_fullsync()
            if result.get("code") == 0:
                print(f"[startup] {result.get('msg')}", flush=True)
                break
        else:
            print("[startup] rule fullsync skipped: Java/ES still unavailable", flush=True)
        # 记忆遗忘：启动时归档陈旧低强度记忆（用户明确高置信记忆天然豁免）
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post(f"{config.JAVA_API_URL}/memory/decay",
                                 params={"staleDays": 30})
                if r.status_code == 200:
                    print(f"[startup] memory decay archived "
                          f"{(r.json().get('data') or 0)} memories", flush=True)
        except Exception as e:
            print(f"[startup] memory decay skipped: {e}", flush=True)

    asyncio.create_task(run())


@app.get("/health")
async def health():
    from . import config
    from . import rerank as rerank_mod
    from .es_client import get_es
    es = get_es()
    return {
        "status": "ok",
        "service": "chaoyin-agent",
        "mockAgent": config.MOCK_AGENT or not config.LLM_API_KEY,
        "llm": config.LLM_MODEL,
        "llmBaseUrl": config.LLM_BASE_URL,
        "es": es.ping(),
        "indices": es.index_status(),
        "embedding": config.EMBEDDING_MODE,
        "embeddingModel": config.EMBEDDING_MODEL,
        "hybridRag": {
            "fusion": "weighted_rrf",
            "rankConstant": config.HYBRID_RRF_K,
            "lexicalWeight": config.HYBRID_LEXICAL_WEIGHT,
            "vectorWeight": config.HYBRID_VECTOR_WEIGHT,
            "candidateWindow": config.HYBRID_CANDIDATE_WINDOW,
        },
        "rerank": {
            "enabled": config.RERANK_ENABLED,
            "model": config.RERANK_MODEL,
            "state": rerank_mod.status(),
        },
        "tryon": {
            "mode": config.TRYON_MODE,
            "providerConfigured": bool(config.TRYON_PROVIDER_URL),
        },
    }
