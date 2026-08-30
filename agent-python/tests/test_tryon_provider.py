# -*- coding: utf-8 -*-
"""虚拟试衣回归：HTTP 供应商适配器契约 + 执行中进度事件即时推送（不等节点结束）。"""
import unittest
from unittest.mock import patch

import httpx

from app import config, tasks, tryon_provider


def _install_transport(handler):
    """给所有 httpx.AsyncClient 注入 MockTransport（含 tasks 里对 Java API 的调用）。"""
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return original(*args, **kwargs)

    return patch.object(httpx, "AsyncClient", factory)


async def _collect_progress(progress):
    async def on_progress(stage, percent):
        progress.append((stage, percent))
    return on_progress


class _MemoryStub:
    def __init__(self):
        self.state = {"clarify_count": 0}


class TryonProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_result_url_returns_immediately(self):
        progress = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual("/generate", request.url.path)
            return httpx.Response(200, json={"data": {"resultUrl": "https://img/x.png", "taskId": "t9"}})

        with patch.object(config, "TRYON_MODE", "http"), \
                patch.object(config, "TRYON_PROVIDER_URL", "https://provider.example/generate"), \
                _install_transport(handler):
            result = await tryon_provider.generate(
                {"label": "通勤"}, await _collect_progress(progress))

        self.assertEqual("https://img/x.png", result["url"])
        self.assertEqual("t9", result["providerTaskId"])
        self.assertEqual("done", result["rawStatus"])
        self.assertEqual([("生图服务已接收任务", 15), ("渲染完成", 100)], progress)

    async def test_async_task_polls_status_until_done(self):
        progress = []
        polls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/generate":
                return httpx.Response(200, json={"taskId": "t-1"})
            polls["count"] += 1
            if polls["count"] == 1:
                return httpx.Response(200, json={
                    "status": "processing", "progress": 40, "stage": "模型生成中"})
            return httpx.Response(200, json={"status": "completed", "resultUrl": "https://img/done.png"})

        with patch.object(config, "TRYON_MODE", "http"), \
                patch.object(config, "TRYON_PROVIDER_URL", "https://provider.example/generate"), \
                patch.object(config, "TRYON_POLL_INTERVAL", 0.01), \
                _install_transport(handler):
            result = await tryon_provider.generate({}, await _collect_progress(progress))

        self.assertEqual("https://img/done.png", result["url"])
        self.assertEqual("t-1", result["providerTaskId"])
        self.assertIn(("模型生成中", 40), progress)
        self.assertEqual(("渲染完成", 100), progress[-1])

    async def test_failed_status_raises_provider_error(self):
        progress = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/generate":
                return httpx.Response(200, json={"taskId": "t-2"})
            return httpx.Response(200, json={"status": "failed", "error": "GPU 显存不足"})

        with patch.object(config, "TRYON_MODE", "http"), \
                patch.object(config, "TRYON_PROVIDER_URL", "https://provider.example/generate"), \
                patch.object(config, "TRYON_POLL_INTERVAL", 0.01), \
                _install_transport(handler):
            with self.assertRaisesRegex(tryon_provider.TryonProviderError, "生图任务失败: GPU 显存不足"):
                await tryon_provider.generate({}, await _collect_progress(progress))

    async def test_http_mode_without_provider_url_is_rejected(self):
        with patch.object(config, "TRYON_MODE", "http"), \
                patch.object(config, "TRYON_PROVIDER_URL", ""):
            with self.assertRaisesRegex(tryon_provider.TryonProviderError, "未配置 TRYON_PROVIDER_URL"):
                await tryon_provider.generate({}, await _collect_progress([]))


class DoImageLiveProgressTests(unittest.IsolatedAsyncioTestCase):
    def _java_handler(self, http_fail=False):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/tryon"):
                return httpx.Response(200, json={"code": 0, "data": {"id": 77}})
            if path.endswith("/status"):
                return httpx.Response(200, json={"code": 0})
            if path.endswith("/generate"):
                return httpx.Response(500) if http_fail else httpx.Response(
                    200, json={"resultUrl": "https://img/real.png"})
            return httpx.Response(404)
        return handler

    async def test_mock_tryon_emits_progress_live_before_node_ends(self):
        live = []

        async def sink(ev):
            live.append(ev)

        task = {"id": "t1", "type": "image", "params": {"label": "白衬衫通勤", "garmentIds": [3]}}
        with patch.object(config, "TRYON_MODE", "mock"), \
                _install_transport(self._java_handler()):
            result = await tasks.do_image(task, [], _MemoryStub(),
                                          {"session_id": "s1", "user_id": 1, "event_sink": sink})

        self.assertTrue(result["ok"])
        # 进度事件在任务仍在执行时就已到达 event_sink（而非等节点结束批量返回）
        self.assertEqual([20, 45, 75, 100], [ev["data"]["percent"] for ev in live])
        self.assertTrue(all(ev["type"] == "image_progress" and ev["data"]["taskId"] == 77
                            and ev["data"]["provider"] == "mock" for ev in live))
        # 同一批事件保留在最终状态里供 Trace/评测，且带 _liveEmitted 去重标记
        deferred = [ev for ev in result["events"] if ev["type"] == "image_progress"]
        self.assertEqual(4, len(deferred))
        self.assertTrue(all(ev.get("_liveEmitted") for ev in deferred))
        image_events = [ev for ev in result["events"] if ev["type"] == "image"]
        self.assertEqual(1, len(image_events))
        self.assertTrue(image_events[0]["data"]["url"].startswith("/seed-images/"))

    async def test_http_tryon_success_reports_provider_result(self):
        live = []

        async def sink(ev):
            live.append(ev)

        task = {"id": "t2", "type": "image", "params": {"label": "约会小黑裙"}}
        with patch.object(config, "TRYON_MODE", "http"), \
                patch.object(config, "TRYON_PROVIDER_URL", "https://provider.example/generate"), \
                _install_transport(self._java_handler()):
            result = await tasks.do_image(task, [], _MemoryStub(),
                                          {"session_id": "s1", "user_id": 1, "event_sink": sink})

        self.assertTrue(result["ok"])
        self.assertEqual("https://img/real.png", result["data"]["url"])
        self.assertEqual("http", result["data"]["provider"])
        self.assertIn(("生图服务已接收任务", 15), [(ev["data"]["stage"], ev["data"]["percent"]) for ev in live])
        tool_events = [ev for ev in result["events"] if ev["type"] == "tool"]
        self.assertTrue(any(ev["data"]["name"] == "http_tryon" and ev["data"]["ok"] for ev in tool_events))

    async def test_http_tryon_failure_marks_task_failed_without_retry(self):
        status_calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/status"):
                status_calls.append(request)
                import json as _json
                body = _json.loads(request.content)
                if body.get("status") == "failed":
                    return httpx.Response(200, json={"code": 0})
            return self._java_handler(http_fail=True)(request)

        task = {"id": "t3", "type": "image", "params": {"label": "街拍风衣"}}
        with patch.object(config, "TRYON_MODE", "http"), \
                patch.object(config, "TRYON_PROVIDER_URL", "https://provider.example/generate"), \
                _install_transport(handler):
            result = await tasks.do_image(task, [], _MemoryStub(),
                                          {"session_id": "s1", "user_id": 1, "event_sink": None})

        self.assertFalse(result["ok"])
        self.assertEqual(77, result["data"]["taskId"])
        failed_updates = [r for r in status_calls]
        self.assertEqual(1, len(failed_updates))
        import json as _json
        self.assertEqual("failed", _json.loads(failed_updates[0].content)["status"])
        self.assertIn("500", _json.loads(failed_updates[0].content)["errorMsg"])
        error_events = [ev for ev in result["events"]
                        if ev["type"] == "tool" and ev["data"]["name"] == "http_tryon"]
        self.assertEqual(1, len(error_events))
        self.assertFalse(error_events[0]["data"]["ok"])


if __name__ == "__main__":
    unittest.main()
