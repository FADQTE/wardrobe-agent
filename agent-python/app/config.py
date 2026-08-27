# -*- coding: utf-8 -*-
"""全局配置：LLM / Embedding / 基础设施地址（.env 可覆盖）。"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM（OpenAI 兼容）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
MOCK_AGENT = os.getenv("MOCK_AGENT", "false").lower() == "true"

# Embedding
EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "none")  # local | api | none
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "") or LLM_BASE_URL
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "") or LLM_API_KEY
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# 基础设施
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
JAVA_MCP_URL = os.getenv("JAVA_MCP_URL", "http://localhost:8080/mcp/sse")
JAVA_API_URL = os.getenv("JAVA_API_URL", "http://localhost:8080/api")

PRODUCT_INDEX = "product_index"
RULE_INDEX = "rule_index"
