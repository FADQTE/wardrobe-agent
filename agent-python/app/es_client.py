# -*- coding: utf-8 -*-
"""ES 客户端与索引管理（与 scripts/init_es.py 一致）。"""
from __future__ import annotations

from typing import Optional

from . import config
from .llm import get_llm


class EsClient:
    def __init__(self):
        from elasticsearch import Elasticsearch
        self.es = Elasticsearch(config.ES_URL)
        self._embedding_client = None

    def ping(self) -> bool:
        try:
            return bool(self.es.ping())
        except Exception:
            return False

    # ---------- embedding ----------
    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """按配置生成向量；不可用返回 None（降级纯 BM25）。"""
        if config.EMBEDDING_MODE == "none":
            return None
        if config.EMBEDDING_MODE == "api":
            try:
                if self._embedding_client is None:
                    from openai import OpenAI
                    self._embedding_client = OpenAI(
                        base_url=config.EMBEDDING_BASE_URL,
                        api_key=config.EMBEDDING_API_KEY or "none")
                resp = self._embedding_client.embeddings.create(
                    model=config.EMBEDDING_MODEL, input=texts)
                return [r.embedding for r in resp.data]
            except Exception as e:
                print(f"[embed] api failed: {e}")
                return None
        # local 模式未安装 sentence-transformers
        return None

    @property
    def has_vector(self) -> bool:
        try:
            m = self.es.indices.get_mapping(index=config.PRODUCT_INDEX)
            props = m[config.PRODUCT_INDEX]["mappings"]["properties"]
            return "embedding" in props
        except Exception:
            return False


_es: Optional[EsClient] = None


def get_es() -> EsClient:
    global _es
    if _es is None:
        _es = EsClient()
    return _es
