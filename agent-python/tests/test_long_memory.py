# -*- coding: utf-8 -*-
"""长期记忆管线测试：写入门控/白名单/置信度分级 + 读取路由/渲染。"""
import unittest

from app import long_memory as lm


class GateTests(unittest.TestCase):
    def test_transactional_message_never_triggers_extraction(self):
        self.assertFalse(lm.should_extract("帮我查一下订单"))
        self.assertFalse(lm.should_extract("物流到哪了"))
        self.assertFalse(lm.should_extract("你好"))
        self.assertFalse(lm.should_extract(""))

    def test_preference_and_size_messages_trigger_extraction(self):
        self.assertTrue(lm.should_extract("我平时上装都穿 L"))
        self.assertTrue(lm.should_extract("以后推荐不要黑色"))
        self.assertTrue(lm.should_extract("给我爸买件外套，预算 500 以内"))
        self.assertTrue(lm.should_extract("我身高178 体重72公斤"))


class NormalizeTests(unittest.TestCase):
    def test_whitelist_outer_predicate_is_dropped(self):
        out = lm.normalize_candidates([{
            "memory_type": "semantic", "predicate": "favorite_food", "value": "火锅",
            "source": "user_explicit", "confidence": 1.0, "importance": 0.9,
        }])
        self.assertEqual([], out)

    def test_inference_confidence_capped_and_low_value_episode_dropped(self):
        out = lm.normalize_candidates([
            {"memory_type": "profile", "predicate": "preferred_color", "value": "黑色",
             "source": "agent_inference", "confidence": 0.95, "importance": 0.6},
            {"memory_type": "episode", "predicate": "buy_gift", "value": "围巾",
             "source": "user_behavior", "confidence": 0.7, "importance": 0.3},
        ])
        self.assertEqual(1, len(out))
        self.assertEqual(0.7, out[0]["confidence"])  # 推断不得冒充确定事实
        self.assertEqual("profile", out[0]["memory_type"])

    def test_duplicate_predicate_keeps_highest_confidence(self):
        out = lm.normalize_candidates([
            {"memory_type": "semantic", "predicate": "size_top", "value": "L",
             "source": "user_behavior", "confidence": 0.6, "importance": 0.6},
            {"memory_type": "semantic", "predicate": "size_top", "value": "L",
             "source": "user_explicit", "confidence": 1.0, "importance": 0.8},
        ])
        self.assertEqual(1, len(out))
        self.assertEqual("user_explicit", out[0]["source"])
        self.assertEqual(1.0, out[0]["confidence"])

    def test_scope_defaults_to_user_person(self):
        out = lm.normalize_candidates([{
            "memory_type": "semantic", "predicate": "size_shoes", "value": "42",
            "source": "user_explicit", "confidence": 1.0, "importance": 0.8,
        }])
        self.assertEqual({"person": "user"}, out[0]["scope"])

    def test_invalid_source_or_type_rejected(self):
        out = lm.normalize_candidates([
            {"memory_type": "semantic", "predicate": "size_top", "value": "L",
             "source": "model_guess", "confidence": 1.0, "importance": 0.8},
            {"memory_type": "short_term", "predicate": "size_top", "value": "L",
             "source": "user_explicit", "confidence": 1.0, "importance": 0.8},
        ])
        self.assertEqual([], out)


class ReadPathTests(unittest.TestCase):
    def test_episodic_recall_only_for_history_questions(self):
        self.assertTrue(lm.wants_episodic_recall("我上次买的那件外套叫什么？"))
        self.assertTrue(lm.wants_episodic_recall("之前给你们反馈过质量问题"))
        self.assertFalse(lm.wants_episodic_recall("推荐一件通勤外套"))
        self.assertFalse(lm.wants_episodic_recall(""))

    def test_render_facts_marks_non_explicit_sources(self):
        rendered = lm.render_facts([
            {"predicate": "size_top", "value": "\"L\"", "sourceType": "user_explicit"},
            {"predicate": "preferred_color", "value": "\"黑色\"", "sourceType": "agent_inference"},
            {"predicate": "budget", "value": "{\"min\":0,\"max\":1000}", "sourceType": "user_explicit"},
        ])
        self.assertIn("size_top=L", rendered)
        self.assertIn("preferred_color=黑色（推断）", rendered)
        budget = rendered.split("budget=")[1]
        self.assertIn('"min": 0', budget)
        self.assertIn('"max": 1000', budget)

    def test_render_facts_empty_is_blank(self):
        self.assertEqual("", lm.render_facts([]))

    def test_render_episodes_truncates_and_dates(self):
        rendered = lm.render_episodes([
            {"content": "用户曾为父亲挑选外套，预算 500 元。" + "长" * 200,
             "createdAt": "2026-08-29T10:00:00+08:00"},
        ])
        self.assertTrue(rendered.startswith("- 用户曾为父亲挑选外套"))
        self.assertIn("2026-08-29", rendered)


if __name__ == "__main__":
    unittest.main()
