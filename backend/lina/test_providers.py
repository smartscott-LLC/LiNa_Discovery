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
    os.environ["DEEPSEEK_API_KEY"] = "k-deepseek"
    os.environ["OPENROUTER_API_KEY"] = "k-openrouter"
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("AI_PROVIDERS", None)

    async def run():
        pool = build_voice_pool_from_env(primary="deepseek", max_concurrent=3)
        # deepseek + openrouter have keys; gemini skipped
        assert pool.names == ["deepseek", "openrouter"], pool.names
        assert pool.max_concurrent == 3
    asyncio.run(run())


def test_factory_chain_override():
    os.environ["AI_PROVIDERS"] = "openrouter,deepseek"
    async def run():
        pool = build_voice_pool_from_env(primary="deepseek")
        assert pool.names == ["openrouter", "deepseek"], pool.names
    asyncio.run(run())
    os.environ.pop("AI_PROVIDERS", None)


def test_factory_no_keys_empty():
    for var in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    os.environ.pop("AI_PROVIDERS", None)
    async def run():
        pool = build_voice_pool_from_env(primary="deepseek")
        assert pool.names == [], pool.names
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
