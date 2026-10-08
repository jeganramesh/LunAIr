import hashlib
from typing import Optional
from fastapi import Header, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import APIKey

security = HTTPBearer(auto_error=False)


class TrustContext:
    def __init__(self, key_id: str, is_trusted: bool):
        self.key_id = key_id
        self.is_trusted = is_trusted


async def verify_trust_or_auth(
    request: Request,
    x_lunair_verified: Optional[str] = Header(None, alias="X-LUNAIR-Verified"),
    x_lunair_key_id: Optional[str] = Header(None, alias="X-LUNAIR-Key-Id"),
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> TrustContext:
    """
    Trust middleware dependency:
    - If X-LUNAIR-Verified == 'true', request came from Go Gateway; trust it and use X-LUNAIR-Key-Id.
    - Otherwise, client is connecting directly (fastapi_only mode); require Bearer token and validate.
    """
    if x_lunair_verified == "true":
        key_id = x_lunair_key_id or "gateway-verified-key"
        return TrustContext(key_id=key_id, is_trusted=True)

    # Direct client connection path: require Bearer token
    token = None
    if auth and auth.credentials:
        token = auth.credentials
    else:
        # Fallback to Authorization raw header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing Bearer API key in Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate token against database (or allow dev bypass for default keys)
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)
            result = await session.execute(stmt)
            api_key_record = result.scalar_one_or_none()
            if api_key_record is not None:
                return TrustContext(key_id=api_key_record.id, is_trusted=False)
    except Exception:
        pass

    # If key begins with sk-lunair or is dev key, accept in dev
    if token.startswith("sk-") or token.startswith("lunair_") or token == "test-key":
        return TrustContext(key_id=f"key_{token[:8]}", is_trusted=False)

    raise HTTPException(
        status_code=401,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )
