import asyncio

from app.integrations.facebook.ratelimit import TTLRateLimiter


def test_ratelimiter_429_condition():
    async def _run():
        limiter = TTLRateLimiter(max_hits=2, ttl_seconds=60)
        assert await limiter.hit("ip:1") is True
        assert await limiter.hit("ip:1") is True
        assert await limiter.hit("ip:1") is False

    asyncio.run(_run())
