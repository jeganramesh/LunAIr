import asyncio

import pytest


@pytest.fixture(autouse=True)
def dispose_db_engine():
    """Keep asyncpg connections from leaking across per-test event loops.

    ``lunair.db.base.engine`` is created once at import time. pytest-asyncio
    gives every test a fresh event loop, so a pooled connection opened in an
    earlier loop is unusable ("attached to a different loop"). Disposing the
    engine after each test forces the next loop to open fresh connections.
    """
    yield

    engine = _get_engine()
    if engine is None:
        return

    async def _dispose():
        await engine.dispose()

    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_closed():
            return
        loop.run_until_complete(_dispose())
    except RuntimeError:
        pass
    finally:
        engine.sync_engine.dispose()


def _get_engine():
    try:
        from lunair.db.base import engine
    except Exception:
        return None
    return engine