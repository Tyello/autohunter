import asyncio

from app.integrations.facebook.ratelimit import TTLRateLimiter


def test_ratelimiter_returns_429_style_limit_signal():
    async def _run():
        r = TTLRateLimiter(max_hits=2, ttl_seconds=60)
        assert await r.hit("k") is True
        assert await r.hit("k") is True
        assert await r.hit("k") is False

    asyncio.run(_run())
