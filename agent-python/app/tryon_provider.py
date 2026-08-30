# -*- coding: utf-8 -*-
"""可插拔虚拟试衣 HTTP 供应商适配器。

供应商 POST 接口可以同步返回 ``resultUrl``，也可以返回 ``taskId`` 和可选
``statusUrl``。异步任务会轮询状态地址，并识别 progress/status/resultUrl/error
这些通用字段；外层 ``data`` 会自动解包。具体供应商只需在网关层把原始协议适配成
这一小组稳定字段，不把厂商 SDK 泄漏到 Agent 编排里。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from . import config

ProgressCallback = Callable[[str, int], Awaitable[None]]


class TryonProviderError(RuntimeError):
    pass


def _data(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("data")
    return nested if isinstance(nested, dict) else payload


def _result_url(payload: dict) -> str:
    return str(payload.get("resultUrl") or payload.get("result_url") or payload.get("url") or "")


async def generate(payload: dict, on_progress: ProgressCallback) -> dict:
    """提交并等待一次真实虚拟试衣任务，返回统一结果结构。"""
    if config.TRYON_MODE != "http":
        raise TryonProviderError(f"不支持的 TRYON_MODE: {config.TRYON_MODE}")
    if not config.TRYON_PROVIDER_URL:
        raise TryonProviderError("TRYON_MODE=http 但未配置 TRYON_PROVIDER_URL")

    headers = {"Accept": "application/json"}
    if config.TRYON_PROVIDER_API_KEY:
        headers["Authorization"] = f"Bearer {config.TRYON_PROVIDER_API_KEY}"

    timeout = httpx.Timeout(config.TRYON_PROVIDER_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        response = await client.post(config.TRYON_PROVIDER_URL, json=payload)
        response.raise_for_status()
        body = _data(response.json())
        await on_progress("生图服务已接收任务", 15)

        direct_url = _result_url(body)
        if direct_url:
            await on_progress("渲染完成", 100)
            return {"url": direct_url, "providerTaskId": body.get("taskId"), "rawStatus": "done"}

        provider_task_id = body.get("taskId") or body.get("id")
        status_url = body.get("statusUrl") or body.get("status_url")
        if not status_url and provider_task_id:
            status_url = f"{config.TRYON_PROVIDER_URL.rstrip('/')}/{provider_task_id}"
        if not status_url:
            raise TryonProviderError("生图服务未返回 resultUrl、taskId 或 statusUrl")

        deadline = time.monotonic() + config.TRYON_POLL_TIMEOUT
        last_percent = 15
        while time.monotonic() < deadline:
            await asyncio.sleep(max(config.TRYON_POLL_INTERVAL, 0.1))
            status_response = await client.get(str(status_url))
            status_response.raise_for_status()
            status_body = _data(status_response.json())
            status = str(status_body.get("status") or "processing").lower()
            try:
                percent = int(status_body.get("progress", last_percent))
            except (TypeError, ValueError):
                percent = last_percent
            percent = min(99, max(last_percent, percent))
            last_percent = percent
            await on_progress(str(status_body.get("stage") or "模型生成中"), percent)

            result_url = _result_url(status_body)
            if result_url or status in {"done", "completed", "success", "succeeded"}:
                if not result_url:
                    raise TryonProviderError("生图任务已完成，但结果中没有 resultUrl")
                await on_progress("渲染完成", 100)
                return {"url": result_url, "providerTaskId": provider_task_id, "rawStatus": status}
            if status in {"failed", "error", "cancelled", "canceled"}:
                message = status_body.get("error") or status_body.get("errorMsg") or status
                raise TryonProviderError(f"生图任务失败: {message}")

    raise TryonProviderError(f"等待生图结果超时（{config.TRYON_POLL_TIMEOUT:g}s）")
