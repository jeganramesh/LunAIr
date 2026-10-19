import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

import litellm
from litellm import completion_cost
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from lunair.config import settings
from lunair.core.litellm_router import router
from lunair.core.router_engine import resolve_intent
from lunair.core.trust import TrustContext, verify_trust_or_auth
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import Request as DBRequest
from lunair.observability import metrics
from lunair.reliability import circuit_breaker
from lunair.reliability.rate_limiter import (
    check_rate_limit,
    estimate_tokens,
    record_tokens,
)
from lunair.schemas.chat import FORWARDABLE_PARAMS, ChatCompletionRequest
from lunair.services.budget_service import check_budget, limit_for_key

logger = logging.getLogger("lunair.chat")

router_api = APIRouter(prefix="/v1", tags=["chat"])


def extract_provider(model_name: str) -> str:
    """Provider serving a model, resolved from config with heuristic fallback."""
    return settings.provider_for_model(model_name)


def summarize_error(err: Optional[BaseException], limit: int = 300) -> str:
    """Collapse a provider exception into a single readable line."""
    if err is None:
        return "no provider attempted the request"
    message = " ".join(str(err).split())
    if len(message) > limit:
        message = message[:limit] + "..."
    return message


def build_upstream_kwargs(req: ChatCompletionRequest, candidate: str, stream: bool) -> Dict[str, Any]:
    """Forward the caller's parameters to the provider.

    Only the known-safe parameter set is forwarded, so unknown fields cannot
    break the upstream call, but nothing the caller actually set is dropped.
    When streaming, usage reporting is switched on so cost can be logged.
    """
    payload = req.model_dump(exclude_none=True)
    messages = payload.pop("messages", [])
    payload.pop("model", None)
    payload.pop("stream", None)

    kwargs: Dict[str, Any] = {"model": candidate, "messages": messages, "stream": stream}
    for key in FORWARDABLE_PARAMS:
        value = payload.get(key)
        if value is not None:
            kwargs[key] = value

    if stream:
        stream_options = dict(kwargs.get("stream_options") or {})
        stream_options["include_usage"] = True
        kwargs["stream_options"] = stream_options

    return kwargs


def compute_cost(model_alias: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost in USD for a completion, using the fully-qualified LiteLLM model id."""
    if not prompt_tokens and not completion_tokens:
        return 0.0
    try:
        litellm_model = settings.litellm_model_for(model_alias)
        prompt_cost, completion_cost_usd = litellm.cost_per_token(
            model=litellm_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return float(prompt_cost) + float(completion_cost_usd)
    except Exception:
        return 0.0


def _usage_fields(usage: Dict[str, Any]) -> Dict[str, int]:
    usage = usage or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    return {
        "tokens_in": int(usage.get("prompt_tokens", 0) or 0),
        "tokens_out": int(usage.get("completion_tokens", 0) or 0),
        "cached_tokens": int(prompt_details.get("cached_tokens", 0) or 0),
        "reasoning_tokens": int(completion_details.get("reasoning_tokens", 0) or 0),
    }


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
    ttft_ms: Optional[float] = None,
    reasoning_tokens: int = 0,
    cached_tokens: int = 0,
    request_id: Optional[str] = None,
):
    """Persist one request row. Failures are counted, never fatal."""
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                DBRequest(
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
                    ttft_ms=ttft_ms,
                    reasoning_tokens=reasoning_tokens,
                    cached_tokens=cached_tokens,
                )
            )
            await session.commit()
    except Exception as err:
        metrics.LOGGING_FAILURES.inc()
        logger.warning(
            "failed to persist request log (request_id=%s): %s", request_id, type(err).__name__
        )


@router_api.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    raw_request: Request,
    trust: TrustContext = Depends(verify_trust_or_auth),
):
    start_time = time.time()
    key_id = trust.key_id
    gateway_mode = "go" if trust.is_trusted else "fastapi_only"
    request_id = getattr(raw_request.state, "request_id", None)

    messages_payload = [m.model_dump(exclude_none=True) for m in req.messages]

    # --- admission control: rate limit, then budget ---------------------
    rl_config = settings.get_rate_limit_config()
    rl_result = await check_rate_limit(
        key_id,
        rl_config.get("rpm_per_key"),
        rl_config.get("tpm_per_key"),
        estimate_tokens(messages_payload),
    )
    if not rl_result.allowed:
        metrics.RATE_LIMITED.labels(key_id=key_id).inc()
        raise HTTPException(
            status_code=429,
            detail=rl_result.reason or "rate limit exceeded",
            headers={"Retry-After": str(rl_result.retry_after or 1)},
        )

    budget = await check_budget(key_id, await limit_for_key(key_id))
    if not budget.allowed:
        metrics.BUDGET_BLOCKED.labels(key_id=key_id).inc()
        raise HTTPException(
            status_code=402,
            detail=(
                f"Monthly budget exceeded for key '{key_id}': "
                f"${budget.spend_usd:.2f} of ${budget.limit_usd:.2f} used."
            ),
        )

    # --- resolve candidates ---------------------------------------------
    candidates = resolve_intent(req.model)

    unconfigured = settings.get_unconfigured_providers()
    if unconfigured:
        usable = [c for c in candidates if extract_provider(c) not in unconfigured]
        if not usable:
            missing = ", ".join(sorted(unconfigured.values()))
            metrics.observe_completion(provider="unknown", model=req.model, status="unconfigured")
            raise HTTPException(
                status_code=503,
                detail=(
                    f"No provider credentials configured. Set {missing} in .env "
                    f"before requesting model '{req.model}'."
                ),
            )
        candidates = usable

    # Skip providers whose breaker is open, unless that would leave nothing.
    available = [c for c in candidates if circuit_breaker.is_available(extract_provider(c))]
    if available:
        candidates = available

    last_error: Optional[BaseException] = None
    response_obj = None
    selected_model: Optional[str] = None
    fallback_from: Optional[str] = None

    for idx, candidate in enumerate(candidates):
        provider = extract_provider(candidate)
        try:
            kwargs = build_upstream_kwargs(req, candidate, bool(req.stream))
            resp = await router.acompletion(**kwargs)
            response_obj = resp
            selected_model = candidate
            circuit_breaker.record_success(provider)
            # Only a genuine failover sets this; alias expansion (auto/*) does not.
            if idx > 0:
                fallback_from = candidates[0]
            break
        except Exception as err:
            last_error = err
            circuit_breaker.record_failure(provider)
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

    assert selected_model is not None
    provider = extract_provider(selected_model)

    base_headers = {
        "X-LUNAIR-Provider": provider,
        "X-LUNAIR-Model": selected_model,
        "X-LUNAIR-Requested": req.model,
    }
    if request_id:
        base_headers["X-LUNAIR-Request-Id"] = request_id
    if fallback_from:
        base_headers["X-LUNAIR-Fallback-From"] = fallback_from

    # --- streaming ------------------------------------------------------
    if req.stream:
        async def event_generator() -> AsyncGenerator[str, None]:
            first_chunk_at: Optional[float] = None
            usage: Dict[str, Any] = {}
            status = "success"
            try:
                async for chunk in response_obj:
                    if first_chunk_at is None:
                        first_chunk_at = time.time()
                    chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
                    if chunk_dict.get("usage"):
                        usage = chunk_dict["usage"]
                    yield f"data: {json.dumps(chunk_dict)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as stream_err:
                status = "error"
                circuit_breaker.record_failure(provider)
                payload = {"error": {"message": str(stream_err), "type": "stream_error"}}
                yield f"data: {json.dumps(payload)}\n\n"
            finally:
                end = time.time()
                fields = _usage_fields(usage)
                cost = compute_cost(selected_model, fields["tokens_in"], fields["tokens_out"])
                ttft_ms = ((first_chunk_at - start_time) * 1000.0) if first_chunk_at else None
                await record_tokens(key_id, fields["tokens_in"] + fields["tokens_out"])
                metrics.observe_completion(
                    provider=provider,
                    model=selected_model,
                    status=status,
                    latency_seconds=end - start_time,
                    fallback_from=fallback_from,
                )
                await record_request_in_db(
                    key_id=key_id,
                    requested_model=req.model,
                    actual_model=selected_model,
                    provider=provider,
                    tokens_in=fields["tokens_in"],
                    tokens_out=fields["tokens_out"],
                    reasoning_tokens=fields["reasoning_tokens"],
                    cached_tokens=fields["cached_tokens"],
                    cost=cost,
                    latency_ms=(end - start_time) * 1000.0,
                    fallback_from=fallback_from,
                    gateway_mode=gateway_mode,
                    ttft_ms=ttft_ms,
                    request_id=request_id,
                )

        stream_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Cost is unknown until the stream ends; it is logged, not returned.
            "X-LUNAIR-Cost-USD": "0.000000",
            **base_headers,
        }
        return StreamingResponse(event_generator(), headers=stream_headers)

    # --- non-streaming --------------------------------------------------
    resp_dict = response_obj.model_dump() if hasattr(response_obj, "model_dump") else dict(response_obj)
    usage = resp_dict.get("usage") or {}
    fields = _usage_fields(usage)

    try:
        cost = completion_cost(completion_response=response_obj) or 0.0
    except Exception:
        cost = compute_cost(selected_model, fields["tokens_in"], fields["tokens_out"])

    latency_ms = (time.time() - start_time) * 1000.0
    choices = resp_dict.get("choices") or [{}]
    finish_reason = choices[0].get("finish_reason", "stop")

    await record_tokens(key_id, fields["tokens_in"] + fields["tokens_out"])
    metrics.observe_completion(
        provider=provider,
        model=selected_model,
        status="success",
        latency_seconds=latency_ms / 1000.0,
        fallback_from=fallback_from,
    )
    await record_request_in_db(
        key_id=key_id,
        requested_model=req.model,
        actual_model=selected_model,
        provider=provider,
        tokens_in=fields["tokens_in"],
        tokens_out=fields["tokens_out"],
        reasoning_tokens=fields["reasoning_tokens"],
        cached_tokens=fields["cached_tokens"],
        cost=cost,
        latency_ms=latency_ms,
        fallback_from=fallback_from,
        finish_reason=finish_reason,
        gateway_mode=gateway_mode,
        request_id=request_id,
    )

    return Response(
        content=json.dumps(resp_dict),
        media_type="application/json",
        headers={"X-LUNAIR-Cost-USD": f"{cost:.6f}", **base_headers},
    )
