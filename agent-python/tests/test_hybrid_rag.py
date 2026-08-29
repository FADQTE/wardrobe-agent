# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from app import rag
from app.api import _apply_latest_versions, _build_rule_docs


def hit(doc_id, score, **source):
    return {"_id": str(doc_id), "_score": score, "_source": source}


class RrfFusionTests(unittest.TestCase):
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
