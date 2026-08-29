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
# 思考强度：off | enabled | max（max 附带 16384 思考预算，DeepSeek thinking schema）
LLM_THINKING = os.getenv("LLM_THINKING", "off")

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
RERANK_MODEL_DIR = (os.getenv("RERANK_MODEL_DIR", "").strip()
                      or str(Path(__file__).resolve().parent.parent / ".models"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "20"))
RERANK_THRESHOLD = float(os.getenv("RERANK_THRESHOLD", "0.3"))

# Hybrid RAG：BM25 与 kNN 独立召回后使用加权 RRF 融合。
HYBRID_RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
HYBRID_LEXICAL_WEIGHT = float(os.getenv("HYBRID_LEXICAL_WEIGHT", "1.0"))
HYBRID_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.8"))
HYBRID_CANDIDATE_WINDOW = int(os.getenv("HYBRID_CANDIDATE_WINDOW", "50"))

# 基础设施
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
JAVA_MCP_URL = os.getenv("JAVA_MCP_URL", "http://localhost:8080/mcp/sse")
JAVA_API_URL = os.getenv("JAVA_API_URL", "http://localhost:8080/api")

# 长期记忆：写入管线开关（抽取+落库）；读取相关参数
MEMORY_WRITE_ENABLED = os.getenv("MEMORY_WRITE_ENABLED", "true").lower() == "true"

# 虚拟试衣：mock 使用本地预设结果；http 调用可配置的真实生图服务。
TRYON_MODE = os.getenv("TRYON_MODE", "mock").strip().lower()
TRYON_PROVIDER_URL = os.getenv("TRYON_PROVIDER_URL", "").strip()
TRYON_PROVIDER_API_KEY = os.getenv("TRYON_PROVIDER_API_KEY", "").strip()
TRYON_PROVIDER_TIMEOUT = float(os.getenv("TRYON_PROVIDER_TIMEOUT", "60"))
TRYON_POLL_INTERVAL = float(os.getenv("TRYON_POLL_INTERVAL", "1.5"))
TRYON_POLL_TIMEOUT = float(os.getenv("TRYON_POLL_TIMEOUT", "180"))

PRODUCT_INDEX = "product_index"
RULE_INDEX = "rule_index"
