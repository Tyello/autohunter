import asyncio

from app.integrations.facebook.guards import FBUserLock


def test_concurrent_lock_only_one_acquires():
    lock = FBUserLock()
    started = asyncio.Event()

    async def slow():
        async with lock.acquire("u1") as acquired:
            assert acquired is True
            started.set()
            await asyncio.sleep(0.05)

    async def fast():
        await started.wait()
        async with lock.acquire("u1") as acquired:
            return acquired

    async def run():
        t1 = asyncio.create_task(slow())
        t2 = asyncio.create_task(fast())
        got = await t2
        await t1
        return got

    acquired = asyncio.run(run())
    assert acquired is False
