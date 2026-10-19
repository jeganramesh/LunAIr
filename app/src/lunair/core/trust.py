"""Authentication and gateway trust.

Two request paths reach the core:

* **Gateway path** — the Go edge resolves the caller's API key, then forwards
  with ``X-LUNAIR-Verified: true``, the resolved ``X-LUNAIR-Key-Id`` and a
  ``X-LUNAIR-Gateway-Secret`` shared secret. The secret is what makes the trust
  header a *proof* rather than a *claim*: without it, any client that can reach
  port 8000 could impersonate the gateway.
* **Direct path** — a client talks to FastAPI directly with
  ``Authorization: Bearer <key>``. The key is hashed and looked up.
"""

import hashlib
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from lunair.config import settings
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import APIKey

security = HTTPBearer(auto_error=False)


class TrustContext:
    def __init__(self, key_id: str, is_trusted: bool, source: str = "direct"):
        self.key_id = key_id
        self.is_trusted = is_trusted
        self.source = source


def gateway_secret_ok(provided: Optional[str]) -> bool:
    """Constant-time comparison against the configured gateway secret."""
    expected = settings.gateway_shared_secret
    if not expected:
        return False
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def hash_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def resolve_key_id(token: str) -> Optional[str]:
    """Look up an active API key by its SHA-256 digest. None if unknown."""
    key_hash = hash_key(token)
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(APIKey).where(
                APIKey.key_hash == key_hash, APIKey.is_active.is_(True)
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            if record is not None:
                return record.id
    except Exception:
        return None
    return None


def _dev_bypass_key_id(token: str) -> Optional[str]:
    """Development-only bypass, gated behind an explicit flag."""
    if not settings.dev_auth_bypass:
        return None
    if token.startswith("sk-") or token.startswith("lunair_") or token == "test-key":
        return f"key_{token[:8]}"
    return None


def extract_bearer(request: Request, auth: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    if auth and auth.credentials:
        return auth.credentials
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header.split(" ", 1)[1].strip()
    return None


async def verify_trust_or_auth(
    request: Request,
    x_lunair_verified: Optional[str] = Header(None, alias="X-LUNAIR-Verified"),
    x_lunair_key_id: Optional[str] = Header(None, alias="X-LUNAIR-Key-Id"),
    x_lunair_gateway_secret: Optional[str] = Header(None, alias="X-LUNAIR-Gateway-Secret"),
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> TrustContext:
    """FastAPI dependency resolving the caller's identity.

    The gateway path requires the shared secret. If no secret is configured the
    trusted-header path is refused unless an explicit development flag is set,
    so a misconfigured deployment fails closed instead of open.
    """
    if x_lunair_verified == "true":
        if settings.gateway_shared_secret:
            if not gateway_secret_ok(x_lunair_gateway_secret):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing gateway shared secret",
                )
            return TrustContext(
                key_id=x_lunair_key_id or "gateway-verified-key",
                is_trusted=True,
                source="gateway",
            )

        # No shared secret configured.
        if settings.dev_auth_bypass or settings.debug:
            return TrustContext(
                key_id=x_lunair_key_id or "gateway-verified-key",
                is_trusted=True,
                source="gateway-insecure",
            )
        raise HTTPException(
            status_code=401,
            detail=(
                "Gateway trust is not configured. Set GATEWAY_SHARED_SECRET "
                "(and match it on the gateway) before forwarding traffic."
            ),
        )

    # Direct client path: a real Bearer key is required.
    token = extract_bearer(request, auth)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing Bearer API key in Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_id = await resolve_key_id(token)
    if key_id is not None:
        return TrustContext(key_id=key_id, is_trusted=False, source="direct")

    bypass_id = _dev_bypass_key_id(token)
    if bypass_id is not None:
        return TrustContext(key_id=bypass_id, is_trusted=False, source="dev-bypass")

    raise HTTPException(
        status_code=401,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )
