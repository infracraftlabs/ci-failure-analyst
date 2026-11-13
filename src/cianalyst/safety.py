"""Defences for hostile log content.

A build or test can print anything, including text aimed at the model ("ignore previous
instructions ..."), links and @mentions. This module:
- flags lines that look like prompt injection, so they never count as evidence;
- strips links, images, HTML and @mentions from model-written text before rendering;
- drops model-suggested commands that download or pipe to a shell.
"""
from __future__ import annotations

import re

_INJECTION = re.compile(
    r"(?i)(ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) instructions"
    r"|disregard (?:the |all )?(?:previous|above|prior|system)"
    r"|\byou are now\b|\bsystem prompt\b|note to (?:the )?(?:ai|assistant|model|llm|bot)"
    r"|\bas an ai\b|report (?:this|the) (?:build|run|job) as (?:passing|green|successful|passed)"
    r"|approve (?:the|this) (?:pr|pull request)|\b(?:tell|ask) the (?:reader|user|maintainer)s? to\b)"
)

_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?i)\b(?:https?|ftp|file)://\S+")
_HTML = re.compile(r"<[^>\n]{1,200}>")
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9_.-]+)?)")
_UNSAFE_CHECK = re.compile(
    r"(?i)\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python3?)\b|\b(?:curl|wget)\b.*\|"
    r"|\brm\s+-rf?\b|https?://|\beval\b"
)


def looks_like_injection(line: str) -> bool:
    return bool(_INJECTION.search(line))


_CLAIMS_SUCCESS = re.compile(
    r"(?i)\b(?:build|job|run|pipeline|tests?|check)s? (?:has |have )?(?:passed|is passing|are passing|succeeded"
    r"|was successful|is green)\b|\bnothing (?:is )?wrong\b"
)


def claims_success(text: str) -> bool:
    """True when model text says the failed job passed: it contradicts the input, so it is not shown."""
    return bool(_CLAIMS_SUCCESS.search(text) or _INJECTION.search(text))


def suspicious_lines(lines: list[str]) -> list[int]:
    """0-based indexes of lines that look like instructions aimed at a model."""
    return [i for i, line in enumerate(lines) if looks_like_injection(line)]


def sanitize(text: str) -> str:
    """Make model-written text safe to render in Markdown (job summary or PR comment)."""
    text = _IMAGE_OR_LINK.sub(lambda m: m.group(1), text)
    text = _URL.sub("[link removed]", text)
    text = _HTML.sub("", text)
    text = _MENTION.sub(lambda m: m.group(1), text)
    return " ".join(text.split())


def safe_check(text: str) -> bool:
    """False for suggested checks that fetch from the network, pipe into a shell or delete."""
    return not _UNSAFE_CHECK.search(text)


def code_block(text: str, lang: str = "text") -> str:
    """Fenced block whose fence is longer than any backtick run inside the text."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


def inline_code(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    ticks = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"
