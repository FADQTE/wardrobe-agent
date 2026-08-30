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
        if config.EMBEDDING_MODE == "ollama":
            try:
                import httpx
                resp = httpx.post(f"{config.OLLAMA_URL}/api/embed",
                                  json={"model": config.EMBEDDING_MODEL, "input": texts},
                                  timeout=120)
                resp.raise_for_status()
                return resp.json()["embeddings"]
            except Exception as e:
                print(f"[embed] ollama failed: {e}", flush=True)
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
                print(f"[embed] api failed: {e}", flush=True)
                return None
        return None

    def index_has_vector(self, index: str) -> bool:
        try:
            m = self.es.indices.get_mapping(index=index)
            props = m[index]["mappings"]["properties"]
            return "embedding" in props
        except Exception:
            return False

    def vector_dims(self, index: str) -> int | None:
        try:
            m = self.es.indices.get_mapping(index=index)
            field = m[index]["mappings"]["properties"].get("embedding") or {}
            return int(field["dims"]) if field.get("dims") else None
        except Exception:
            return None

    @property
    def has_vector(self) -> bool:
        """向后兼容：商品索引是否具备向量字段。新代码应显式传入索引名。"""
        return self.index_has_vector(config.PRODUCT_INDEX)

    def index_status(self) -> dict:
        """返回双索引的文档数、向量覆盖数与 Mapping 状态，供健康页验收。"""
        result = {}
        for index in (config.PRODUCT_INDEX, config.RULE_INDEX):
            try:
                exists = bool(self.es.indices.exists(index=index))
                if not exists:
                    result[index] = {"exists": False, "documents": 0,
                                     "vectorDocuments": 0, "vectorDims": None}
                    continue
                has_vector = self.index_has_vector(index)
                result[index] = {
                    "exists": True,
                    "documents": int(self.es.count(index=index)["count"]),
                    "vectorDocuments": int(self.es.count(
                        index=index, query={"exists": {"field": "embedding"}})["count"])
                    if has_vector else 0,
                    "vectorDims": self.vector_dims(index),
                }
            except Exception as e:
                result[index] = {"exists": False, "error": str(e)[:160]}
        return result


_es: Optional[EsClient] = None


def get_es() -> EsClient:
    global _es
    if _es is None:
        _es = EsClient()
    return _es
