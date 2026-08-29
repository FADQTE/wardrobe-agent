# -*- coding: utf-8 -*-
"""Hybrid RAG：ES 商品/规则双索引，BM25 与 kNN 独立召回后做加权 RRF 融合。

检索边界：
- 商品：status + 类目/颜色/季节/风格/价格过滤；
- 规则：published + 类型/标签 + 生效时间窗过滤；
- 向量不可用、维度不匹配或 kNN 异常时自动降级 BM25；
- `_source` 永远排除 embedding，避免把 1024 维向量传给 Agent/前端。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import config
from .es_client import get_es

CATEGORY_CN = {"top": "上装", "bottom": "下装", "outerwear": "外套",
               "dress": "连衣裙", "shoes": "鞋履", "accessory": "配饰"}
SEASON_ALIAS = {"春季": "春", "夏季": "夏", "秋季": "秋", "冬季": "冬"}
SOURCE_FILTER = {"excludes": ["embedding"]}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_tags(tags: Optional[list[str]]) -> list[str]:
    """标签归一化：把“秋季”等自然语言标签映射到索引枚举“秋”。"""
    out = [SEASON_ALIAS.get(tag, tag) for tag in tags or []]
    return [tag for tag in dict.fromkeys(out) if tag]


def _tag_filters(tags: Optional[list[str]]) -> list[dict]:
    return [{"term": {"tags": tag}} for tag in tags or []]


def _filtered_query(filters: list[dict], must: list[dict] | None = None) -> dict:
    return {"bool": {"must": must or [], "filter": filters}}


def _lexical_search(index: str, must: list[dict], filters: list[dict], size: int,
                    *, offset: int = 0, sort: list[dict] | None = None) -> dict:
    body: dict = {
        "query": _filtered_query(filters, must),
        "from": offset,
        "size": size,
        "track_total_hits": True,
        "_source": SOURCE_FILTER,
    }
    if sort:
        body["sort"] = sort
    return get_es().es.search(index=index, body=body)


def _vector_search(index: str, query: str, filters: list[dict], size: int) -> tuple[list[dict], str]:
    """独立 kNN 召回；返回 (hits, 状态)，任何故障都安全降级，不污染 BM25。"""
    es = get_es()
    if not es.index_has_vector(index):
        return [], "index_without_vector"
    vectors = es.embed([query])
    if not vectors or not vectors[0]:
        return [], "embedding_unavailable"
    expected_dims = es.vector_dims(index)
    if expected_dims and len(vectors[0]) != expected_dims:
        print(f"[hybrid] vector dims mismatch index={index} expected={expected_dims} "
              f"actual={len(vectors[0])}", flush=True)
        return [], "dimension_mismatch"
    try:
        k = max(1, size)
        knn: dict = {
            "field": "embedding",
            "query_vector": vectors[0],
            "k": k,
            "num_candidates": min(10_000, max(100, k * 4)),
        }
        if filters:
            knn["filter"] = {"bool": {"filter": filters}}
        response = es.es.search(index=index, body={
            "knn": knn,
            "size": k,
            "_source": SOURCE_FILTER,
        })
        return list(response["hits"]["hits"]), "ok"
    except Exception as error:
        print(f"[hybrid] kNN failed index={index}: {error}", flush=True)
        return [], "knn_error"


def _rrf_fuse(lexical_hits: list[dict], vector_hits: list[dict],
              *, offset: int = 0, size: int = 10) -> list[dict]:
    """加权 Reciprocal Rank Fusion；分数只依赖各通道排名，不混用 BM25/cosine 量纲。"""
    fused: dict[str, dict] = {}
    channels = (
        ("bm25", lexical_hits, config.HYBRID_LEXICAL_WEIGHT),
        ("knn", vector_hits, config.HYBRID_VECTOR_WEIGHT),
    )
    for channel, hits, weight in channels:
        for rank, hit in enumerate(hits, 1):
            doc_id = str(hit["_id"])
            entry = fused.setdefault(doc_id, {
                "hit": hit,
                "rrfScore": 0.0,
                "retrievalChannels": [],
                "channelRanks": {},
                "lexicalScore": None,
                "vectorScore": None,
            })
            entry["rrfScore"] += weight / (config.HYBRID_RRF_K + rank)
            entry["retrievalChannels"].append(channel)
            entry["channelRanks"][channel] = rank
            entry["lexicalScore" if channel == "bm25" else "vectorScore"] = hit.get("_score")
            if channel == "bm25":
                entry["hit"] = hit
    ranked = sorted(
        fused.values(),
        key=lambda item: (item["rrfScore"], item["lexicalScore"] or 0,
                          item["vectorScore"] or 0),
        reverse=True,
    )
    for entry in ranked:
        entry["rrfScore"] = round(entry["rrfScore"], 8)
    return ranked[offset:offset + size]


def _entry_source(entry: dict) -> dict:
    source = dict(entry["hit"].get("_source") or {})
    source.pop("embedding", None)
    return source


def _retrieval_mode(lexical_hits: list, vector_hits: list) -> str:
    if lexical_hits and vector_hits:
        return "hybrid_rrf"
    if vector_hits:
        return "knn"
    return "bm25"


def hybrid_product_search(keyword: str = "", category: str = "", color: str = "",
                          season: str = "", style: str = "", max_price: float | None = None,
                          page: int = 1, size: int = 24, min_score: float | None = None) -> dict:
    """商城检索：BM25 与 kNN 双路召回 + 标签过滤 + 加权 RRF。"""
    page, size = max(1, page), max(1, size)
    offset = (page - 1) * size
    filters: list[dict] = [{"term": {"status": 1}}]
    if category:
        filters.append({"term": {"category": category}})
    if color:
        filters.append({"term": {"color": color}})
    season = SEASON_ALIAS.get(season, season) if season else ""
    if season:
        filters.append({"term": {"season": season}})
    if style:
        filters.append({"term": {"style": style}})
    if max_price is not None:
        filters.append({"range": {"price": {"lte": max_price}}})

    if not keyword:
        response = _lexical_search(
            config.PRODUCT_INDEX, [], filters, size, offset=offset,
            sort=[{"sales": {"order": "desc"}}, {"_id": {"order": "desc"}}],
        )
        hits = list(response["hits"]["hits"])
        products = []
        for rank, hit in enumerate(hits, offset + 1):
            source = dict(hit.get("_source") or {})
            source.pop("embedding", None)
            products.append(source | {
                "id": int(hit["_id"]), "score": hit.get("_score"),
                "imageUrl": source.get("image_url"),
                "retrievalMode": "catalog_filter", "retrievalChannels": ["filter"],
                "channelRanks": {"filter": rank},
            })
        return {
            "products": products,
            "total": int(response["hits"]["total"]["value"]),
            "retrieval": {"mode": "catalog_filter", "lexicalHits": len(hits),
                          "vectorHits": 0, "vectorState": "not_requested"},
        }

    window = max(config.HYBRID_CANDIDATE_WINDOW, offset + size)
    must = [{"multi_match": {
        "query": keyword, "fields": ["name^3", "detail"], "type": "best_fields",
    }}]
    lexical = _lexical_search(config.PRODUCT_INDEX, must, filters, window)
    lexical_hits = list(lexical["hits"]["hits"])
    vector_hits, vector_state = _vector_search(config.PRODUCT_INDEX, keyword, filters, window)
    entries = _rrf_fuse(lexical_hits, vector_hits, offset=offset, size=size)
    mode = _retrieval_mode(lexical_hits, vector_hits)
    products = []
    for entry in entries:
        source = _entry_source(entry)
        product = source | {
            "id": int(entry["hit"]["_id"]),
            "score": entry["rrfScore"] if mode == "hybrid_rrf" else
                     (entry["lexicalScore"] or entry["vectorScore"]),
            "rrfScore": entry["rrfScore"],
            "lexicalScore": entry["lexicalScore"], "vectorScore": entry["vectorScore"],
            "retrievalMode": mode, "retrievalChannels": entry["retrievalChannels"],
            "channelRanks": entry["channelRanks"], "imageUrl": source.get("image_url"),
        }
        if min_score is None or max(product.get("lexicalScore") or 0,
                                    product.get("vectorScore") or 0) >= min_score:
            products.append(product)

    if not products and (color or season or style):
        fallback = hybrid_product_search(
            keyword=keyword, category=category, color="", season="", style="",
            max_price=max_price, page=page, size=size, min_score=min_score,
        )
        fallback.setdefault("retrieval", {})["relaxedFilters"] = [
            key for key, value in (("color", color), ("season", season), ("style", style)) if value
        ]
        return fallback

    lexical_total = int(lexical["hits"]["total"]["value"])
    return {
        "products": products,
        "total": max(lexical_total, len({str(hit["_id"]) for hit in lexical_hits + vector_hits})),
        "retrieval": {
            "mode": mode, "lexicalHits": len(lexical_hits), "vectorHits": len(vector_hits),
            "vectorState": vector_state, "candidateWindow": window,
            "rrf": {"rankConstant": config.HYBRID_RRF_K,
                    "lexicalWeight": config.HYBRID_LEXICAL_WEIGHT,
                    "vectorWeight": config.HYBRID_VECTOR_WEIGHT},
        },
    }


_cache: dict = {}


def invalidate_cache():
    _cache.clear()


def _cache_get(key):
    import time
    item = _cache.get(key)
    if item and time.time() - item[0] < 60:
        return item[1]
    return None


def _cache_put(key, value):
    import time
    _cache[key] = (time.time(), value)


def hybrid_rule_search(query: str, tags: Optional[list[str]] = None,
                       rule_type: Optional[str] = None, only_time_valid: bool = True,
                       size: int = 6, fallback_all: bool = False) -> list[dict]:
    """规则 RAG：BM25/kNN 双路召回，发布状态、标签和生效时间窗在两路中一致过滤。"""
    tags = normalize_tags(tags)
    cache_key = (query, tuple(tags), rule_type, only_time_valid, size, fallback_all)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    filters: list[dict] = [{"term": {"publish_status": "published"}}]
    if rule_type:
        filters.append({"term": {"type": rule_type}})
    if only_time_valid:
        now = _now_iso()
        filters.extend([
            {"range": {"effective_from": {"lte": now}}},
            {"range": {"effective_to": {"gte": now}}},
        ])
    filters.extend(_tag_filters(tags))

    if query:
        window = max(config.HYBRID_CANDIDATE_WINDOW, size)
        must = [{"multi_match": {
            "query": query, "fields": ["title^3", "content"], "type": "best_fields",
        }}]
        lexical = _lexical_search(config.RULE_INDEX, must, filters, window)
        lexical_hits = list(lexical["hits"]["hits"])
        vector_hits, vector_state = _vector_search(config.RULE_INDEX, query, filters, window)
        entries = _rrf_fuse(lexical_hits, vector_hits, size=size)
        mode = _retrieval_mode(lexical_hits, vector_hits)
    else:
        response = _lexical_search(
            config.RULE_INDEX, [], filters, size,
            sort=[{"effective_to": {"order": "asc"}}, {"effective_from": {"order": "desc"}}],
        )
        lexical_hits = list(response["hits"]["hits"])
        vector_hits, vector_state, mode = [], "not_requested", "catalog_filter"
        entries = _rrf_fuse(lexical_hits, [], size=size)

    rules = []
    for entry in entries:
        source = _entry_source(entry)
        effective_from, effective_to = source.get("effective_from"), source.get("effective_to")
        rules.append({
            "id": int(entry["hit"]["_id"]), "title": source.get("title"),
            "content": source.get("content"), "source": source.get("source"),
            "version": source.get("version"), "tags": source.get("tags", []),
            "type": source.get("type"), "publishStatus": source.get("publish_status"),
            "effectiveFrom": effective_from, "effectiveTo": effective_to,
            "timeValid": rule_time_valid(source),
            "score": entry["rrfScore"] if mode == "hybrid_rrf" else
                     (entry["lexicalScore"] or entry["vectorScore"]),
            "rrfScore": entry["rrfScore"], "lexicalScore": entry["lexicalScore"],
            "vectorScore": entry["vectorScore"], "retrievalMode": mode,
            "retrievalChannels": entry["retrievalChannels"],
            "channelRanks": entry["channelRanks"], "vectorState": vector_state,
        })

    if not rules and tags:
        rules = hybrid_rule_search(
            query, tags=None, rule_type=rule_type, only_time_valid=only_time_valid,
            size=size, fallback_all=fallback_all,
        )
    if fallback_all and not rules and query:
        rules = hybrid_rule_search(
            "", tags=tags, rule_type=rule_type,
            only_time_valid=only_time_valid, size=size, fallback_all=False,
        )
    _cache_put(cache_key, rules)
    return rules


def rule_time_valid(source: dict) -> bool:
    """按当前时间窗校验单条规则，作为 ES filter 之外的展示证据。"""
    if source.get("publish_status") != "published":
        return False
    now = datetime.now(timezone.utc)
    effective_from = source.get("effective_from")
    effective_to = source.get("effective_to")
    if effective_from:
        value = datetime.fromisoformat(effective_from.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if now < value:
            return False
    if effective_to:
        value = datetime.fromisoformat(effective_to.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if now > value:
            return False
    return True


def hybrid_memory_search(query: str, user_id: int, size: int = 5,
                         memory_types: Optional[list[str]] = None) -> list[dict]:
    """长期记忆混合召回：仅限当前用户的 active 记忆，BM25/kNN 双路 + 加权 RRF。

    边界：user_id + status 在两路中一致过滤；索引/向量不可用时安全降级 BM25。
    """
    filters = [{"term": {"user_id": str(user_id)}}, {"term": {"status": "active"}}]
    if memory_types:
        filters.append({"terms": {"memory_type": memory_types}})
    window = max(config.HYBRID_CANDIDATE_WINDOW, size)
    must = [{"match": {"content": {"query": query}}}]
    lexical = _lexical_search(config.MEMORY_INDEX, must, filters, window)
    lexical_hits = list(lexical["hits"]["hits"])
    vector_hits, vector_state = _vector_search(config.MEMORY_INDEX, query, filters, window)
    entries = _rrf_fuse(lexical_hits, vector_hits, size=size)
    mode = _retrieval_mode(lexical_hits, vector_hits)
    memories = []
    for entry in entries:
        source = _entry_source(entry)
        memories.append({
            "id": int(entry["hit"]["_id"]),
            "memoryType": source.get("memory_type"), "predicate": source.get("predicate"),
            "content": source.get("content"), "importance": source.get("importance"),
            "confidence": source.get("confidence"), "createdAt": source.get("created_at"),
            "score": entry["rrfScore"] if mode == "hybrid_rrf" else
                     (entry["lexicalScore"] or entry["vectorScore"]),
            "retrievalMode": mode, "retrievalChannels": entry["retrievalChannels"],
            "vectorState": vector_state,
        })
    return memories
