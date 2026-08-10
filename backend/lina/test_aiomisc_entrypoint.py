"""aiomisc lifecycle smoke test — services start and stop cleanly.

Runs the real entrypoint with VoicePoolService + IPCBridgeService (the
LINAIdentityService needs PostgreSQL, so it is exercised separately below
via create_application()).
"""
import asyncio
import os
import sys

os.environ["DEEPSEEK_API_KEY"] = "k-test"
os.environ["LINA_FORESIGHT_TIMEOUT_SECONDS"] = "0.3"

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

import aiomisc  # noqa: E402

results = []

def check(name, fn):
    try:
        fn()
        results.append((name, "OK"))
    except Exception as e:
        results.append((name, f"FAIL: {type(e).__name__}: {e}"))
        import traceback; traceback.print_exc()


def test_entrypoint_start_stop():
    import lina_service

    # Self-contained env: exactly one provider, regardless of ambient keys.
    os.environ["DEEPSEEK_API_KEY"] = "k-test"
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("AI_PROVIDERS", None)

    async def smoke():
        services = [
            lina_service.VoicePoolService(default_provider="deepseek"),
            lina_service.IPCBridgeService(),
        ]
        async with aiomisc.entrypoint(*services) as ep:
            await asyncio.sleep(0.5)

            # Services published their resources for the FastAPI app.
            assert lina_service._voice_pool is not None
            assert lina_service._voice_pool.primary.name == "deepseek", \
                lina_service._voice_pool.names
            assert lina_service._bridge_service is not None
            assert lina_service._bridge_service.bridge is not None
            assert lina_service._bridge_service.bridge.available()

            # The voice pool is usable through the published reference.
            from providers import VoicePool
            assert isinstance(lina_service._voice_pool, VoicePool)

        # After exit: pool closed and unpublished, bridge reset.
        assert lina_service._voice_pool is None, "voice pool must be unpublished on stop"
        assert lina_service._bridge_service is None, "bridge service must be unpublished on stop"

    asyncio.run(smoke())


def test_lina_identity_service_application():
    import lina_service

    svc = lina_service.LINAIdentityService(host="127.0.0.1", port=8999)
    app = asyncio.run(svc.create_application())
    assert app is lina_service.app, "create_application must return the FastAPI app"
    paths = {r.path for r in app.routes}
    assert "/lina/chat" in paths and "/lina/season/advance/{user_id}" in paths
    assert "/lina/ipc/status" in paths


def test_voice_pool_service_env_driven():
    import lina_service

    # Deterministic: only these two keys exist for this test.
    os.environ["DEEPSEEK_API_KEY"] = "k-test"
    os.environ["OPENROUTER_API_KEY"] = "k-test"
    for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(var, None)
    os.environ.pop("AI_PROVIDERS", None)

    svc = lina_service.VoicePoolService(default_provider="openrouter", max_concurrent=7)
    asyncio.run(svc.start())
    try:
        assert lina_service._voice_pool is not None
        assert lina_service._voice_pool.names == ["openrouter", "deepseek"], \
            lina_service._voice_pool.names
        assert lina_service._voice_pool.max_concurrent == 7
    finally:
        asyncio.run(svc.stop())
        assert lina_service._voice_pool is None


if __name__ == "__main__":
    check("entrypoint start/stop", test_entrypoint_start_stop)
    check("LINAIdentityService application", test_lina_identity_service_application)
    check("VoicePoolService env-driven", test_voice_pool_service_env_driven)

    print("=" * 60)
    ok = True
    for name, status in results:
        print(f"[{status}] {name}")
        if not status.startswith("OK"):
            ok = False
    print("=" * 60)
    print("ALL AIOMISC TESTS PASS" if ok else "FAILURES PRESENT")
