# -*- coding: utf-8 -*-
"""ES 索引初始化：商品/规则/长期记忆三索引 (product_index / rule_index / memory_index)。

- 中文分词：默认镜像未装 ik 插件，使用 standard 分词（逐字），
  BM25 + 标签 filter 组合适合当前数据量；后续可换 ik。
- dense_vector：仅当 EMBEDDING_MODE != none 时建向量字段（dims 可配）。
- memory_index 只作检索索引（MySQL agent_memory 才是事实源）：已存在时不删除重建，
  避免误清空记忆；结构变化可通过 /internal/memory/fullsync 重建。
"""
import os
from dotenv import load_dotenv

load_dotenv()

PRODUCT_INDEX = "product_index"
RULE_INDEX = "rule_index"
MEMORY_INDEX = "memory_index"

ES_URL = os.getenv("ES_URL", "http://localhost:9200")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))


def get_es():
    from elasticsearch import Elasticsearch
    es = Elasticsearch(ES_URL)
    if not es.ping():
        raise RuntimeError(f"ES 不可达: {ES_URL}")
    return es


def _product_mapping(with_vector: bool):
    props = {
        "name": {"type": "text", "analyzer": "standard"},
        "detail": {"type": "text", "analyzer": "standard"},
        "category": {"type": "keyword"},
        "color": {"type": "keyword"},
        "season": {"type": "keyword"},
        "style": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "price": {"type": "double"},
        "stock": {"type": "integer"},
        "sales": {"type": "integer"},
        "status": {"type": "integer"},
        "image_url": {"type": "keyword", "index": False},
    }
    if with_vector:
        # ES 8: dense_vector 需 indexed 才能指定 similarity（kNN/script_score 均可检索）
        props["embedding"] = {"type": "dense_vector", "dims": EMBEDDING_DIM,
                              "index": True, "similarity": "cosine"}
    return {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": props},
    }


def _rule_mapping(with_vector: bool):
    props = {
        "title": {"type": "text", "analyzer": "standard"},
        "content": {"type": "text", "analyzer": "standard"},
        "type": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "version": {"type": "integer"},
        "publish_status": {"type": "keyword"},
        "effective_from": {"type": "date"},
        "effective_to": {"type": "date"},
        "source": {"type": "keyword"},
    }
    if with_vector:
        props["embedding"] = {"type": "dense_vector", "dims": EMBEDDING_DIM,
                              "index": True, "similarity": "cosine"}
    return {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": props},
    }


def _memory_mapping(with_vector: bool):
    props = {
        "user_id": {"type": "keyword"},
        "memory_type": {"type": "keyword"},
        "predicate": {"type": "keyword"},
        "content": {"type": "text", "analyzer": "standard"},
        "importance": {"type": "float"},
        "confidence": {"type": "float"},
        "status": {"type": "keyword"},
        "created_at": {"type": "date"},
    }
    if with_vector:
        props["embedding"] = {"type": "dense_vector", "dims": EMBEDDING_DIM,
                              "index": True, "similarity": "cosine"}
    return {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": props},
    }


def ensure_indices(es, with_vector: bool):
    for name, body in (
        (PRODUCT_INDEX, _product_mapping(with_vector)),
        (RULE_INDEX, _rule_mapping(with_vector)),
    ):
        if es.indices.exists(index=name):
            es.indices.delete(index=name)
        es.indices.create(index=name, body=body)
        print(f"[init_es] created {name} (vector={with_vector}, dims={EMBEDDING_DIM})")
    # 记忆索引：只补建不重建，MySQL 才是事实源，误删可由 fullsync 重建
    if not es.indices.exists(index=MEMORY_INDEX):
        es.indices.create(index=MEMORY_INDEX, body=_memory_mapping(with_vector))
        print(f"[init_es] created {MEMORY_INDEX} (vector={with_vector}, dims={EMBEDDING_DIM})")


if __name__ == "__main__":
    es = get_es()
    with_vector = os.getenv("EMBEDDING_MODE", "none") != "none"
    ensure_indices(es, with_vector)
    print("indices:", es.cat.indices())
