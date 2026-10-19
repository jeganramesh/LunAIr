import json
import time
from typing import AsyncGenerator, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import litellm
from litellm import completion_cost

from lunair.config import settings
from lunair.core.litellm_router import router
from lunair.core.router_engine import resolve_intent
from lunair.core.trust import TrustContext, verify_trust_or_auth
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import Request as DBRequest
from lunair.observability import metrics
from lunair.reliability import circuit_breaker
from lunair.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

router_api = APIRouter(prefix="/v1", tags=["chat"])


def extract_provider(model_name: str) -> str:
    for item in settings.get_model_list():
        if item.get("model_name") == model_name:
            litellm_model = item.get("litellm_params", {}).get("model", "")
            if "/" in litellm_model:
                return litellm_model.split("/")[0]
    if "gemini" in model_name:
        return "gemini"
    if "groq" in model_name or "llama" in model_name:
        return "groq"
    if "gpt" in model_name:
        return "openai"
    return "openai"


def summarize_error(err: Optional[BaseException], limit: int = 300) -> str:
    """Collapse a provider exception into a single readable line."""
    if err is None:
        return "no provider attempted the request"
    message = " ".join(str(err).split())
    if len(message) > limit:
        message = message[:limit] + "..."
    return message


async def record_request_in_db(
    key_id: str,
    requested_model: str,
    actual_model: str,
    provider: str,
    tokens_in: int,
    tokens_out: int,
    cost: float,
    latency_ms: float,
    fallback_from: Optional[str] = None,
    finish_reason: Optional[str] = "stop",
    gateway_mode: str = "go",
):
    try:
        async with AsyncSessionLocal() as session:
            db_req = DBRequest(
                key_id=key_id,
                model=actual_model,
                provider=provider,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                latency_ms=latency_ms,
                fallback_from=fallback_from,
                finish_reason=finish_reason,
                gateway_mode=gateway_mode,
            )
            session.add(db_req)
            await session.commit()
    except Exception:
        pass


@router_api.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    raw_request: Request,
    trust: TrustContext = Depends(verify_trust_or_auth),
):
    start_time = time.time()
    key_id = trust.key_id
    gateway_mode = "go" if trust.is_trusted else "fastapi_only"

    candidates = resolve_intent(req.model)

    # Drop providers without real credentials so we fail fast with an
    # actionable message instead of a 401 storm from every candidate.
    unconfigured = settings.get_unconfigured_providers()
    if unconfigured:
        usable = [c for c in candidates if extract_provider(c) not in unconfigured]
        if not usable:
            missing = ", ".join(sorted(unconfigured.values()))
            metrics.observe_completion(
                provider="unknown", model=req.model, status="unconfigured"
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    f"No provider credentials configured. Set {missing} in .env "
                    f"before requesting model '{req.model}'."
                ),
            )
        candidates = usable

    last_error = None
    response_obj = None
    selected_model = None
    fallback_from = None

    messages_payload = [m.model_dump() for m in req.messages]

    # Try resolved model candidates in priority order
    for idx, candidate in enumerate(candidates):
        try:
            call_kwargs = {
                "model": candidate,
                "messages": messages_payload,
                "stream": req.stream,
            }
            if req.temperature is not None:
                call_kwargs["temperature"] = req.temperature
            if req.max_tokens is not None:
                call_kwargs["max_tokens"] = req.max_tokens
            if req.stop is not None:
                call_kwargs["stop"] = req.stop

            resp = await router.acompletion(**call_kwargs)
            response_obj = resp
            selected_model = candidate
            circuit_breaker.record_success(extract_provider(candidate))
            if idx > 0:
                fallback_from = candidates[0]
            elif req.model != candidate:
                fallback_from = req.model
            break
        except Exception as err:
            last_error = err
            circuit_breaker.record_failure(extract_provider(candidate))
            continue

    if response_obj is None:
        metrics.observe_completion(
            provider=extract_provider(candidates[0]) if candidates else "unknown",
            model=req.model,
            status="error",
            latency_seconds=(time.time() - start_time),
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"All provider candidates failed for model '{req.model}'. "
                f"Last error: {summarize_error(last_error)}"
            ),
        )

    latency_ms = (time.time() - start_time) * 1000.0
    provider = extract_provider(selected_model)

    metrics.observe_completion(
        provider=provider,
        model=selected_model,
        status="success",
        latency_seconds=latency_ms / 1000.0,
        fallback_from=fallback_from,
    )

    if req.stream:
        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                async for chunk in response_obj:
                    chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
                    yield f"data: {json.dumps(chunk_dict)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as stream_err:
                error_payload = {"error": {"message": str(stream_err), "type": "stream_error"}}
                yield f"data: {json.dumps(error_payload)}\n\n"

        response_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-LUNAIR-Provider": provider,
            "X-LUNAIR-Model": selected_model,
            "X-LUNAIR-Cost-USD": "0.000000",
        }
        if fallback_from:
            response_headers["X-LUNAIR-Fallback-From"] = fallback_from

        return StreamingResponse(event_generator(), headers=response_headers)

    # Non-streaming response
    resp_dict = response_obj.model_dump() if hasattr(response_obj, "model_dump") else dict(response_obj)

    try:
        cost = completion_cost(completion_response=response_obj) or 0.0
    except Exception:
        cost = 0.0

    usage = resp_dict.get("usage") or {}
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)
    choices = resp_dict.get("choices") or [{}]
    finish_reason = choices[0].get("finish_reason", "stop")

    await record_request_in_db(
        key_id=key_id,
        requested_model=req.model,
        actual_model=selected_model,
        provider=provider,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        latency_ms=latency_ms,
        fallback_from=fallback_from,
        finish_reason=finish_reason,
        gateway_mode=gateway_mode,
    )

    response_headers = {
        "X-LUNAIR-Provider": provider,
        "X-LUNAIR-Model": selected_model,
        "X-LUNAIR-Cost-USD": f"{cost:.6f}",
    }
    if fallback_from:
        response_headers["X-LUNAIR-Fallback-From"] = fallback_from

    return Response(
        content=json.dumps(resp_dict),
        media_type="application/json",
        headers=response_headers,
    )
