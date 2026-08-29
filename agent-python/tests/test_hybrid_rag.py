# -*- coding: utf-8 -*-
import threading
import unittest
from unittest.mock import patch

from app import rag
from app.api import _apply_latest_versions, _build_rule_docs


def hit(doc_id, score, **source):
    return {"_id": str(doc_id), "_score": score, "_source": source}


class RrfFusionTests(unittest.TestCase):
    def setUp(self):
        rag.invalidate_cache()

    def test_document_present_in_both_channels_wins_fusion(self):
        lexical = [hit(1, 8.0, name="lexical-only"), hit(2, 5.0, name="both")]
        vector = [hit(3, 0.91, name="vector-only"), hit(2, 0.85, name="both")]

        fused = rag._rrf_fuse(lexical, vector, size=3)

        self.assertEqual("2", fused[0]["hit"]["_id"])
        self.assertEqual(["bm25", "knn"], fused[0]["retrievalChannels"])
        self.assertEqual({"bm25": 2, "knn": 2}, fused[0]["channelRanks"])

    def test_vector_only_candidates_expand_beyond_bm25_recall(self):
        lexical_response = {"hits": {"hits": [hit(
            1, 7.0, name="关键词商品", embedding=[1, 2, 3], image_url="/1.svg"
        )], "total": {"value": 1}}}
        vector_hits = [hit(
            9, 0.93, name="纯语义商品", embedding=[4, 5, 6], image_url="/9.svg"
        )]
        with patch("app.rag._lexical_search", return_value=lexical_response), \
                patch("app.rag._vector_search", return_value=(vector_hits, "ok")):
            result = rag.hybrid_product_search(keyword="面试穿什么", size=5)

        self.assertEqual("hybrid_rrf", result["retrieval"]["mode"])
        self.assertEqual({1, 9}, {product["id"] for product in result["products"]})
        self.assertFalse(any("embedding" in product for product in result["products"]))
        semantic = next(product for product in result["products"] if product["id"] == 9)
        self.assertEqual(["knn"], semantic["retrievalChannels"])


class DualRecallParallelismTests(unittest.TestCase):
    def test_both_channels_run_concurrently(self):
        # Barrier(2)：两路都到达才放行。若双路退化为串行，先到的一路会等超时报错。
        barrier = threading.Barrier(2, timeout=10)

        def fake_lexical(*args, **kwargs):
            barrier.wait()
            return {"hits": {"hits": [], "total": {"value": 0}}}

        def fake_vector(*args, **kwargs):
            barrier.wait()
            return [], "ok"

        with patch("app.rag._lexical_search", side_effect=fake_lexical), \
                patch("app.rag._vector_search", side_effect=fake_vector):
            lexical, vector_hits, state = rag._dual_recall(
                "product_index", [], [], "通勤", 10)

        self.assertEqual("ok", state)
        self.assertEqual([], vector_hits)
        self.assertEqual(0, lexical["hits"]["total"]["value"])

    def test_lexical_failure_still_propagates(self):
        def broken_lexical(*args, **kwargs):
            raise RuntimeError("es down")

        with patch("app.rag._lexical_search", side_effect=broken_lexical), \
                patch("app.rag._vector_search", return_value=([], "ok")):
            with self.assertRaises(RuntimeError):
                rag._dual_recall("product_index", [], [], "通勤", 10)


class ProductSearchCacheTests(unittest.TestCase):
    def setUp(self):
        rag.invalidate_cache()
        self.es_calls = 0

    def _patch_channels(self, lexical_hits, vector_hits):
        response = {"hits": {"hits": lexical_hits, "total": {"value": len(lexical_hits)}}}

        def fake_lexical(*args, **kwargs):
            self.es_calls += 1
            return response

        def fake_vector(*args, **kwargs):
            self.es_calls += 1
            return list(vector_hits), "ok"

        return patch("app.rag._lexical_search", side_effect=fake_lexical), \
            patch("app.rag._vector_search", side_effect=fake_vector)

    def test_second_identical_search_served_from_cache(self):
        lexical_patch, vector_patch = self._patch_channels(
            [hit(1, 7.0, name="衬衫")], [hit(2, 0.9, name="语义衬衫")])
        with lexical_patch, vector_patch:
            first = rag.hybrid_product_search(keyword="衬衫", size=5)
            second = rag.hybrid_product_search(keyword="衬衫", size=5)

        self.assertEqual(2, self.es_calls)  # 双路各 1 次，第二次请求零 ES 调用
        self.assertEqual([p["id"] for p in first["products"]],
                         [p["id"] for p in second["products"]])
        self.assertEqual(first["retrieval"]["mode"], second["retrieval"]["mode"])

    def test_different_params_get_separate_cache_entries(self):
        lexical_patch, vector_patch = self._patch_channels(
            [hit(1, 7.0, name="衬衫")], [])
        with lexical_patch, vector_patch:
            rag.hybrid_product_search(keyword="衬衫", size=5)
            rag.hybrid_product_search(keyword="外套", size=5)

        self.assertEqual(4, self.es_calls)

    def test_invalidate_cache_forces_new_es_calls(self):
        lexical_patch, vector_patch = self._patch_channels(
            [hit(1, 7.0, name="衬衫")], [])
        with lexical_patch, vector_patch:
            rag.hybrid_product_search(keyword="衬衫", size=5)
            rag.invalidate_cache()
            rag.hybrid_product_search(keyword="衬衫", size=5)

        self.assertEqual(4, self.es_calls)

    def test_caller_mutation_does_not_poison_cached_result(self):
        # 模拟 api 层就地改写返回值（rerank 后覆盖 products、置 reranked=True）
        lexical_patch, vector_patch = self._patch_channels(
            [hit(1, 7.0, name="衬衫")], [hit(2, 0.9, name="语义衬衫")])
        with lexical_patch, vector_patch:
            first = rag.hybrid_product_search(keyword="衬衫", size=5)
            first["reranked"] = True
            first["products"].clear()
            second = rag.hybrid_product_search(keyword="衬衫", size=5)

        self.assertFalse(second.get("reranked", False))
        self.assertEqual([1, 2], [p["id"] for p in second["products"]])


class KnnQueryTests(unittest.TestCase):
    def test_knn_uses_same_business_filters_and_excludes_vector_source(self):
        class RawEs:
            def __init__(self):
                self.body = None

            def search(self, *, index, body):
                self.body = body
                return {"hits": {"hits": []}}

        class FakeEs:
            def __init__(self):
                self.es = RawEs()

            def index_has_vector(self, index):
                return True

            def vector_dims(self, index):
                return 3

            def embed(self, texts):
                return [[0.1, 0.2, 0.3]]

        fake = FakeEs()
        filters = [{"term": {"publish_status": "published"}},
                   {"range": {"effective_to": {"gte": "now"}}}]
        with patch("app.rag.get_es", return_value=fake):
            _, state = rag._vector_search("rule_index", "通勤", filters, 10)

        self.assertEqual("ok", state)
        self.assertEqual({"bool": {"filter": filters}}, fake.es.body["knn"]["filter"])
        self.assertEqual({"excludes": ["embedding"]}, fake.es.body["_source"])


class RuleIndexUpdateTests(unittest.TestCase):
    def test_incremental_documents_receive_embeddings(self):
        class FakeEs:
            def index_has_vector(self, index):
                return True

            def vector_dims(self, index):
                return 3

            def embed(self, texts):
                return [[0.1, 0.2, 0.3] for _ in texts]

        rules = [{
            "id": 1, "title": "通勤规则 v1", "content": "白衬衫配西装裤",
            "type": "outfit", "version": 1, "publishStatus": "published", "tags": "[]",
        }]

        docs, state = _build_rule_docs(FakeEs(), rules)

        self.assertEqual("ok", state)
        self.assertEqual([0.1, 0.2, 0.3], docs[0]["embedding"])

    def test_fullsync_keeps_only_latest_published_family_version(self):
        rules = [
            {"id": 1, "title": "秋季通勤 v1", "version": 1},
            {"id": 2, "title": "秋季通勤 v2", "version": 2},
        ]
        docs = [
            {"title": "秋季通勤 v1", "version": 1, "publish_status": "published"},
            {"title": "秋季通勤 v2", "version": 2, "publish_status": "published"},
        ]

        _apply_latest_versions(rules, docs)

        self.assertEqual("offline", docs[0]["publish_status"])
        self.assertEqual("published", docs[1]["publish_status"])


class MemoryHybridSearchTests(unittest.TestCase):
    def test_memory_search_filters_user_and_active_and_excludes_embedding(self):
        class RawEs:
            def __init__(self):
                self.search_bodies = []

            def search(self, *, index, body):
                self.search_bodies.append(body)
                return {"hits": {"hits": []}}

        class FakeEs:
            def __init__(self):
                self.es = RawEs()

            def index_has_vector(self, index):
                return True

            def vector_dims(self, index):
                return 3

            def embed(self, texts):
                return [[0.1, 0.2, 0.3]]

        fake = FakeEs()
        with patch("app.rag.get_es", return_value=fake):
            memories = rag.hybrid_memory_search("上次买的鞋", user_id=7, size=4,
                                                memory_types=["episode"])

        self.assertEqual([], memories)
        for body in fake.es.search_bodies:
            if "query" in body:  # BM25 路的过滤条件
                filters = body["query"]["bool"]["filter"]
                self.assertIn({"term": {"user_id": "7"}}, filters)
                self.assertIn({"term": {"status": "active"}}, filters)
                self.assertIn({"terms": {"memory_type": ["episode"]}}, filters)
            self.assertEqual({"excludes": ["embedding"]}, body["_source"])


if __name__ == "__main__":
    unittest.main()
