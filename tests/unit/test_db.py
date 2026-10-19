import pytest
from sqlalchemy import select
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import APIKey


@pytest.mark.asyncio
async def test_db_connection_and_models():
    async with AsyncSessionLocal() as session:
        # Query APIKey
        result = await session.execute(select(APIKey))
        assert result.scalars().all() is not None

        # Insert a test API key
        key = APIKey(
            key_hash="test_hash_123",
            name="Test Key",
            rpm_limit=60,
            tpm_limit=100000,
            monthly_budget_usd=50.0,
        )
        session.add(key)
        await session.commit()

        # Query back
        result = await session.execute(select(APIKey).where(APIKey.key_hash == "test_hash_123"))
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.name == "Test Key"

        # Cleanup
        await session.delete(found)
        await session.commit()
