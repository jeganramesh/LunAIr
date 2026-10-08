from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    gateway_mode: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error: str
    message: Optional[str] = None
    code: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
