# -*- coding: utf-8 -*-
"""追问建议：按本轮实际执行的任务与结果生成 2~4 条可点击的后续问题。

规则派生（非 LLM）：零成本、零延迟，且与 Agent 真实做过的事强相关——
查过活动就追问券的使用，出了搭配就追问试穿/替换，查过订单就追问物流/售后。
"""
from __future__ import annotations

import re

DEFAULT_FOLLOWUPS = [
    "现在都有什么优惠活动",
    "用我衣橱里的衣服搭一套秋季通勤装",
    "查一下我的订单",
]


def _similar(a: str, b: str) -> bool:
    """去掉标点后互为包含，或字符重合度过高 → 视为与用户刚问过的问题重复。"""
    a = re.sub(r"[，。？?！!·、\s]", "", a or "")
    b = re.sub(r"[，。？?！!·、\s]", "", b or "")
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, min(len(sa), len(sb))) > 0.7


def _names(results: list[dict], result_type: str, limit: int = 1) -> list[str]:
    for r in results:
        if r.get("type") == result_type and r.get("ok"):
            data = r.get("data") or {}
            items = data.get("items") or data.get("products") or []
            return [i.get("name") for i in items[:limit] if i.get("name")]
    return []


def build_followups(final_state: dict) -> list[str]:
    intent = final_state.get("intent_data") or {}
    if intent.get("needsClarification"):
        # 澄清轮：给常见场景选项，点一下就能补全信息
        return ["通勤", "约会", "面试", "旅行"]
    if final_state.get("handoff"):
        return ["再试一次"]
    if final_state.get("safety_data", {}).get("blocked_user_request"):
        return ["用我衣橱里的衣服搭一套通勤装"]

    message = final_state.get("message") or ""
    results = final_state.get("results") or []
    types = {t.get("type") for t in (intent.get("tasks") or [])}
    out: list[str] = []

    if "image" in types:
        out += ["换一个场景再生成一张", "把图里的外套换成商城在售的"]
    if "wardrobe" in types or "rag" in types:
        wn = _names(results, "wardrobe")
        if wn:
            out.append(f"把「{wn[0]}」换成商城在售的替代款")
        out += ["基于这套生成换装效果图", "再配一双鞋和一个包"]
    if "product" in types:
        pn = _names(results, "product")
        if pn:
            out.append(f"看看「{pn[0]}」的详情和尺码")
        out += ["收藏这件，回头再买", "有没有更便宜的同类款"]
    if "rule_query" in types:
        out += ["新人专享券现在还能用吗", "这些活动可以叠加使用吗", "用最划算的活动搭一套"]
    if "order" in types or "favorite" in types:
        out += ["查一下我的订单状态", "继续逛逛类似商品"]
    if "order_query" in types:
        out += ["查一下最新订单的物流", "尺码不合适怎么申请退款"]
    if "logistics" in types:
        out += ["申请退款要怎么操作", "查我的其他订单"]
    if "aftersale" in types:
        apply_result = next((r for r in results if r.get("type") == "aftersale"), None)
        apply_data = (apply_result or {}).get("data") or {}
        if apply_data.get("needsOrderNo"):
            nos = [o.get("orderNo") for o in apply_data.get("orders", [])[:3] if o.get("orderNo")]
            return nos or ["帮我查一下我的订单"]
        if apply_data.get("action") == "apply":
            return ["售后单审核到哪一步了",
                    "符合什么条件可以自动退款",
                    "帮我重新挑一件替代"]
        out += ["售后进度到哪里了", "帮我重新挑一件替代"]
    if "cart" in types:
        cart_result = next((r for r in results if r.get("type") == "cart"), None)
        if ((cart_result or {}).get("data") or {}).get("action") == "list":
            return ["帮我把购物车里的商品下单", "继续挑一件搭配的外套"]
        out += ["看下我的购物车", "帮我直接下单购物车里的商品"]

    out += [d for d in DEFAULT_FOLLOWUPS if not _similar(d, message)]
    seen: set[str] = set()
    unique = [s for s in out if not (s in seen or seen.add(s))]
    return unique[:4]
