# -*- coding: utf-8 -*-
"""Mock 意图解析：无 LLM Key 时按规则拆解，保证本地链路可运行。"""
from __future__ import annotations

import re

SCENE_TAGS = {
    "通勤": ["通勤", "职场"], "约会": ["约会"], "运动": ["运动", "健身"],
    "正式": ["正式", "面试", "商务"], "休闲": ["休闲", "日常", "周末"],
}
SEASON_TAGS = {"秋": ["秋季", "秋天", "秋"], "冬": ["冬季", "冬天", "冬"],
               "夏": ["夏季", "夏天", "夏"], "春": ["春季", "春天", "春"]}
COLOR_TAGS = ["白色", "黑色", "浅蓝", "深蓝", "藏青", "灰色", "卡其", "米色", "粉色", "酒红", "墨绿", "棕色"]
ITEM_TAGS = ["衬衫", "T恤", "牛仔裤", "西装裤", "裤子", "裙子", "连衣裙", "外套", "风衣", "大衣", "卫衣", "针织", "鞋", "包", "围巾"]


def _tags(message: str) -> list:
    tags = [c for c in COLOR_TAGS if c in message]
    tags += [i for i in ITEM_TAGS if i in message]
    return tags


def _scene_tags(message: str) -> list:
    tags = []
    for scene, kws in SCENE_TAGS.items():
        if any(k in message for k in kws):
            tags.append(scene)
    for season, kws in SEASON_TAGS.items():
        if any(k in message for k in kws):
            tags.append(season)
    return tags


def _price(message: str):
    m = re.search(r"(\d+)\s*(?:元|块|以内|以下)", message)
    if m:
        return float(m.group(1))
    m = re.search(r"预算\s*(\d+)", message)
    return float(m.group(1)) if m else None


def _keyword(message: str) -> str:
    tags = _tags(message)
    if tags:
        return " ".join(tags[:2])
    return ""


def parse_mock(message: str, memory_desc: str = "") -> dict:
    tasks = []

    def tid():
        return f"t{len(tasks) + 1}"

    wants_image = any(k in message for k in ["效果图", "生成图", "换装", "试穿", "上身效果", "看图"])
    wants_product = any(k in message for k in ["在售", "买", "商品", "预算", "下单", "购买", "收藏", "推荐商品"])
    wants_wardrobe = any(k in message for k in ["衣橱", "我的", "已有", "搭配", "搭一套", "穿搭", "这件"])
    wants_rule = any(k in message for k in ["活动", "优惠", "折扣", "满减", "券", "促销"])

    deps_base = []
    if wants_wardrobe:
        tasks.append({"id": tid(), "type": "wardrobe", "params": {"tags": _tags(message)}, "deps": []})
        deps_base.append(tasks[-1]["id"])
    if wants_wardrobe or wants_rule:
        scene = _scene_tags(message)
        query = " ".join(scene) if scene else (message[:20] if wants_wardrobe else "活动 优惠")
        rtype = "rag"
        if wants_rule and not wants_wardrobe:
            rtype = "rule_query"
        tasks.append({"id": tid(), "type": rtype,
                      "params": {"query": query, "tags": scene}, "deps": []})
        deps_base.append(tasks[-1]["id"])
    if wants_product:
        tasks.append({"id": tid(), "type": "product",
                      "params": {"keyword": _keyword(message),
                                 "style": _scene_tags(message)[0] if _scene_tags(message) else "",
                                 "maxPrice": _price(message)},
                      "deps": []})
        deps_base.append(tasks[-1]["id"])
    if wants_image:
        tasks.append({"id": tid(), "type": "image",
                      "params": {"label": "基于当前搭配的换装效果"},
                      "deps": list(deps_base)})
    if "收藏" in message:
        tasks.append({"id": tid(), "type": "favorite",
                      "params": {"productIds": [], "keyword": _keyword(message)},
                      "deps": [t["id"] for t in tasks if t["type"] == "product"]})
    if ("下单" in message or "购买" in message) and wants_product:
        tasks.append({"id": tid(), "type": "order",
                      "params": {"productIds": [], "keyword": _keyword(message)},
                      "deps": [t["id"] for t in tasks if t["type"] == "product"]})

    if not tasks:
        return {
            "confidence": 0.4, "needsClarification": True,
            "clarifyQuestion": "这个需求我还不太确定，能补充一下吗？比如：想搭什么场景（通勤/约会/运动）、用什么单品、要不要商城商品？",
            "summary": "意图不明", "tasks": [],
        }

    # 澄清场景：指代不明（"这件衣服"）且记忆里没有选中单品
    if any(k in message for k in ["这件", "那个", "这件衣服", "这个"]) and "衣橱" not in message:
        if not memory_desc or "已选单品" not in memory_desc:
            return {
                "confidence": 0.5, "needsClarification": True,
                "clarifyQuestion": "你指的是哪一件呢？可以从衣橱选择一件（例如：衣橱里的白衬衫），或告诉我在商城看到的商品名称。",
                "summary": "指代不明，需澄清", "tasks": [],
            }

    return {
        "confidence": 0.85, "needsClarification": False, "clarifyQuestion": "",
        "summary": message[:30], "tasks": tasks,
    }
