import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import litellm
from litellm import completion_cost
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from lunair.config import settings
from lunair.core.litellm_router import router
from lunair.core.registry import load_registry
from lunair.core.routing import ProviderPreferences, pin_cache_endpoint, select_endpoints
from lunair.core.trust import TrustContext, verify_trust_or_auth
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import InjectionEvent, PIIEvent, Request as DBRequest
from lunair.observability import metrics
from lunair.reliability import circuit_breaker, stats
from lunair.reliability.rate_limiter import (
    check_rate_limit,
    estimate_tokens,
    record_tokens,
)
from lunair.schemas.chat import FORWARDABLE_PARAMS, ChatCompletionRequest
from lunair.security.guardrails import detect_injection, redact_messages
from lunair.services import cache, compression
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


def build_upstream_kwargs(
    req: ChatCompletionRequest,
    candidate: str,
    stream: bool,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Forward the caller's parameters to the provider.

    Only the known-safe parameter set is forwarded, so unknown fields cannot
    break the upstream call, but nothing the caller actually set is dropped.
    ``messages`` overrides the request messages so guardrail/compression
    processing is what actually reaches the provider.
    """
    payload = req.model_dump(exclude_none=True)
    payload.pop("messages", None)
    for internal in ("model", "stream", "provider", "models"):
        payload.pop(internal, None)

    resolved_messages = messages if messages is not None else [m.model_dump(exclude_none=True) for m in req.messages]
    kwargs: Dict[str, Any] = {"model": candidate, "messages": resolved_messages, "stream": stream}
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
    pii_redacted: bool = False,
    injection_blocked: bool = False,
    cache_hit: bool = False,
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
                    pii_redacted=pii_redacted,
                    injection_blocked=injection_blocked,
                    cache_hit=cache_hit,
                )
            )
            await session.commit()
    except Exception as err:
        metrics.LOGGING_FAILURES.inc()
        logger.warning("failed to persist request log (request_id=%s): %s", request_id, type(err).__name__)


async def record_pii_events(events) -> None:
    if not events:
        return
    try:
        async with AsyncSessionLocal() as session:
            for event in events:
                session.add(
                    PIIEvent(
                        request_id="live",
                        pii_type=event.pii_type,
                        placeholder=event.placeholder,
                        location=event.location,
                    )
                )
            await session.commit()
    except Exception:
        pass


async def record_injection_event(risk: float, threats: List[str], action: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                InjectionEvent(
                    request_id="live",
                    risk_score=risk,
                    threats=",".join(threats)[:2000],
                    action_taken=action,
                )
            )
            await session.commit()
    except Exception:
        pass


def _cacheable_params(req: ChatCompletionRequest) -> Dict[str, Any]:
    payload = req.model_dump(exclude_none=True)
    return {k: payload[k] for k in FORWARDABLE_PARAMS if k in payload}


def _apply_guardrails(messages: List[Dict[str, Any]]):
    """Return (messages, pii_events, pii_map, injection_blocked)."""
    security = settings.get_security_config()
    pii_events: List[Any] = []
    pii_map: Dict[str, str] = {}

    if security.get("pii_redaction"):
        messages, pii_events, pii_map = redact_messages(messages, security.get("pii_types"))

    injection_blocked = False
    if security.get("injection_detection"):
        result = detect_injection(
            messages,
            threshold=float(security.get("injection_risk_threshold", 0.7)),
            sensitivity=security.get("injection_sensitivity", "high"),
        )
        if result.action == "block":
            injection_blocked = True
    return messages, pii_events, pii_map, injection_blocked


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

    # --- guardrails: PII redaction + injection detection ----------------
    messages_payload, pii_events, pii_map, injection_blocked = _apply_guardrails(messages_payload)
    if injection_blocked:
        security = settings.get_security_config()
        scan = detect_injection(
            messages_payload,
            threshold=float(security.get("injection_risk_threshold", 0.7)),
            sensitivity=security.get("injection_sensitivity", "high"),
        )
        metrics.INJECTION_BLOCKED.inc()
        await record_injection_event(scan.risk_score, scan.threats, "blocked")
        await record_request_in_db(
            key_id=key_id, requested_model=req.model, actual_model=req.model,
            provider="none", tokens_in=0, tokens_out=0, cost=0.0,
            latency_ms=(time.time() - start_time) * 1000.0, gateway_mode=gateway_mode,
            request_id=request_id, injection_blocked=True,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Request blocked: possible prompt injection.",
                "risk_score": scan.risk_score,
                "threats": scan.threats,
            },
        )
    if pii_events:
        metrics.PII_REDACTED.inc(len(pii_events))
        await record_pii_events(pii_events)

    # --- prompt compression --------------------------------------------
    if compression.is_enabled():
        messages_payload, _ = compress_lite_safe(messages_payload)

    # --- routing: resolve the ordered endpoint list ---------------------
    registry = load_registry()
    routing_cfg = settings.get_routing_config()
    prefs = ProviderPreferences.from_request(req.provider)

    prompt_hash = cache.prompt_prefix_hash(messages_payload) if cache.is_enabled() else None

    endpoints, strategy, route_error = select_endpoints(
        req.model,
        registry=registry,
        routing_cfg=routing_cfg,
        prefs=prefs,
        prompt_hash=prompt_hash,
    )
    if route_error:
        raise HTTPException(status_code=400, detail=route_error)

    # Model fallback array: append candidates from req.models.
    for fallback_model in (req.models or []):
        endpoints.extend(registry.endpoints_for(fallback_model))

    # Drop providers with no usable credentials; fail fast if none remain.
    unconfigured = settings.get_unconfigured_providers()
    if unconfigured:
        usable = [e for e in endpoints if e.provider not in unconfigured]
        if not usable:
            missing = ", ".join(sorted(unconfigured.values()))
            metrics.observe_completion(provider="unknown", model=req.model, status="unconfigured")
            raise HTTPException(
                status_code=503,
                detail=(
                    f"No provider credentials configured for '{req.model}'. "
                    f"Set {missing} in .env before requesting it."
                ),
            )
        endpoints = usable

    if not endpoints:
        raise HTTPException(status_code=503, detail=f"No endpoints available for '{req.model}'.")

    # --- response cache (non-streaming only) ---------------------------
    cache_key_value = None
    if not req.stream and cache.is_enabled():
        cache_key_value = cache.cache_key(key_id, req.model, _cacheable_params(req), messages_payload)
        cached = await cache.get_cached(cache_key_value)
        if cached is not None:
            metrics.CACHE_HITS.inc()
            metrics.observe_completion(provider=cached.get("provider", "cache"), model=req.model, status="cache_hit")
            return Response(
                content=json.dumps(cached["body"]),
                media_type="application/json",
                headers={
                    "X-LUNAIR-Cache": "hit",
                    "X-LUNAIR-Provider": cached.get("provider", "cache"),
                    "X-LUNAIR-Model": cached.get("model", req.model),
                    "X-LUNAIR-Cost-USD": "0.000000",
                    "X-LUNAIR-Requested": req.model,
                    **({"X-LUNAIR-Request-Id": request_id} if request_id else {}),
                },
            )
        metrics.CACHE_MISSES.inc()

    # --- try endpoints in order ----------------------------------------
    last_error: Optional[BaseException] = None
    response_obj = None
    selected = None
    fallback_from: Optional[str] = None

    for idx, endpoint in enumerate(endpoints):
        stats.inc_inflight(endpoint.deployment_name)
        try:
            kwargs = build_upstream_kwargs(req, endpoint.deployment_name, bool(req.stream), messages_payload)
            resp = await router.acompletion(**kwargs)
            response_obj = resp
            selected = endpoint
            latency_ms = (time.time() - start_time) * 1000.0
            stats.record_success(endpoint.deployment_name, latency_ms)
            circuit_breaker.record_success(endpoint.provider)
            if strategy == "cache_optimized" and prompt_hash:
                pin_cache_endpoint(req.model, prompt_hash, endpoint.deployment_name)
            if idx > 0:
                fallback_from = endpoints[0].deployment_name
            break
        except Exception as err:
            last_error = err
            stats.record_failure(endpoint.deployment_name)
            circuit_breaker.record_failure(endpoint.provider)
            continue
        finally:
            stats.dec_inflight(endpoint.deployment_name)

    if response_obj is None or selected is None:
        metrics.observe_completion(
            provider=endpoints[0].provider if endpoints else "unknown",
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

    provider = selected.provider
    base_headers = {
        "X-LUNAIR-Provider": provider,
        "X-LUNAIR-Model": selected.deployment_name,
        "X-LUNAIR-Endpoint": selected.deployment_name,
        "X-LUNAIR-Strategy": strategy,
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
                cost = compute_cost(selected.deployment_name, fields["tokens_in"], fields["tokens_out"])
                ttft_ms = ((first_chunk_at - start_time) * 1000.0) if first_chunk_at else None
                await record_tokens(key_id, fields["tokens_in"] + fields["tokens_out"])
                metrics.observe_completion(
                    provider=provider, model=selected.deployment_name, status=status,
                    latency_seconds=end - start_time, fallback_from=fallback_from,
                )
                await record_request_in_db(
                    key_id=key_id, requested_model=req.model, actual_model=selected.deployment_name,
                    provider=provider, tokens_in=fields["tokens_in"], tokens_out=fields["tokens_out"],
                    reasoning_tokens=fields["reasoning_tokens"], cached_tokens=fields["cached_tokens"],
                    cost=cost, latency_ms=(end - start_time) * 1000.0, fallback_from=fallback_from,
                    gateway_mode=gateway_mode, ttft_ms=ttft_ms, request_id=request_id,
                    pii_redacted=bool(pii_events),
                )

        return StreamingResponse(
            event_generator(),
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-LUNAIR-Cost-USD": "0.000000",
                "X-LUNAIR-Cache": "miss",
                **base_headers,
            },
        )

    # --- non-streaming --------------------------------------------------
    resp_dict = response_obj.model_dump() if hasattr(response_obj, "model_dump") else dict(response_obj)
    usage = resp_dict.get("usage") or {}
    fields = _usage_fields(usage)

    try:
        cost = completion_cost(completion_response=response_obj) or 0.0
    except Exception:
        cost = compute_cost(selected.deployment_name, fields["tokens_in"], fields["tokens_out"])

    latency_ms = (time.time() - start_time) * 1000.0
    choices = resp_dict.get("choices") or [{}]
    finish_reason = choices[0].get("finish_reason", "stop")

    # Restore redacted PII in the response so the caller sees their own data.
    if pii_map:
        resp_dict = _restore_pii(resp_dict, pii_map)

    await record_tokens(key_id, fields["tokens_in"] + fields["tokens_out"])
    metrics.observe_completion(
        provider=provider, model=selected.deployment_name, status="success",
        latency_seconds=latency_ms / 1000.0, fallback_from=fallback_from,
    )
    await record_request_in_db(
        key_id=key_id, requested_model=req.model, actual_model=selected.deployment_name,
        provider=provider, tokens_in=fields["tokens_in"], tokens_out=fields["tokens_out"],
        reasoning_tokens=fields["reasoning_tokens"], cached_tokens=fields["cached_tokens"],
        cost=cost, latency_ms=latency_ms, fallback_from=fallback_from,
        finish_reason=finish_reason, gateway_mode=gateway_mode, request_id=request_id,
        pii_redacted=bool(pii_events),
    )

    if cache_key_value is not None:
        await cache.set_cached(
            cache_key_value,
            {"body": resp_dict, "provider": provider, "model": selected.deployment_name},
        )

    return Response(
        content=json.dumps(resp_dict),
        media_type="application/json",
        headers={"X-LUNAIR-Cost-USD": f"{cost:.6f}", "X-LUNAIR-Cache": "miss", **base_headers},
    )


def compress_lite_safe(messages: List[Dict[str, Any]]):
    from lunair.services.compression import compress_lite

    return compress_lite(messages)


def _restore_pii(resp_dict: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    for choice in resp_dict.get("choices", []) or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            for placeholder, original in mapping.items():
                content = content.replace(placeholder, original)
            message["content"] = content
    return resp_dict
