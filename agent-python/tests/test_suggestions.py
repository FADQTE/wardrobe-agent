# -*- coding: utf-8 -*-
"""追问建议：与任务类型相关、去重、不重复用户刚问过的问题。"""
from app.suggestions import build_followups


def state(task_types, message="", **extra):
    return {
        "message": message,
        "intent_data": {"tasks": [{"id": f"t{i}", "type": t} for i, t in enumerate(task_types)]},
        "results": extra.pop("results", []),
        **extra,
    }


def test_activity_turn_suggests_coupon_followups():
    out = build_followups(state(["rule_query"]))

    assert any("新人专享券" in s for s in out)
    assert len(out) <= 4


def test_outfit_turn_suggests_tryon_and_replace():
    out = build_followups(state(
        ["wardrobe", "rag"],
        results=[{"type": "wardrobe", "ok": True,
                  "data": {"items": [{"name": "白色基础衬衫"}]}}]))

    assert any("白色基础衬衫" in s for s in out)
    assert any("效果图" in s for s in out)


def test_order_turn_suggests_logistics_and_aftersale():
    out = build_followups(state(["order_query"]))

    assert any("物流" in s for s in out)
    assert any("退款" in s or "退换" in s for s in out)


def test_clarify_turn_offers_scene_options():
    out = build_followups({
        "message": "", "results": [],
        "intent_data": {"tasks": [], "needsClarification": True},
    })

    assert "通勤" in out and "约会" in out


def test_defaults_do_not_repeat_current_question():
    out = build_followups(state(["rule_query"], message="现在都有什么优惠活动？"))

    assert all(not (s in "现在都有什么优惠活动？" or "现在都有什么优惠活动" in s) for s in out
               if "优惠活动" in s and "还能用" not in s and "叠加" not in s and "划算" not in s)


def test_handoff_turn_only_offers_retry():
    out = build_followups(state(["product"], handoff="业务事实查询失败"))

    assert out == ["再试一次"]
