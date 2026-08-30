# -*- coding: utf-8 -*-
"""种子数据：基础账号 + 衣橱 14 件 + 商城商品 200 件 + 规则 40 条（含过期/未来/草稿）。

用法（agent-python venv 内）:
    python ../scripts/seed.py
依赖：MySQL 与 ES 容器已启动；EMBEDDING_MODE 决定是否写入向量。
"""
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(ROOT / "agent-python" / ".env")
load_dotenv()

import pymysql
from init_es import get_es, ensure_indices, PRODUCT_INDEX, RULE_INDEX

IMG_DIR = ROOT / "frontend" / "public" / "seed-images"
IMG_DIR.mkdir(parents=True, exist_ok=True)

MYSQL = dict(
    host="localhost", port=16543, user="root", password="root",
    database="chaoyin", charset="utf8mb4",
)

random.seed(20260827)

# ---------- 配色 / SVG 占位图 ----------
COLOR_HEX = {
    "白色": ("#f5f5f7", "#c9c9cf"), "黑色": ("#3a3a40", "#141416"),
    "浅蓝": ("#dcecfb", "#7fb3e8"), "深蓝": ("#2b4c7e", "#16243e"),
    "藏青": ("#2f3d5c", "#1a2336"), "灰色": ("#c8ccd2", "#6f747d"),
    "卡其": ("#d8c8a8", "#a08b63"), "米色": ("#f0e7d8", "#cbb595"),
    "粉色": ("#fbdbe4", "#e89ab0"), "碎花": ("#fdeff3", "#d98fa8"),
    "墨绿": ("#3d5a4c", "#1f3027"), "酒红": ("#7a2e3a", "#3f171f"),
    "棕色": ("#8b6b4a", "#4f3a26"), "银色": ("#e8eaee", "#9aa1ab"),
    "黄色": ("#f7e9a0", "#d8c25c"), "红色": ("#e25555", "#8f2a2a"),
    "紫色": ("#b8a1d9", "#6d4f96"), "橙色": ("#f0a86b", "#c06a2c"),
    "驼色": ("#c9a884", "#8f6f4e"),
}
CATEGORY_ICON = {
    "top": "👔", "bottom": "👖", "outerwear": "🧥",
    "dress": "👗", "shoes": "👟", "accessory": "👜",
}


def make_svg(text, color_name, tag_text, filename):
    c1, c2 = COLOR_HEX.get(color_name, ("#cccccc", "#888888"))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="600">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
  </linearGradient></defs>
  <rect width="480" height="600" rx="16" fill="url(#g)"/>
  <rect x="20" y="20" width="440" height="560" rx="12" fill="none" stroke="#ffffff88" stroke-width="2"/>
  <text x="240" y="290" font-size="44" text-anchor="middle" fill="#ffffffcc">{tag_text}</text>
  <text x="240" y="350" font-size="30" text-anchor="middle" fill="#ffffff">{text}</text>
</svg>"""
    (IMG_DIR / filename).write_text(svg, encoding="utf-8")
    return f"/seed-images/{filename}"


def person_svg(index, outfit_text):
    palettes = [("#f0c9a8", "#e0a17a"), ("#f7d8c0", "#d99b6c"), ("#e8b48c", "#c98a5e"),
                ("#ffd9b0", "#e0a468"), ("#f2c9a0", "#d49a66"), ("#eec39a", "#c98e5a")]
    c1, c2 = palettes[index % len(palettes)]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="640">
  <rect width="480" height="640" fill="#f2f4f8"/>
  <text x="240" y="80" font-size="28" text-anchor="middle" fill="#667">AI 虚拟换装 · 效果预览</text>
  <circle cx="240" cy="210" r="60" fill="{c1}"/>
  <rect x="180" y="280" width="120" height="200" rx="30" fill="{c2}"/>
  <rect x="160" y="485" width="60" height="120" rx="20" fill="#33415c"/>
  <rect x="260" y="485" width="60" height="120" rx="20" fill="#33415c"/>
  <text x="240" y="580" font-size="26" text-anchor="middle" fill="#333">{outfit_text}</text>
  <text x="240" y="615" font-size="18" text-anchor="middle" fill="#999">mock 生成 · 接入真实模型后替换 provider</text>
</svg>"""
    fname = f"tryon_result_{index}.svg"
    (IMG_DIR / fname).write_text(svg, encoding="utf-8")
    return f"/seed-images/{fname}"


# ---------- 衣橱数据（14 件，标签与商品同构） ----------
WARDROBE = [
    ("白色基础衬衫", "top", "白色", "春秋", "通勤", ["基础款", "百搭", "纯棉"]),
    ("浅蓝条纹衬衫", "top", "浅蓝", "春夏", "通勤", ["条纹", "商务", "修身"]),
    ("黑色高领针织衫", "top", "黑色", "秋冬", "休闲", ["高领", "保暖", "修身"]),
    ("白色印花T恤", "top", "白色", "夏", "休闲", ["印花", "清凉", "宽松"]),
    ("深蓝直筒牛仔裤", "bottom", "深蓝", "春秋", "休闲", ["直筒", "百搭", "显瘦"]),
    ("黑色西装裤", "bottom", "黑色", "春秋", "通勤", ["垂感", "显瘦", "正装"]),
    ("卡其色风衣", "outerwear", "卡其", "春秋", "通勤", ["中长款", "防风", "经典"]),
    ("灰色羊毛大衣", "outerwear", "灰色", "冬", "正式", ["羊毛", "长款", "保暖"]),
    ("藏青西装外套", "outerwear", "藏青", "春秋", "通勤", ["修身", "单排扣"]),
    ("碎花雪纺连衣裙", "dress", "碎花", "夏", "约会", ["碎花", "收腰", "雪纺"]),
    ("白色板鞋", "shoes", "白色", "春夏", "休闲", ["皮质", "百搭", "平底"]),
    ("黑色乐福鞋", "shoes", "黑色", "春秋", "通勤", ["平底", "英伦", "百搭"]),
    ("棕色托特包", "accessory", "棕色", "四季", "通勤", ["大容量", "牛皮", "手提"]),
    ("银色锁骨链", "accessory", "银色", "四季", "约会", ["锁骨链", "简约", "银饰"]),
]

# ---------- 商品生成 ----------
PRODUCT_TEMPLATES = [
    # (品类, 名称词, 颜色池, 季节池, 风格池, 价格区间)
    ("top", "衬衫", ["白色", "浅蓝", "黑色", "粉色"], ["春秋"], ["通勤", "正式"], (99, 199)),
    ("top", "T恤", ["白色", "黑色", "灰色"], ["夏"], ["休闲", "运动"], (59, 129)),
    ("top", "针织衫", ["米色", "墨绿", "酒红", "灰色"], ["秋冬"], ["休闲", "约会"], (129, 259)),
    ("top", "卫衣", ["灰色", "黑色", "藏青"], ["秋冬"], ["休闲", "运动"], (99, 219)),
    ("top", "Polo衫", ["白色", "藏青", "浅蓝"], ["夏"], ["休闲", "通勤"], (89, 169)),
    ("top", "雪纺衫", ["白色", "粉色", "浅蓝"], ["春夏"], ["约会", "通勤"], (79, 159)),
    ("bottom", "牛仔裤", ["深蓝", "浅蓝", "黑色"], ["春秋"], ["休闲"], (119, 269)),
    ("bottom", "西装裤", ["黑色", "灰色", "藏青"], ["春秋"], ["通勤", "正式"], (129, 259)),
    ("bottom", "休闲裤", ["卡其", "米色", "墨绿"], ["春秋"], ["休闲"], (99, 199)),
    ("bottom", "半身裙", ["黑色", "卡其", "碎花"], ["春夏", "秋冬"], ["约会", "通勤"], (89, 189)),
    ("bottom", "阔腿裤", ["黑色", "米色", "酒红"], ["春秋"], ["通勤", "约会"], (109, 229)),
    ("outerwear", "西装外套", ["藏青", "黑色", "灰色"], ["春秋"], ["通勤", "正式"], (299, 599)),
    ("outerwear", "风衣", ["卡其", "米色", "墨绿"], ["春秋"], ["通勤"], (259, 499)),
    ("outerwear", "牛仔夹克", ["浅蓝", "深蓝"], ["春秋"], ["休闲"], (159, 329)),
    ("outerwear", "羽绒服", ["黑色", "白色", "酒红"], ["冬"], ["休闲"], (299, 899)),
    ("outerwear", "毛呢大衣", ["驼色", "灰色", "黑色"], ["冬"], ["正式", "通勤"], (399, 899)),
    ("outerwear", "针织开衫", ["米色", "粉色", "灰色"], ["春秋"], ["约会", "休闲"], (139, 279)),
    ("dress", "连衣裙", ["碎花", "黑色", "白色", "粉色"], ["夏"], ["约会"], (139, 399)),
    ("dress", "衬衫裙", ["白色", "浅蓝", "卡其"], ["春夏"], ["通勤"], (129, 299)),
    ("dress", "吊带裙", ["黑色", "酒红", "墨绿"], ["夏"], ["约会"], (89, 219)),
    ("shoes", "小白鞋", ["白色"], ["春夏"], ["休闲"], (99, 199)),
    ("shoes", "乐福鞋", ["黑色", "棕色"], ["春秋"], ["通勤"], (139, 299)),
    ("shoes", "切尔西靴", ["黑色", "棕色"], ["秋冬"], ["休闲", "通勤"], (169, 399)),
    ("shoes", "高跟鞋", ["黑色", "米色", "红色"], ["四季"], ["约会", "正式"], (159, 499)),
    ("shoes", "运动鞋", ["白色", "灰色", "黑色"], ["四季"], ["运动"], (129, 399)),
    ("shoes", "帆布鞋", ["白色", "黄色", "藏青"], ["春夏"], ["休闲"], (69, 149)),
    ("accessory", "单肩包", ["黑色", "棕色", "酒红"], ["四季"], ["通勤", "约会"], (99, 299)),
    ("accessory", "托特包", ["棕色", "米色", "黑色"], ["四季"], ["通勤"], (89, 399)),
    ("accessory", "围巾", ["灰色", "卡其", "酒红"], ["秋冬"], ["休闲"], (39, 129)),
    ("accessory", "腰带", ["黑色", "棕色"], ["四季"], ["通勤"], (49, 149)),
    ("accessory", "渔夫帽", ["米色", "黑色", "卡其"], ["春夏"], ["休闲"], (39, 99)),
    ("accessory", "手表", ["银色", "黑色", "棕色"], ["四季"], ["通勤", "正式"], (199, 899)),
]

CATEGORY_CN = {"top": "上装", "bottom": "下装", "outerwear": "外套",
               "dress": "连衣裙", "shoes": "鞋履", "accessory": "配饰"}


def gen_products(n=200):
    products = []
    tpl_index = 0
    # 固定第一件：用于验证商品搜索的"白色衬衫"
    products.append({
        "name": "白色衬衫·通勤款", "category": "top", "color": "白色",
        "season": "春秋", "style": "通勤", "tags": ["基础款", "百搭", "纯棉", "免烫"],
        "price": 159.0, "stock": 120, "sales": 3400,
        "detail": "纯棉免烫白色衬衫，通勤基础款，修身剪裁，四季百搭。",
    })
    while len(products) < n:
        cat, noun, colors, seasons, styles, (lo, hi) = PRODUCT_TEMPLATES[tpl_index % len(PRODUCT_TEMPLATES)]
        tpl_index += 1
        color = random.choice(colors)
        season = random.choice(seasons)
        style = random.choice(styles)
        name = f"{color}{noun}·{style}款"
        price = round(random.randint(lo, hi) + random.random(), 2)
        if random.random() < 0.15:
            price = round(price * random.choice([0.75, 0.85]), 2)  # 折扣款
        products.append({
            "name": name, "category": cat, "color": color,
            "season": season, "style": style,
            "tags": [CATEGORY_CN[cat], style, "当季新品"],
            "price": price, "stock": random.randint(5, 200),
            "sales": random.randint(0, 5000),
            "detail": f"{name}，{season}款{style}风格，{CATEGORY_CN[cat]}类目，支持 7 天无理由退换。",
        })
    return products[:n]


# ---------- 规则（版本/时间窗/状态） ----------
NOW = datetime.now()

def dt(days_offset):  # 相对今天
    return NOW + timedelta(days=days_offset)


def es_dt(s: str):
    """MySQL DATETIME(空格格式) → ES date 字段(ISO8601 带时区)。"""
    return (s.replace(" ", "T") + "+08:00") if s else None

OUTFIT_RULES = [
    ("通勤标配", ["通勤", "衬衫", "西装裤", "乐福鞋"], "白衬衫 + 西装裤 + 乐福鞋，干练利落，日常办公不出错。"),
    ("秋季通勤叠穿", ["秋", "通勤", "针织开衫", "衬衫"], "衬衫外搭针织开衫 + 直筒裤，层次感强且保暖。"),
    ("约会小心机", ["约会", "连衣裙", "高跟鞋", "项链"], "小黑裙 + 高跟鞋 + 锁骨链，优雅显气质。"),
    ("周末休闲", ["休闲", "T恤", "牛仔裤", "小白鞋"], "T恤 + 牛仔裤 + 小白鞋，经典不出错。"),
    ("商务正式", ["正式", "西装", "衬衫", "西裤"], "藏青西装 + 白衬衫 + 西裤，面试会议首选。"),
    ("冬季保暖", ["冬", "大衣", "围巾", "高领"], "高领针织衫 + 毛呢大衣 + 围巾，暖而不臃肿。"),
    ("风衣叠穿", ["春秋", "风衣", "T恤", "牛仔裤"], "风衣 + T恤 + 牛仔裤，春秋街头感。"),
    ("同色系法则", ["同色系", "显瘦"], "上下装同色系深浅搭配，视觉显高显瘦。"),
    ("撞色点缀", ["撞色", "配饰"], "基础色穿搭 + 亮色包/鞋点缀，点睛之笔。"),
    ("牛仔双搭", ["牛仔", "休闲", "牛仔夹克"], "牛仔夹克 + 深色牛仔裤，注意深浅错开。"),
    ("裙装通勤", ["通勤", "衬衫裙", "乐福鞋"], "衬衫裙 + 乐福鞋，通勤优雅两相宜。"),
    ("运动风", ["运动", "卫衣", "运动鞋"], "卫衣 + 运动鞋 + 棒球帽，活力出街。"),
    ("半身裙秋搭", ["秋", "半身裙", "针织衫", "切尔西靴"], "针织衫 + 半身裙 + 切尔西靴，温柔秋日。"),
    ("阔腿裤显瘦", ["阔腿裤", "显瘦"], "短款上衣 + 高腰阔腿裤，拉长腿部比例。"),
    ("腰带法则", ["腰带", "连衣裙", "收腰"], "连衣裙配细腰带，收腰提升比例。"),
    ("西装套装", ["正式", "西装"], "同色西装外套 + 西裤，气场全开。"),
    ("大衣内搭", ["冬", "大衣", "高领"], "大衣 + 高领打底，简约高级。"),
    ("白T万能", ["T恤", "百搭"], "白T + 任意下装，衣橱万能单品。"),
    ("牛仔裤通勤", ["通勤", "牛仔裤", "衬衫"], "深色牛仔裤 + 衬衫，smart casual 风格。"),
    ("春夏碎花", ["春夏", "碎花", "连衣裙", "小白鞋"], "碎花裙 + 小白鞋，清新减龄。"),
    ("秋冬靴子", ["秋冬", "切尔西靴", "显瘦"], "切尔西靴 + 九分裤，利落显瘦。"),
    ("配饰点睛", ["配饰", "质感", "手表"], "纯色穿搭 + 金属手表/项链，提升质感。"),
    ("卫衣裙叠穿", ["休闲", "卫衣"], "长款卫衣 + 打底裤，街头慵懒风。"),
    ("西装混搭", ["混搭", "西装", "牛仔裤", "T恤"], "西装外套 + T恤 + 牛仔裤，平衡正式与休闲。"),
    ("配色禁忌", ["配色"], "全身不超过三个主色，保持清爽。"),
]

ACTIVITY_RULES = [
    # (标题, tags, 内容, from_offset, to_offset, 状态)
    ("新人专享券", ["新人", "优惠券", "满减"], "首单满 200 减 30，全场通用。", -60, 120, "published"),
    ("秋季通勤焕新季 v2", ["秋", "通勤", "折扣"], "通勤风格商品 9 折，叠加店铺券。", -7, 24, "published"),
    ("白衬衫专场", ["衬衫", "白色", "折扣"], "白衬衫类目第二件半价。", -2, 4, "published"),
    ("开学季", ["开学季", "学生", "折扣"], "学生款商品 8.5 折，凭学生证。", -2, 14, "published"),
    ("周末闪购", ["闪购", "周末", "折扣"], "每周六日全场限时 9 折。", -26, 34, "published"),
    ("会员升级礼", ["会员", "积分"], "累计满 1000 元升级金卡，赠 50 元券。", -26, 35, "published"),
    ("老客回馈", ["满减", "老客"], "老用户满 500 减 80。", -12, 19, "published"),
    ("鞋履节", ["鞋", "折扣"], "鞋履类目满两件 8 折。", -7, 4, "published"),
    ("品牌周", ["品牌", "折扣"], "指定品牌 7 折，限时抢购。", -5, 1, "published"),
    # 已过期（时间窗失效，不应被召回）
    ("会员日", ["会员", "积分"], "每月 8 日全场积分双倍。", -19, -17, "published"),
    ("夏日清仓", ["夏", "清仓", "折扣"], "夏装 3 折起，售完即止。", -88, -27, "published"),
    ("七夕约会穿搭", ["七夕", "约会", "裙装"], "裙装 + 配饰组合 8 折。", -15, -11, "published"),
    # 未来生效（未到生效时间，不应被召回）
    ("国庆出游季", ["国庆", "出游", "满减"], "出游装备满 300 减 50。", 32, 40, "published"),
    ("双十一预售", ["双十一", "预售"], "定金膨胀，11 月全场狂欢。", 54, 76, "published"),
    ("冬装预售", ["冬", "预售", "羽绒服"], "羽绒服/大衣预售减 100。", 14, 34, "published"),
    # 草稿（未发布，不应被召回）
    ("测试活动-勿发布", ["测试"], "仅用于验证发布状态过滤。", -5, 30, "draft"),
    ("待审核活动", ["待审核"], "尚未走完审核流程。", -1, 20, "draft"),
]


def build_rules():
    rules = []
    rid = 1
    for title, tags, content in OUTFIT_RULES:
        rules.append({
            "id": rid, "type": "outfit", "title": title, "content": content,
            "tags": tags, "version": 1,
            "effective_from": dt(-30).strftime("%Y-%m-%d %H:%M:%S"),
            "effective_to": dt(365).strftime("%Y-%m-%d %H:%M:%S"),
            "publish_status": "published", "source": "穿搭师团队",
        })
        rid += 1
    for i, (title, tags, content, f, t, status) in enumerate(ACTIVITY_RULES):
        version = 2 if "v2" in title else 1
        rules.append({
            "id": rid, "type": "activity", "title": title, "content": content,
            "tags": tags, "version": version,
            "effective_from": dt(f).strftime("%Y-%m-%d %H:%M:%S"),
            "effective_to": dt(t).strftime("%Y-%m-%d %H:%M:%S"),
            "publish_status": status, "source": "运营平台",
        })
        rid += 1
    # 秋季通勤焕新季 v1（同族旧版本，已过期）——用于验证版本治理
    rules.append({
        "id": rid, "type": "activity", "title": "秋季通勤焕新季",
        "content": "通勤风格商品 95 折（旧版，已被 v2 替代）。",
        "tags": ["秋", "通勤", "折扣"], "version": 1,
        "effective_from": dt(-200).strftime("%Y-%m-%d %H:%M:%S"),
        "effective_to": dt(-30).strftime("%Y-%m-%d %H:%M:%S"),
        "publish_status": "published", "source": "运营平台",
    })
    rid += 1
    # 新版 v2 草稿，用于验证发布流程
    rules.append({
        "id": rid, "type": "activity", "title": "秋季通勤焕新季 v3",
        "content": "通勤风格商品 85 折 + 满 300 减 60（v3 待发布）。",
        "tags": ["秋", "通勤", "折扣"], "version": 3,
        "effective_from": dt(0).strftime("%Y-%m-%d %H:%M:%S"),
        "effective_to": dt(30).strftime("%Y-%m-%d %H:%M:%S"),
        "publish_status": "draft", "source": "运营平台",
    })
    return rules


# ---------- Embedding ----------
def make_embedder():
    mode = os.getenv("EMBEDDING_MODE", "none")
    if mode == "none":
        return None
    if mode == "ollama":
        import httpx
        model = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
        url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        print(f"[embed] using ollama model={model}")

        def embed_ollama(texts):
            r = httpx.post(f"{url}/api/embed", json={"model": model, "input": texts}, timeout=120)
            r.raise_for_status()
            return r.json()["embeddings"]

        return embed_ollama
    if mode == "api":
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL"),
                api_key=os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or "none",
            )
            model = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
            print(f"[embed] using api model={model}")
            return lambda texts: [r.embedding for r in
                                  client.embeddings.create(model=model, input=texts).data]
        except Exception as e:
            print(f"[embed] api unavailable: {e}; fallback to no-vector")
            return None
    print("[embed] unknown mode, fallback to no-vector")
    return None


# ---------- 主流程 ----------
def has_existing_business_data() -> bool:
    """启动脚本使用：核心业务表已有数据时禁止自动重置聊天、订单和用户数据。"""
    try:
        conn = pymysql.connect(**MYSQL)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT (SELECT COUNT(*) FROM product), (SELECT COUNT(*) FROM rule)")
                product_count, rule_count = cur.fetchone()
                return int(product_count or 0) > 0 and int(rule_count or 0) > 0
        finally:
            conn.close()
    except Exception as error:
        print(f"[seed] 检查现有数据失败，将按首次初始化处理: {error}")
        return False


def seed_mysql(products, rules):
    conn = pymysql.connect(**MYSQL)
    try:
        with conn.cursor() as cur:
            # 兼容已经创建过数据卷的开发环境：docker-entrypoint-initdb 只在首次启动执行。
            cur.execute("""
                CREATE TABLE IF NOT EXISTS after_sale (
                  id BIGINT AUTO_INCREMENT PRIMARY KEY,
                  request_no VARCHAR(32) NOT NULL UNIQUE,
                  order_id BIGINT NOT NULL,
                  user_id BIGINT NOT NULL,
                  type VARCHAR(24) NOT NULL,
                  status VARCHAR(16) NOT NULL DEFAULT 'pending',
                  reason VARCHAR(255),
                  amount DECIMAL(10,2) NOT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  INDEX idx_user (user_id), INDEX idx_order (order_id)
                ) ENGINE=InnoDB
            """)
            cur.execute("DELETE FROM after_sale")
            cur.execute("DELETE FROM order_item")
            cur.execute("DELETE FROM orders")
            cur.execute("DELETE FROM favorite")
            cur.execute("DELETE FROM wardrobe_item")
            cur.execute("DELETE FROM rule")
            cur.execute("DELETE FROM product")
            cur.execute("DELETE FROM chat_message")
            cur.execute("DELETE FROM chat_session")
            cur.execute("DELETE FROM tryon_task")
            cur.execute("DELETE FROM user_auth_token")
            cur.execute("DELETE FROM `user`")
            # 重置自增，保证 DB id 与 ES _id 一致（1..N）
            for t in ["wardrobe_item", "product", "rule", "orders", "order_item", "favorite", "after_sale"]:
                cur.execute(f"ALTER TABLE {t} AUTO_INCREMENT = 1")
            cur.execute(
                "INSERT INTO `user` (id, username, password, nickname) VALUES (1, 'user', 'user123', '用户')")

            # 衣橱
            for i, (name, cat, color, season, style, tags) in enumerate(WARDROBE, 1):
                img = make_svg(name[:4], color, CATEGORY_ICON[cat], f"wardrobe_{i}.svg")
                cur.execute(
                    "INSERT INTO wardrobe_item (user_id, name, image_url, category, color, season, style, tags, note, source) "
                    "VALUES (1, %s, %s, %s, %s, %s, %s, %s, 'seed 示例单品', 'upload')",
                    (name, img, cat, color, season, style, json.dumps(tags, ensure_ascii=False)))

            # 商品
            product_ids = []
            for i, p in enumerate(products, 1):
                img = make_svg(p["name"][:4], p["color"], CATEGORY_ICON[p["category"]], f"product_{i}.svg")
                cur.execute(
                    "INSERT INTO product (name, image_url, category, color, season, style, tags, price, stock, status, sales, detail) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
                    (p["name"], img, p["category"], p["color"], p["season"], p["style"],
                     json.dumps(p["tags"], ensure_ascii=False), p["price"], p["stock"], p["sales"], p["detail"]))
                product_ids.append(cur.lastrowid)

            # 规则
            for r in rules:
                cur.execute(
                    "INSERT INTO rule (id, type, title, content, tags, version, effective_from, effective_to, publish_status, source) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (r["id"], r["type"], r["title"], r["content"],
                     json.dumps(r["tags"], ensure_ascii=False), r["version"],
                     r["effective_from"], r["effective_to"], r["publish_status"], r["source"]))

            # 收藏与订单基础数据
            for pid in [product_ids[0], product_ids[6], product_ids[10]]:
                cur.execute("INSERT INTO favorite (user_id, product_id) VALUES (1, %s)", (pid,))
            cur.execute(
                "INSERT INTO orders (order_no, user_id, total_amount, status, receiver_name, receiver_phone, receiver_address, logistics_no) "
                "VALUES ('CY202608150001', 1, 398.00, 'shipped', '小潮', '13800000000', '上海市徐汇区漕河泾', 'SF1234567890')")
            cur.execute(
                "INSERT INTO orders (order_no, user_id, total_amount, status, receiver_name, receiver_phone, receiver_address) "
                "VALUES ('CY202608260002', 1, 159.00, 'pending', '小潮', '13800000000', '上海市徐汇区漕河泾')")
            conn.commit()
        print(f"[seed] mysql done: wardrobe={len(WARDROBE)} products={len(products)} rules={len(rules)}")
    finally:
        conn.close()
    return product_ids


def seed_es(products, product_ids, rules, embedder):
    es = get_es()
    # 探测 embedding 可用性：模型未就绪/服务不可达 → 本次不建向量索引（降级 BM25）
    if embedder is not None:
        try:
            embedder(["探测"])
        except Exception as e:
            print(f"[embed] 探测失败，本次跳过向量索引（稍后拉取模型并重跑 seed 即可补向量）: {e}")
            embedder = None
    with_vector = embedder is not None
    ensure_indices(es, with_vector)

    def bulk_docs(index, docs):
        from elasticsearch.helpers import bulk
        actions = [{"_index": index, "_id": d.pop("_id"), "_source": d} for d in docs]
        ok, errors = bulk(es, actions, raise_on_error=False)
        print(f"[seed] es {index}: ok={ok} errors={len(errors)}")
        if errors:
            print("   sample error:", str(errors[0])[:300])

    # 商品文档：_id 用 MySQL 实际主键，保证与商城/订单数据一致
    docs = []
    for i, p in enumerate(products, 1):
        d = {"_id": product_ids[i - 1], "name": p["name"], "detail": p["detail"],
             "category": p["category"], "color": p["color"], "season": p["season"],
             "style": p["style"], "tags": p["tags"], "price": p["price"],
             "stock": p["stock"], "sales": p["sales"], "status": 1,
             "image_url": f"/seed-images/product_{i}.svg"}
        docs.append(d)
    if embedder:
        texts = [d["name"] + " " + d["detail"] for d in docs]
        vecs = []
        try:
            for i in range(0, len(texts), 32):
                vecs.extend(embedder(texts[i:i + 32]))
                print(f"[embed] products {min(i + 32, len(texts))}/{len(texts)}")
            for d, v in zip(docs, vecs):
                d["embedding"] = v
        except Exception as e:
            print(f"[embed] 向量化失败，降级为无向量索引（稍后可重跑 seed 补向量）: {e}")
    bulk_docs(PRODUCT_INDEX, docs)

    # 规则文档
    docs = []
    for r in rules:
        d = {"_id": r["id"], "title": r["title"], "content": r["content"],
             "type": r["type"], "tags": r["tags"], "version": r["version"],
             "publish_status": r["publish_status"],
             "effective_from": es_dt(r["effective_from"]), "effective_to": es_dt(r["effective_to"]),
             "source": r["source"]}
        docs.append(d)
    if embedder:
        texts = [d["title"] + " " + d["content"] for d in docs]
        vecs = []
        try:
            for i in range(0, len(texts), 32):
                vecs.extend(embedder(texts[i:i + 32]))
            for d, v in zip(docs, vecs):
                d["embedding"] = v
        except Exception as e:
            print(f"[embed] 规则向量化失败，降级为无向量索引: {e}")
    bulk_docs(RULE_INDEX, docs)

    # 换装结果占位图
    outfits = ["白衬衫·通勤套装", "风衣叠穿·街拍", "小黑裙·约会", "西装·商务", "卫衣·运动", "大衣·冬日"]
    for i, t in enumerate(outfits):
        person_svg(i, t)
    print(f"[seed] es done, tryon presets={len(outfits)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="初始化本地数据；默认执行显式重置。")
    parser.add_argument(
        "--if-empty", action="store_true",
        help="仅在商品/规则表为空时初始化；一键启动必须使用该选项以保护订单和聊天记录",
    )
    args = parser.parse_args()
    if args.if_empty and has_existing_business_data():
        print("[seed] 已存在商品和规则数据，跳过重置；聊天、订单和会话记忆均保留。")
        raise SystemExit(0)
    products = gen_products(200)
    rules = build_rules()
    product_ids = seed_mysql(products, rules)
    embedder = make_embedder()
    seed_es(products, product_ids, rules, embedder)
    print("[seed] all done. 初始账号 user / user123")
