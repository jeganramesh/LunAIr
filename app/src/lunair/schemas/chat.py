from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict

# Content may be a plain string (classic) or a list of parts (vision / multimodal).
MessageContent = Optional[Union[str, List[Dict[str, Any]]]]


class ChatMessage(BaseModel):
    # ``extra="allow"`` keeps unknown message fields (e.g. provider-specific
    # annotations) instead of rejecting the request, matching OpenAI SDK
    # behaviour when new fields are added upstream.
    model_config = ConfigDict(extra="allow")

    role: str
    content: MessageContent = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    # Permissive: unknown fields are preserved rather than 422'd so new OpenAI
    # parameters do not break clients. Only a known-safe subset is forwarded
    # upstream (see FORWARDABLE_PARAMS).
    model_config = ConfigDict(extra="allow")

    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    logit_bias: Optional[Dict[str, float]] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    user: Optional[str] = None
    seed: Optional[int] = None
    response_format: Optional[Dict[str, Any]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    parallel_tool_calls: Optional[bool] = None
    stream_options: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = None
    modalities: Optional[List[str]] = None
    # OpenRouter-style provider routing preferences for this request.
    provider: Optional[Dict[str, Any]] = None
    # Model fallback array: try these models if the primary fails.
    models: Optional[List[str]] = None


# Parameters forwarded verbatim to the upstream provider when present.
FORWARDABLE_PARAMS = (
    "temperature",
    "top_p",
    "n",
    "stop",
    "max_tokens",
    "max_completion_tokens",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "top_logprobs",
    "user",
    "seed",
    "response_format",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "stream_options",
    "metadata",
    "reasoning_effort",
    "service_tier",
    "modalities",
)


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: Optional[int] = 0
    cached_tokens: Optional[int] = 0


class ChatChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatChoiceMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: Optional[Usage] = None
