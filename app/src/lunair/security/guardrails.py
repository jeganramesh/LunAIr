"""Guardrails: PII redaction and prompt-injection detection.

Runs on the request path before the prompt reaches a provider, and (for
non-streaming responses) restores redacted placeholders on the way back.

Detection is deterministic and dependency-free: regex + checksum recognisers
for structured PII, and heuristic scoring for injection. That keeps the hot
path fast and predictable; heavier classifier-based detection can be layered on
as an optional hook without changing callers.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --- PII recognisers --------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

SUPPORTED_TYPES = ("EMAIL", "PHONE", "SSN", "CREDIT_CARD", "API_KEY")


def _luhn(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class PIIEvent:
    pii_type: str
    placeholder: str
    location: str = "prompt"


@dataclass
class RedactionResult:
    text: str
    events: List[PIIEvent] = field(default_factory=list)
    mapping: Dict[str, str] = field(default_factory=dict)


class Redactor:
    """Redacts PII in text, assigning stable placeholders for the request."""

    def __init__(self, types: Optional[List[str]] = None):
        self.types = [t for t in (types or SUPPORTED_TYPES) if t in SUPPORTED_TYPES]
        self._counters: Dict[str, int] = {}
        self._value_to_placeholder: Dict[str, str] = {}
        self.mapping: Dict[str, str] = {}

    def _placeholder(self, pii_type: str, value: str) -> str:
        """Deterministic placeholder: the same value always maps to the same tag.

        Stable pseudonyms keep the prompt prefix identical across turns, which
        preserves provider-side prompt-cache reuse.
        """
        key = f"{pii_type}:{value}"
        existing = self._value_to_placeholder.get(key)
        if existing is not None:
            return existing
        self._counters[pii_type] = self._counters.get(pii_type, 0) + 1
        placeholder = f"<{pii_type}_{self._counters[pii_type]}>"
        self._value_to_placeholder[key] = placeholder
        self.mapping[placeholder] = value
        return placeholder

    def _sub(self, pattern: re.Pattern, text: str, pii_type: str, validator=None) -> Tuple[str, List[PIIEvent]]:
        events: List[PIIEvent] = []

        def repl(match: "re.Match[str]") -> str:
            value = match.group(0)
            if validator and not validator(value):
                return value
            placeholder = self._placeholder(pii_type, value)
            events.append(PIIEvent(pii_type=pii_type, placeholder=placeholder))
            return placeholder

        return pattern.sub(repl, text), events

    def redact(self, text: str, location: str = "prompt") -> RedactionResult:
        if not isinstance(text, str) or not text:
            return RedactionResult(text=text or "")

        events: List[PIIEvent] = []
        if "API_KEY" in self.types:
            text, ev = self._sub(_API_KEY, text, "API_KEY")
            events += ev
        if "EMAIL" in self.types:
            text, ev = self._sub(_EMAIL, text, "EMAIL")
            events += ev
        if "SSN" in self.types:
            text, ev = self._sub(_SSN, text, "SSN")
            events += ev
        if "CREDIT_CARD" in self.types:
            text, ev = self._sub(_CARD, text, "CREDIT_CARD", validator=_luhn)
            events += ev
        if "PHONE" in self.types:
            text, ev = self._sub(_PHONE, text, "PHONE")
            events += ev

        for event in events:
            event.location = location
        return RedactionResult(text=text, events=events, mapping=dict(self.mapping))

    def restore(self, text: str) -> str:
        for placeholder, original in self.mapping.items():
            text = text.replace(placeholder, original)
        return text


def redact_messages(messages: List[Dict[str, Any]], types: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], List[PIIEvent], Dict[str, str]]:
    """Redact PII across a message list (string content and text parts)."""
    redactor = Redactor(types)
    events: List[PIIEvent] = []
    out: List[Dict[str, Any]] = []

    for message in messages:
        new_message = dict(message)
        content = new_message.get("content")
        if isinstance(content, str):
            result = redactor.redact(content, location=new_message.get("role", "prompt"))
            new_message["content"] = result.text
            events += result.events
        elif isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    result = redactor.redact(part["text"], location=new_message.get("role", "prompt"))
                    part = {**part, "text": result.text}
                    events += result.events
                parts.append(part)
            new_message["content"] = parts
        out.append(new_message)

    return out, events, dict(redactor.mapping)


# --- injection detection ----------------------------------------------------

_INJECTION_PATTERNS = [
    (r"ignore (?:all |the )?(?:previous|prior|above) instructions", 0.6),
    (r"disregard (?:all |the )?(?:previous|prior|above)", 0.6),
    (r"forget (?:everything|your instructions|the above)", 0.5),
    (r"you are now (?:a|an|in)\b", 0.4),
    (r"system prompt", 0.3),
    (r"reveal (?:your|the) (?:instructions|prompt|system)", 0.6),
    (r"repeat (?:your|the) (?:instructions|system prompt)", 0.5),
    (r"(?:bypass|override|jailbreak)\b", 0.5),
    (r"do anything now|\bDAN\b", 0.5),
    (r"developer mode", 0.4),
    (r"<\|.*?\|>", 0.3),
]

_SENSITIVITY_SCALE = {"low": 0.6, "medium": 0.8, "high": 1.0}


@dataclass
class InjectionResult:
    risk_score: float
    threats: List[str]
    action: str  # allow | block


def detect_injection(
    messages: List[Dict[str, Any]],
    threshold: float = 0.7,
    sensitivity: str = "high",
) -> InjectionResult:
    """Heuristic injection scan across message text.

    Returns a risk score in ``[0, 1]`` and the matched threat labels. A score at
    or above ``threshold`` yields ``action="block"``; callers decide whether to
    enforce or merely log.
    """
    text_parts: List[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
    blob = "\n".join(text_parts).lower()

    scale = _SENSITIVITY_SCALE.get(sensitivity, 1.0)
    score = 0.0
    threats: List[str] = []
    for pattern, weight in _INJECTION_PATTERNS:
        if re.search(pattern, blob):
            threats.append(pattern)
            score += weight * scale

    score = min(1.0, score)
    return InjectionResult(
        risk_score=round(score, 4),
        threats=threats,
        action="block" if score >= threshold else "allow",
    )
