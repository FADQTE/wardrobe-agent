"""潮引智能衣橱商城 - AI 穿搭客服 Agent 服务（FastAPI + LangGraph）。"""
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


@app.get("/health")
async def health():
    from . import config
    from . import rerank as rerank_mod
    from .es_client import get_es
    return {
        "status": "ok",
        "service": "chaoyin-agent",
        "mockAgent": config.MOCK_AGENT or not config.LLM_API_KEY,
        "llm": config.LLM_MODEL,
        "llmBaseUrl": config.LLM_BASE_URL,
        "es": get_es().ping(),
        "embedding": config.EMBEDDING_MODE,
        "embeddingModel": config.EMBEDDING_MODEL,
        "rerank": {
            "enabled": config.RERANK_ENABLED,
            "model": config.RERANK_MODEL,
            "state": rerank_mod.status(),
        },
    }
