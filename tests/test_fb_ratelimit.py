import asyncio

from app.web.routes_auth_facebook import _RateLimiter


def test_ratelimiter_ttl():
    async def _run():
        r = _RateLimiter(max_hits=2, ttl_seconds=60)
        assert await r.hit("k") is True
        assert await r.hit("k") is True
        assert await r.hit("k") is False
    asyncio.run(_run())
