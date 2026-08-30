# -*- coding: utf-8 -*-
"""本地 Reranker：Qwen3-Reranker-0.6B（Ollama 不支持 rerank，代码内直接部署）。

Qwen3-Reranker 的评分方式是 LogitScore：基座 Qwen3 CausalLM + 指令模板，
取末位位置 yes/no 两个 token 的 logit 做 softmax，P(yes) 即相关分数
（true/false token id 在权重目录的 1_LogitScore/config.json 中）。

- 权重从 ModelScope 下载到 RERANK_MODEL_DIR（D 盘），首次自动拉取；
  失败自动降级为 ES 原始排序，不影响主链路。
- CPU 批量推理（query+doc 成对一次前向）。
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from . import config

INSTRUCT = ("<Instruct>: Given a web search query, retrieve relevant passages that answer the query\n"
            "<Query>: {query}\n"
            "<Document>: {doc}")

_model = None
_true_id, _false_id = 9693, 2152
_lock = threading.Lock()
_state = "idle"  # idle | loading | ready | failed


def _ensure_model_dir(model_id: str) -> str | None:
    """定位/下载 reranker 权重（ModelScope 目录规则：模型名中的 . 变为 ___），失败返回 None。"""
    base = Path(config.RERANK_MODEL_DIR)
    org, name = (model_id.split("/") + ["", ""])[:2]
    name_safe = name.replace(".", "___")
    candidates = [
        base / model_id.replace("/", "--").replace(".", "___"),
        base / org / name_safe,
        base / f"{org}___{name_safe}",
    ]

    def _valid(d: Path) -> bool:
        return d.is_dir() and (d / "config.json").exists() and list(d.glob("*.safetensors"))

    for cand in candidates:
        if _valid(cand):
            return str(cand)
    for d in base.rglob(f"*{name_safe}*"):
        if _valid(d) and "._____temp" not in str(d):
            return str(d)
    try:
        from modelscope import snapshot_download
        path = snapshot_download(model_id, cache_dir=str(base))
        if _valid(Path(path)):
            return str(path)
        # ModelScope 会把真实文件放到 org___name 子目录
        for d in Path(path).rglob("*.safetensors"):
            if _valid(d.parent):
                return str(d.parent)
        return str(path)
    except Exception as e:
        print(f"[rerank] model download failed ({model_id}): {e}", flush=True)
        return None


def _load() -> bool:
    global _model, _state, _true_id, _false_id
    if _state == "ready":
        return True
    if _state in ("loading", "failed"):
        return _state == "ready"
    with _lock:
        if _state in ("ready", "loading"):
            return _state == "ready"
        _state = "loading"
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            path = _ensure_model_dir(config.RERANK_MODEL)
            if not path:
                _state = "failed"
                return False
            print(f"[rerank] loading {config.RERANK_MODEL} from {path} ...", flush=True)
            tokenizer = AutoTokenizer.from_pretrained(path)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            model = AutoModelForCausalLM.from_pretrained(path)
            model.eval()
            # LogitScore 的 yes/no token id（1_LogitScore/config.json）
            score_cfg = Path(path) / "1_LogitScore" / "config.json"
            if score_cfg.exists():
                sc = json.loads(score_cfg.read_text(encoding="utf-8"))
                _true_id = int(sc.get("true_token_id", _true_id))
                _false_id = int(sc.get("false_token_id", _false_id))
            _model = (tokenizer, model)
            _state = "ready"
            print(f"[rerank] ready (logit-score yes={_true_id} no={_false_id})", flush=True)
            return True
        except Exception as e:
            print(f"[rerank] load failed: {e}", flush=True)
            _state = "failed"
            return False


def rerank_sync(query: str, docs: list[dict], top_k: int = 6) -> list[dict]:
    """同步重排：docs 需含 text 字段；返回带 rerank_score 的排序结果（≥阈值）。"""
    if not config.RERANK_ENABLED or not docs or len(docs) < 2:
        for d in docs:
            d.setdefault("rerankScore", None)
        return docs
    if not _load():
        for d in docs:
            d.setdefault("rerankScore", None)
        return docs
    try:
        import torch
        tokenizer, model = _model
        texts = [INSTRUCT.format(query=query, doc=(d.get("text") or d.get("name") or "")) for d in docs]
        inputs = tokenizer(texts, padding=True, truncation=True, max_length=1024, return_tensors="pt")
        with torch.no_grad():
            logits = model(**inputs).logits
        # 每个样本取最后一个非 pad 位置，计算 yes/no 的 softmax
        last_idx = inputs["attention_mask"].sum(dim=1) - 1
        batch_idx = torch.arange(len(docs))
        pair = torch.stack([logits[batch_idx, last_idx, _true_id],
                            logits[batch_idx, last_idx, _false_id]], dim=-1)
        scores = torch.softmax(pair.float(), dim=-1)[:, 0].tolist()
        for d, s in zip(docs, scores):
            d["rerankScore"] = round(s, 4)
        ranked = [d for d in docs if (d["rerankScore"] or 0) >= config.RERANK_THRESHOLD]
        if not ranked:
            ranked = [max(docs, key=lambda d: d["rerankScore"] or 0)]
            ranked[0]["rerankLowConfidence"] = True
        ranked.sort(key=lambda d: d["rerankScore"] or 0, reverse=True)
        return ranked[:top_k]
    except Exception as e:
        print(f"[rerank] inference failed: {e}", flush=True)
        for d in docs:
            d.setdefault("rerankScore", None)
        return docs


async def rerank(query: str, docs: list[dict], top_k: int = 6) -> list[dict]:
    """异步包装：CPU 推理放线程池，不阻塞事件循环。"""
    if not config.RERANK_ENABLED or not docs:
        return docs
    return await asyncio.to_thread(rerank_sync, query, docs, top_k)


def status() -> str:
    return _state
