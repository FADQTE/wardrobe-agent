# -*- coding: utf-8 -*-
"""全局配置：LLM / Embedding / Reranker / 基础设施地址（.env 可覆盖）。"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# LLM（OpenAI 兼容）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
MOCK_AGENT = os.getenv("MOCK_AGENT", "false").lower() == "true"

# Embedding
EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "none")  # ollama | api | none
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "") or LLM_BASE_URL
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "") or LLM_API_KEY
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Reranker（本地 cross-encoder 部署：Qwen3-Reranker-0.6B，Ollama 不支持 rerank）
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B")
RERANK_MODEL_DIR = os.getenv("RERANK_MODEL_DIR", str(Path(__file__).resolve().parent.parent / ".models"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "20"))
RERANK_THRESHOLD = float(os.getenv("RERANK_THRESHOLD", "0.3"))

# 基础设施
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
JAVA_MCP_URL = os.getenv("JAVA_MCP_URL", "http://localhost:8080/mcp/sse")
JAVA_API_URL = os.getenv("JAVA_API_URL", "http://localhost:8080/api")

PRODUCT_INDEX = "product_index"
RULE_INDEX = "rule_index"
