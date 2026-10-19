"""Key-management API.

Create, list, inspect and revoke API keys. Gated behind an admin key
(``LUNAIR_ADMIN_KEY``): when it is unset the endpoints are disabled entirely,
so a deployment cannot accidentally expose key management.

Plaintext keys are returned exactly once, at creation. Only the SHA-256 digest
is stored.
"""

import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from lunair.config import settings
from lunair.core.trust import hash_key
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import APIKey

keys_api = APIRouter(prefix="/v1/keys", tags=["keys"])


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    rpm_limit: int = Field(default=60, ge=0)
    tpm_limit: int = Field(default=100000, ge=0)
    monthly_budget_usd: float = Field(default=50.0, ge=0)


class UpdateKeyRequest(BaseModel):
    name: Optional[str] = None
    rpm_limit: Optional[int] = Field(default=None, ge=0)
    tpm_limit: Optional[int] = Field(default=None, ge=0)
    monthly_budget_usd: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


def _require_admin(x_admin_key: Optional[str]) -> None:
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=404,
            detail="Key management is disabled. Set LUNAIR_ADMIN_KEY to enable it.",
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing admin key")


def _serialize(key: APIKey) -> Dict[str, Any]:
    return {
        "id": key.id,
        "name": key.name,
        "rpm_limit": key.rpm_limit,
        "tpm_limit": key.tpm_limit,
        "monthly_budget_usd": key.monthly_budget_usd,
        "is_active": key.is_active,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


@keys_api.post("", status_code=201)
async def create_key(
    body: CreateKeyRequest,
    x_admin_key: Optional[str] = Header(None, alias="X-LUNAIR-Admin-Key"),
) -> Dict[str, Any]:
    _require_admin(x_admin_key)

    plaintext = "lunair_" + secrets.token_urlsafe(32)
    key = APIKey(
        key_hash=hash_key(plaintext),
        name=body.name,
        rpm_limit=body.rpm_limit,
        tpm_limit=body.tpm_limit,
        monthly_budget_usd=body.monthly_budget_usd,
    )
    async with AsyncSessionLocal() as session:
        session.add(key)
        await session.commit()
        await session.refresh(key)

    payload = _serialize(key)
    # The plaintext is shown once and never persisted.
    payload["key"] = plaintext
    return payload


@keys_api.get("")
async def list_keys(
    x_admin_key: Optional[str] = Header(None, alias="X-LUNAIR-Admin-Key"),
) -> Dict[str, Any]:
    _require_admin(x_admin_key)
    async with AsyncSessionLocal() as session:
        rows: List[APIKey] = (await session.execute(select(APIKey).order_by(APIKey.created_at.desc()))).scalars().all()
    return {"object": "list", "data": [_serialize(k) for k in rows]}


@keys_api.patch("/{key_id}")
async def update_key(
    key_id: str,
    body: UpdateKeyRequest,
    x_admin_key: Optional[str] = Header(None, alias="X-LUNAIR-Admin-Key"),
) -> Dict[str, Any]:
    _require_admin(x_admin_key)
    async with AsyncSessionLocal() as session:
        key = (await session.execute(select(APIKey).where(APIKey.id == key_id))).scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=404, detail="key not found")
        for field in ("name", "rpm_limit", "tpm_limit", "monthly_budget_usd", "is_active"):
            value = getattr(body, field)
            if value is not None:
                setattr(key, field, value)
        key.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(key)
    return _serialize(key)


@keys_api.delete("/{key_id}")
async def revoke_key(
    key_id: str,
    x_admin_key: Optional[str] = Header(None, alias="X-LUNAIR-Admin-Key"),
) -> Dict[str, Any]:
    _require_admin(x_admin_key)
    async with AsyncSessionLocal() as session:
        key = (await session.execute(select(APIKey).where(APIKey.id == key_id))).scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=404, detail="key not found")
        key.is_active = False
        await session.commit()
    return {"id": key_id, "is_active": False}
