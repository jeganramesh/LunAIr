"""Prompt compression.

A deliberately conservative first engine ("lite"): it removes only redundancy
that cannot change meaning — repeated blank lines, trailing whitespace,
duplicate system messages and empty messages. Code blocks, URLs and structured
data are left untouched.

This is the safe, always-on tier. Aggressive engines (prose condensation,
history aging, tool-output filtering) are intended to compose on top of it; the
pipeline shape is here so they can be added without changing callers.
"""

import re
from typing import Any, Dict, List, Tuple

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")


def _clean(text: str) -> str:
    text = _TRAILING_WS.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def compress_lite(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Return ``(compressed_messages, stats)``."""
    out: List[Dict[str, Any]] = []
    seen_system: set[str] = set()
    before = 0
    after = 0

    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            before += len(content)
            cleaned = _clean(content)
            if not cleaned and message.get("role") != "assistant":
                continue
            if message.get("role") == "system":
                if cleaned in seen_system:
                    continue
                seen_system.add(cleaned)
            after += len(cleaned)
            out.append({**message, "content": cleaned})
        else:
            out.append(message)

    return out, {"chars_before": before, "chars_after": after, "saved": max(0, before - after)}


def is_enabled() -> bool:
    from lunair.config import settings

    return bool(settings.get_compression_config().get("enabled", False))
