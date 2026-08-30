# -*- coding: utf-8 -*-
"""Hybrid RAG：ES 双索引（商品/规则），BM25 + 向量 kNN(script_score) + 标签过滤 + 时间窗过滤。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import config
from .es_client import get_es

CATEGORY_CN = {"top": "上装", "bottom": "下装", "outerwear": "外套",
               "dress": "连衣裙", "shoes": "鞋履", "accessory": "配饰"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SEASON_ALIAS = {"春季": "春", "夏季": "夏", "秋季": "秋", "冬季": "冬"}


def normalize_tags(tags: Optional[list[str]]) -> list[str]:
    """标签归一化：LLM 可能输出"秋季/春季"等全称，映射到知识库枚举（秋/春…）。"""
    out = []
    for t in tags or []:
        out.append(SEASON_ALIAS.get(t, t))
    return [t for t in dict.fromkeys(out) if t]


def _tag_filters(tags: Optional[list[str]], prefix: str = "") -> list:
    if not tags:
        return []
    return [{"term": {f"{prefix}tags": t}} for t in tags]


def hybrid_product_search(keyword: str = "", category: str = "", color: str = "",
                          season: str = "", style: str = "", max_price: float | None = None,
                          page: int = 1, size: int = 24, min_score: float | None = None) -> dict:
    """商城商品混合检索：BM25 + 标签过滤 +（可选）向量相似度。"""
    es = get_es()
    must, filters = [], []
    if keyword:
        must.append({"multi_match": {
            "query": keyword,
            "fields": ["name^3", "detail"],
            "type": "best_fields",
        }})
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
    filters.append({"term": {"status": 1}})

    body = {"query": {"bool": {"must": must, "filter": filters}},
            "from": (page - 1) * size, "size": size}
    if not must:
        body["sort"] = [{"sales": {"order": "desc"}}]

    # 向量召回（若索引带向量且关键词非空）
    if keyword and es.has_vector:
        vec = es.embed([keyword])
        if vec:
            body["query"]["bool"]["should"] = [{
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "cosineSimilarity(params.q, 'embedding') + 1.0",
                        "params": {"q": vec[0]},
                    },
                },
            }]
            body["query"]["bool"]["minimum_should_match"] = 1

    resp = es.es.search(index=config.PRODUCT_INDEX, body=body)
    products = [h["_source"] | {"id": int(h["_id"]), "score": h["_score"],
                                "imageUrl": h["_source"].get("image_url")}
                for h in resp["hits"]["hits"]]
    # 兜底：颜色/季节/风格过滤过严导致零命中 → 去掉这三个条件重试（保留关键词/类目/价格）
    if not products and (color or season or style):
        return hybrid_product_search(keyword=keyword, category=category,
                                     color="", season="", style="",
                                     max_price=max_price, page=page, size=size)
    if min_score is not None and keyword:
        products = [p for p in products if p["score"] >= min_score]
    return {"products": products, "total": resp["hits"]["total"]["value"]}


# ---------- 检索结果缓存（规则发布时整体失效） ----------
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
    """规则 RAG：关键词 + 标签过滤 + 时间窗过滤（only_time_valid 时过滤过期/未生效/未发布）。

    fallback_all=True 时（活动查询）：关键词零命中则回退返回当前全部有效规则。
    返回: [{id, title, content, source, version, timeValid, tags, score}]
    """
    cache_key = (query, tuple(tags or []), rule_type, only_time_valid, size)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    tags = normalize_tags(tags)
    es = get_es()
    must = []
    if query:
        must.append({"multi_match": {"query": query, "fields": ["title^3", "content"], "type": "best_fields"}})
    filters = [{"term": {"publish_status": "published"}}]
    if rule_type:
        filters.append({"term": {"type": rule_type}})
    if only_time_valid:
        now = _now_iso()
        filters.append({"range": {"effective_from": {"lte": now}}})
        filters.append({"range": {"effective_to": {"gte": now}}})
    filters.extend(_tag_filters(tags))

    body = {"query": {"bool": {"must": must, "filter": filters}}, "size": size}
    if not must:
        body["sort"] = [{"effective_from": {"order": "desc"}}]
    if query and es.has_vector:
        vec = es.embed([query])
        if vec:
            body["query"]["bool"]["should"] = [{
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "cosineSimilarity(params.q, 'embedding') + 1.0",
                        "params": {"q": vec[0]},
                    },
                },
            }]
            body["query"]["bool"]["minimum_should_match"] = 1

    resp = es.es.search(index=config.RULE_INDEX, body=body)
    rules = []
    for h in resp["hits"]["hits"]:
        s = h["_source"]
        ef, et = s.get("effective_from"), s.get("effective_to")
        rules.append({
            "id": int(h["_id"]), "title": s.get("title"), "content": s.get("content"),
            "source": s.get("source"), "version": s.get("version"),
            "tags": s.get("tags", []), "type": s.get("type"),
            "effectiveFrom": ef, "effectiveTo": et,
            "timeValid": only_time_valid, "score": h["_score"],
        })
    # 兜底1：标签过滤导致零命中 → 去掉标签重试（LLM 标签粒度可能过细）
    if not rules and tags:
        rules = hybrid_rule_search(query, tags=None, rule_type=rule_type,
                                   only_time_valid=only_time_valid, size=size)
    # 兜底2：关键词零命中时回退返回当前全部有效规则（活动查询场景）
    if fallback_all and not rules and query:
        rules = hybrid_rule_search("", tags=tags, rule_type=rule_type,
                                   only_time_valid=only_time_valid, size=size)
    _cache_put(cache_key, rules)
    return rules


def rule_time_valid(source: dict) -> bool:
    """按当前时间窗校验单条规则（查询前过滤）。"""
    if source.get("publish_status") != "published":
        return False
    now = datetime.now(timezone.utc)
    ef = source.get("effective_from")
    et = source.get("effective_to")
    if ef:
        t = datetime.fromisoformat(ef.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if now < t:
            return False
    if et:
        t = datetime.fromisoformat(et.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if now > t:
            return False
    return True
