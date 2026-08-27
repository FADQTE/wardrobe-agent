# -*- coding: utf-8 -*-
"""ES 索引初始化：商品双索引 (product_index / rule_index)。

- 中文分词：默认镜像未装 ik 插件，使用 standard 分词（逐字），
  BM25 + 标签 filter 组合对 demo 场景足够；后续可换 ik。
- dense_vector：仅当 EMBEDDING_MODE != none 时建向量字段（dims 可配）。
"""
import os
from dotenv import load_dotenv

load_dotenv()

PRODUCT_INDEX = "product_index"
RULE_INDEX = "rule_index"

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
        props["embedding"] = {"type": "dense_vector", "dims": EMBEDDING_DIM,
                              "index": False, "similarity": "cosine"}
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
                              "index": False, "similarity": "cosine"}
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


if __name__ == "__main__":
    es = get_es()
    with_vector = os.getenv("EMBEDDING_MODE", "none") != "none"
    ensure_indices(es, with_vector)
    print("indices:", es.cat.indices())
