from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import threading
import time

import httpx
from PIL import Image

import invoice_ocr.api as api
from invoice_ocr.models import OCRLine


def png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    return stream.getvalue()


def recognized_lines() -> list[OCRLine]:
    return [
        OCRLine(text="电子发票（普通发票）", score=0.98, box=(0, 0, 500, 18)),
        OCRLine(text="开票日期 2026-07-14", score=0.98, box=(0, 20, 500, 38)),
        OCRLine(text="发票号码 00123456789012345678", score=0.98, box=(0, 40, 500, 58)),
        OCRLine(text="合计（不含税） ￥100.00", score=0.98, box=(0, 60, 500, 78)),
        OCRLine(text="合计税额 ￥6.00", score=0.98, box=(0, 80, 500, 98)),
        OCRLine(text="价税合计 ￥106.00", score=0.98, box=(0, 100, 500, 118)),
    ]


def reset_engine() -> None:
    reset = getattr(api, "reset_engine", None)
    if reset is not None:
        reset()
    else:
        api.get_engine.cache_clear()


def test_ocr_work_does_not_block_health_on_the_event_loop(monkeypatch):
    engine_started = threading.Event()
    release_engine = threading.Event()
    health_timing: dict[str, object] = {}

    class SlowEngine:
        def recognize(self, _image_path: Path):
            engine_started.set()
            assert release_engine.wait(timeout=2)
            return recognized_lines()

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", SlowEngine)

    async def scenario():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            loop = asyncio.get_running_loop()

            def request_health_from_thread():
                assert engine_started.wait(timeout=1)
                submitted = time.perf_counter()
                future = asyncio.run_coroutine_threadsafe(client.get("/health"), loop)
                health_timing["response"] = future.result(timeout=2)
                health_timing["elapsed"] = time.perf_counter() - submitted

            requester = threading.Thread(target=request_health_from_thread)
            requester.start()
            release_timer = threading.Timer(0.75, release_engine.set)
            release_timer.start()
            try:
                ocr_response = await client.post(
                    "/v1/recognize",
                    files={"file": ("invoice.png", png_bytes(), "image/png")},
                )
                await asyncio.to_thread(requester.join, 2)
            finally:
                release_engine.set()
                release_timer.cancel()
                requester.join(timeout=2)
            return ocr_response

    ocr_response = asyncio.run(scenario())
    reset_engine()

    assert ocr_response.status_code == 200
    assert health_timing["response"].status_code == 200
    assert health_timing["elapsed"] < 0.4


def test_concurrent_cold_start_constructs_exactly_one_engine(monkeypatch):
    constructors = 0
    constructors_lock = threading.Lock()
    callers_ready = threading.Barrier(8)

    class CountingEngine:
        def __init__(self):
            nonlocal constructors
            with constructors_lock:
                constructors += 1
            time.sleep(0.1)

    def resolve_engine():
        callers_ready.wait(timeout=2)
        return api.get_engine()

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", CountingEngine)
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            engines = list(executor.map(lambda _index: resolve_engine(), range(8)))
    finally:
        reset_engine()

    assert constructors == 1
    assert all(engine is engines[0] for engine in engines)


def test_shared_engine_recognition_is_serialized_without_blocking_event_loop(monkeypatch):
    active = 0
    maximum_active = 0
    active_lock = threading.Lock()

    class ObservingEngine:
        def recognize(self, _image_path: Path):
            nonlocal active, maximum_active
            with active_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.1)
            with active_lock:
                active -= 1
            return recognized_lines()

    reset_engine()
    monkeypatch.setattr(api, "PaddleOCREngine", ObservingEngine)

    async def scenario():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first, second = await asyncio.gather(
                client.post(
                    "/v1/recognize",
                    files={"file": ("first.png", png_bytes(), "image/png")},
                ),
                client.post(
                    "/v1/recognize",
                    files={"file": ("second.png", png_bytes(), "image/png")},
                ),
            )
            return first, second

    first, second = asyncio.run(scenario())
    reset_engine()

    assert first.status_code == 200
    assert second.status_code == 200
    assert maximum_active == 1
