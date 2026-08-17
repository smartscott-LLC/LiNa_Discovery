"""Voice pool + provider tests: fallback chain, semaphore, env factory."""
import asyncio
import os
import sys

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

from providers import VoicePool, VoicePoolError, build_voice_pool_from_env
from providers.base import AIProvider
from providers.openai_compat import OpenAICompatProvider

from typing import cast

import httpx

results = []

def check(name, fn):
    try:
        fn()
        results.append((name, "OK"))
    except Exception as e:
        results.append((name, f"FAIL: {type(e).__name__}: {e}"))
        import traceback
        traceback.print_exc()


class FakeProvider(AIProvider):
    def __init__(self, name, responses=None, fail=False):
        self.name = name
        self.label = name
        self.responses = list(responses) if responses else []
        self.calls = 0
        self.fail = fail
        self.closed = False
    async def generate(self, system, messages, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} exploded")
        return self.responses.pop(0) if self.responses else f"{self.name}:ok"
    async def aclose(self):
        self.closed = True


def test_fallback_chain():
    async def run():
        primary = FakeProvider("deepseek", fail=True)
        backup = FakeProvider("openrouter")
        pool = VoicePool([primary, backup], max_concurrent=2)
        text = await pool.generate("sys", [{"role": "user", "content": "hi"}])
        assert text == "openrouter:ok"
        assert primary.calls == 1 and backup.calls == 1
        await pool.aclose()
        assert backup.closed
    asyncio.run(run())


def test_all_fail_raises():
    async def run():
        pool = VoicePool([FakeProvider("a", fail=True), FakeProvider("b", fail=True)])
        try:
            await pool.generate("", [])
            raise AssertionError("should have raised")
        except VoicePoolError as e:
            assert "all voice providers failed" in str(e)
    asyncio.run(run())


def test_empty_pool():
    async def run():
        pool = VoicePool([])
        try:
            await pool.generate("", [])
            raise AssertionError("should have raised")
        except VoicePoolError as e:
            assert "no voice providers configured" in str(e)
    asyncio.run(run())


def test_semaphore_bounds_concurrency():
    async def run():
        active = 0
        peak = 0
        class SlowProvider(FakeProvider):
            async def generate(self, system, messages, **kwargs):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.05)
                active -= 1
                return "ok"
        pool = VoicePool([SlowProvider("slow")], max_concurrent=2)
        await asyncio.gather(*[pool.generate("", []) for _ in range(8)])
        assert peak <= 2, f"peak concurrency {peak} > 2"
    asyncio.run(run())


def test_primary_is_first():
    async def run():
        pool = VoicePool([FakeProvider("a"), FakeProvider("b")])
        primary = pool.primary
        assert primary is not None and primary.name == "a"
        assert pool.names == ["a", "b"]
        assert bool(pool)
    asyncio.run(run())


def test_factory_env_chain():
    os.environ["SILICON_FLOW_API_KEY"] = "k-siliconflow"
    os.environ["HUGGING_FACE_ACCESS_TOKEN"] = "k-huggingface"
    os.environ.pop("AI_PROVIDERS", None)

    async def run():
        pool = build_voice_pool_from_env(primary="siliconflow", max_concurrent=3)
        # siliconflow + huggingface have keys; local is always
        # available — her voice lives on her own machine now.
        assert pool.names == ["siliconflow", "local", "huggingface"], pool.names
        assert pool.max_concurrent == 3
    asyncio.run(run())


def test_factory_chain_override():
    os.environ["AI_PROVIDERS"] = "huggingface,siliconflow"
    async def run():
        pool = build_voice_pool_from_env(primary="siliconflow")
        assert pool.names == ["huggingface", "siliconflow"], pool.names
    asyncio.run(run())
    os.environ.pop("AI_PROVIDERS", None)


def test_factory_no_keys_empty():
    for var in ("SILICON_FLOW_API_KEY", "HUGGING_FACE_ACCESS_TOKEN"):
        os.environ.pop(var, None)
    os.environ.pop("AI_PROVIDERS", None)
    async def run():
        pool = build_voice_pool_from_env(primary="siliconflow")
        # The cloud providers need keys; the local instrument does not —
        # she always has her own voice on this machine.
        assert pool.names == ["local"], pool.names
    asyncio.run(run())


def test_openai_compat_request_shape():
    class StubResponse:
        def __init__(self, status_code=200, body=None):
            self.status_code = status_code
            self._body = body or {"choices": [{"message": {"content": "stub answer"}}]}
            self.text = str(body) if status_code >= 400 else "ok"
        def json(self):
            return self._body
    captured = {}
    class StubClient:
        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return StubResponse()
        async def aclose(self):
            pass
    async def run():
        provider = OpenAICompatProvider(
            base_url="https://example.com/v1", api_key="k", model="m", name="test"
        )
        provider._client = cast(httpx.AsyncClient, StubClient())
        text = await provider.generate("sys", [{"role": "user", "content": "q"}], max_tokens=42)
        assert text == "stub answer"
        assert captured["url"] == "/chat/completions"
        assert captured["json"]["model"] == "m"
        assert captured["json"]["max_tokens"] == 42
        assert captured["json"]["messages"][0] == {"role": "system", "content": "sys"}
        assert captured["json"]["messages"][1] == {"role": "user", "content": "q"}
    asyncio.run(run())


class ChunkProvider(FakeProvider):
    """A provider that truly streams — pieces, not one assembled answer."""
    async def generate_stream(self, system, messages, **kwargs):
        if self.fail:
            raise RuntimeError(f"{self.name} exploded")
        for piece in self.responses:
            yield piece


def test_generate_stream_default_yields_once():
    async def run():
        pool = VoicePool([FakeProvider("a", responses=["whole answer"])])
        chunks = [c async for c in pool.generate_stream("", [])]
        assert chunks == ["whole answer"]
    asyncio.run(run())


def test_generate_stream_fallback_before_first_chunk():
    async def run():
        primary = ChunkProvider("deepseek", responses=["partial"], fail=True)
        backup = ChunkProvider("openrouter", responses=["hello", " world"])
        pool = VoicePool([primary, backup])
        chunks = [c async for c in pool.generate_stream("", [])]
        assert chunks == ["hello", " world"]
    asyncio.run(run())


def test_generate_stream_mid_stream_failure_surfaces():
    class MidFailProvider(ChunkProvider):
        async def generate_stream(self, system, messages, **kwargs):
            yield "first"
            raise RuntimeError(f"{self.name} died mid-word")
    async def run():
        pool = VoicePool([MidFailProvider("a"), ChunkProvider("b", responses=["never used"])])
        try:
            chunks = [c async for c in pool.generate_stream("", [])]
            raise AssertionError(f"should have raised, got {chunks}")
        except VoicePoolError as e:
            assert "mid-stream" in str(e)


def test_empty_stream_falls_back():
    # A provider that answers with nothing (empty 200 — the wedge that
    # silently delivered empty responses) is a failure: the next instrument
    # carries her words instead of delivering silence.
    async def run():
        primary = ChunkProvider("local", responses=[])
        backup = ChunkProvider("openrouter", responses=["hello", " world"])
        pool = VoicePool([primary, backup])
        chunks = [c async for c in pool.generate_stream("", [])]
        assert chunks == ["hello", " world"]
    asyncio.run(run())


def test_empty_completion_falls_back():
    # The non-stream path has the same rule: whitespace is not a voice.
    class EmptyProvider(FakeProvider):
        async def generate(self, system, messages, **kwargs):
            self.calls += 1
            return "   "
    async def run():
        pool = VoicePool([EmptyProvider("local"), FakeProvider("openrouter")])
        text = await pool.generate("", [])
        assert text == "openrouter:ok"
    asyncio.run(run())


def test_all_empty_raises():
    # Every provider silent → an honest VoicePoolError, never a blank page.
    class EmptyProvider(FakeProvider):
        async def generate(self, system, messages, **kwargs):
            return ""
    async def run():
        pool = VoicePool([EmptyProvider("a"), EmptyProvider("b")])
        try:
            await pool.generate("", [])
            raise AssertionError("should have raised")
        except VoicePoolError as e:
            assert "empty" in str(e)
    asyncio.run(run())
    asyncio.run(run())


def test_openai_compat_http_error():
    class StubResponse:
        def __init__(self):
            self.status_code = 429
            self.text = "rate limited"
    class StubClient:
        async def post(self, url, json=None):
            return StubResponse()
        async def aclose(self):
            pass
    async def run():
        provider = OpenAICompatProvider(
            base_url="https://example.com/v1", api_key="k", model="m", name="test"
        )
        provider._client = cast(httpx.AsyncClient, StubClient())
        try:
            await provider.generate("", [])
            raise AssertionError("should have raised")
        except Exception as e:
            assert "429" in str(e)
    asyncio.run(run())


if __name__ == "__main__":
    check("fallback chain", test_fallback_chain)
    check("all fail raises", test_all_fail_raises)
    check("empty pool", test_empty_pool)
    check("semaphore bounds", test_semaphore_bounds_concurrency)
    check("primary is first", test_primary_is_first)
    check("factory env chain", test_factory_env_chain)
    check("factory chain override", test_factory_chain_override)
    check("factory no keys empty", test_factory_no_keys_empty)
    check("openai compat request shape", test_openai_compat_request_shape)
    check("openai compat http error", test_openai_compat_http_error)

    print("=" * 60)
    ok = True
    for name, status in results:
        print(f"[{status}] {name}")
        if not status.startswith("OK"):
            ok = False
    print("=" * 60)
    print("ALL PROVIDER TESTS PASS" if ok else "FAILURES PRESENT")
