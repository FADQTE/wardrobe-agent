# -*- coding: utf-8 -*-
"""用户点名具体活动/优惠券时的状态核验：下线/草稿/过期不再被清单模板顶替。"""
import unittest
from unittest.mock import patch

from app.graph import _compose_activity_list, _compose_rule_status_answer
from app.tasks import _lookup_named_activity, is_broad_activity_query

OFFLINE_COUPON = {
    "id": 26, "title": "新人专享券", "content": "首单满 200 减 30，全场通用。",
    "source": "运营平台", "publishStatus": "offline",
    "effectiveFrom": "2026-06-30T18:09:54+08:00",
    "effectiveTo": "2026-12-27T18:09:54+08:00",
    "timeValid": True,
}


class BroadQueryTests(unittest.TestCase):
    def test_catalog_question_is_broad(self):
        self.assertTrue(is_broad_activity_query("现在都有什么活动"))

    def test_named_coupon_question_is_not_broad(self):
        self.assertFalse(is_broad_activity_query("新人专享券现在好像不能用了"))


class NamedActivityLookupTests(unittest.TestCase):
    def test_offline_rule_found_by_name_returns_status_evidence(self):
        with patch("app.tasks.rag.hybrid_rule_search", return_value=[dict(OFFLINE_COUPON)]):
            hit = _lookup_named_activity("新人专享券使用规则", {}, [])

        self.assertIsNotNone(hit)
        self.assertEqual("offline", hit["publishStatus"])

    def test_activityname_param_takes_priority(self):
        with patch("app.tasks.rag.hybrid_rule_search", return_value=[dict(OFFLINE_COUPON)]) as search:
            hit = _lookup_named_activity("这个券怎么用不了", {"activityName": "新人专享券"}, [])

        self.assertIsNotNone(hit)
        self.assertEqual("新人专享券", search.call_args.args[0])

    def test_published_rule_already_in_strict_results_needs_no_status(self):
        with patch("app.tasks.rag.hybrid_rule_search", return_value=[dict(OFFLINE_COUPON)]):
            hit = _lookup_named_activity("新人专享券使用规则", {}, [dict(OFFLINE_COUPON, publishStatus="published")])

        self.assertIsNone(hit)

    def test_unrelated_titles_do_not_match(self):
        unrelated = dict(OFFLINE_COUPON, id=28, title="白衬衫专场")
        with patch("app.tasks.rag.hybrid_rule_search", return_value=[unrelated]):
            hit = _lookup_named_activity("新人专享券使用规则", {}, [])

        self.assertIsNone(hit)

    def test_generic_word_activity_does_not_match_draft_rule(self):
        # 「现在都有什么活动」被意图改写成「当前所有活动」后，
        # 泛词“活动”不得让草稿规则「待审核活动」被误判为用户点名的活动
        draft = dict(OFFLINE_COUPON, id=30, title="待审核活动",
                     content="学生款商品 8.5 折。", publishStatus="draft")
        with patch("app.tasks.rag.hybrid_rule_search", return_value=[draft]):
            hit = _lookup_named_activity("当前所有活动", {}, [])

        self.assertIsNone(hit)


class StatusAnswerTests(unittest.TestCase):
    def test_offline_answer_names_the_rule_and_does_not_dump_catalog(self):
        answer = _compose_rule_status_answer(OFFLINE_COUPON)

        self.assertIn("新人专享券", answer)
        self.assertIn("已下线", answer)
        self.assertIn("首单满 200 减 30", answer)
        self.assertNotIn("正在生效的活动", answer)

    def test_active_answer_confirms_usable(self):
        answer = _compose_rule_status_answer(dict(OFFLINE_COUPON, publishStatus="published"))

        self.assertIn("正在生效中", answer)
        self.assertIn("首单满 200 减 30", answer)


class ActivityListGateTests(unittest.TestCase):
    def test_named_coupon_status_beats_catalog_list(self):
        state = {"message": "新人专享券现在好像不能用了",
                 "results": [{"type": "rule_query", "ok": True, "data": {
                     "rules": [], "statusNotice": OFFLINE_COUPON, "broad": False}}]}

        answer = _compose_activity_list(state)

        self.assertIn("已下线", answer)

    def test_specific_question_skips_catalog_template(self):
        state = {"message": "新人专享券现在好像不能用了",
                 "results": [{"type": "rule_query", "ok": True, "data": {
                     "rules": [dict(OFFLINE_COUPON, publishStatus="published", title="白衬衫专场")],
                     "broad": False}}]}

        self.assertIsNone(_compose_activity_list(state))

    def test_catalog_question_still_renders_list_even_after_rewritten_query(self):
        # 意图把原话改写成「当前所有活动」也不丢清单语义（broad 标记或原话任一命中即可）
        state = {"message": "现在都有什么活动",
                 "results": [{"type": "rule_query", "ok": True, "data": {
                     "rules": [dict(OFFLINE_COUPON, publishStatus="published")],
                     "broad": False}}]}

        answer = _compose_activity_list(state)

        self.assertIn("1 个正在生效的活动", answer)
        self.assertIn("新人专享券", answer)


if __name__ == "__main__":
    unittest.main()
