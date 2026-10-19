"""Internal endpoints called by the Go gateway.

These are not part of the public API. They are gated on the same shared secret
the gateway uses, so an external client cannot use them to probe keys.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from lunair.config import settings
from lunair.core.trust import (
    _dev_bypass_key_id,
    extract_bearer,
    gateway_secret_ok,
    resolve_key_id,
)

internal_api = APIRouter(prefix="/internal", tags=["internal"])


@internal_api.post("/validate")
async def validate_key(
    request: Request,
    x_lunair_gateway_secret: Optional[str] = Header(None, alias="X-LUNAIR-Gateway-Secret"),
) -> Dict[str, Any]:
    """Resolve a Bearer key to a key id on behalf of the gateway.

    The gateway calls this once per (uncached) request so that authentication
    happens against the database, not against a client-supplied header.
    """
    if not settings.gateway_shared_secret or not gateway_secret_ok(x_lunair_gateway_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing gateway shared secret")

    token = extract_bearer(request, None)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer API key")

    key_id = await resolve_key_id(token)
    if key_id is not None:
        return {"valid": True, "key_id": key_id}

    bypass_id = _dev_bypass_key_id(token)
    if bypass_id is not None:
        return {"valid": True, "key_id": bypass_id}

    raise HTTPException(status_code=401, detail="Invalid API key")
