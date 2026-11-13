"""Read a CI log: clean it, detect the CI system, split it into steps or stages.

Supported formats (detected from markers in the text):
- GitHub Actions job logs: `##[group]Run <command>` starts a step, `##[error]` marks errors.
- Jenkins Pipeline console output: `[Pipeline] { (<stage>)` starts a stage.
- Anything else is treated as one generic section.

Setup and cleanup sections ("Set up job", "Post job cleanup", "Declarative: ..." stages) are
marked as noise so the first real error is not taken from them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

LogFormat = Literal["github-actions", "jenkins", "generic"]

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_GHA_TS = re.compile(r"^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
_JENKINS_TS = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\] ")

_GHA_STEP = re.compile(r"^##\[group\](Run .+)$")
_GHA_POST = re.compile(r"^(?:Post job cleanup\.?|##\[group\]Post .*)$")
_JENKINS_STAGE = re.compile(r"^\[Pipeline\] \{ \((.+)\)$")
_JENKINS_END = re.compile(r"^\[Pipeline\] End of Pipeline$")

# Lines that end a failed job/stage. Used to find the failing section and kept in the
# excerpt even when they fall outside the window around the first error.
MARKER = re.compile(
    r"^(?:##\[error\]|ERROR: |Finished: (?:FAILURE|ABORTED|UNSTABLE)|Timeout has been exceeded"
    r"|script returned exit code [1-9])"
)

_GENERIC_ERROR = re.compile(
    r"(?i)(\berror\b|\bERR!|\bfailed\b|\bfailure\b|\bfatal\b|\bexception\b|traceback|\bdenied\b|\bpanic:)"
)
_NOT_ERROR = re.compile(
    r"(?i)(\b0 errors?\b|\bno errors?\b|continue-on-error|if-no-files-found|\bwarn(ing)?\b|-Werror"
    r"|\berrors?: 0\b|^##\[warning\]|^\s*(set|shell):)"
)


@dataclass(frozen=True)
class Section:
    name: str
    start: int  # 0-based, inclusive
    end: int    # 0-based, exclusive
    noise: bool = False

    def __contains__(self, index: int) -> bool:
        return self.start <= index < self.end


def clean(text: str) -> list[str]:
    """Split into lines; remove carriage returns, ANSI colour codes and leading timestamps."""
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _ANSI.sub("", line)
        line = _GHA_TS.sub("", line)
        line = _JENKINS_TS.sub("", line)
        out.append(line.rstrip())
    while out and not out[-1]:
        out.pop()
    return out


def detect_format(lines: list[str]) -> LogFormat:
    gha = sum(1 for line in lines if line.startswith(("##[group]", "##[error]", "##[endgroup]")))
    jenkins = sum(1 for line in lines if line.startswith("[Pipeline]"))
    if gha == 0 and jenkins == 0:
        return "generic"
    return "github-actions" if gha >= jenkins else "jenkins"


def sections(lines: list[str], fmt: LogFormat) -> list[Section]:
    if fmt == "github-actions":
        starts: list[tuple[int, str, bool]] = [(0, "Set up job", True)]
        for i, line in enumerate(lines):
            if m := _GHA_STEP.match(line):
                starts.append((i, m.group(1), False))
            elif _GHA_POST.match(line):
                starts.append((i, "Post job cleanup", True))
    elif fmt == "jenkins":
        starts = [(0, "Start of pipeline", True)]
        for i, line in enumerate(lines):
            if m := _JENKINS_STAGE.match(line):
                name = m.group(1)
                starts.append((i, name, name.startswith("Declarative: ")))
            elif _JENKINS_END.match(line):
                starts.append((i, "End of pipeline", True))
    else:
        return [Section("log", 0, len(lines))]

    out = []
    for n, (start, name, noise) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        if end > start:
            out.append(Section(name, start, end, noise))
    return out or [Section("log", 0, len(lines))]


def is_generic_error(line: str) -> bool:
    return bool(_GENERIC_ERROR.search(line)) and not _NOT_ERROR.search(line)


def failing_section(lines: list[str], secs: list[Section], step_hint: str | None = None) -> Section:
    """The step or stage that failed.

    Order: a step name supplied by the caller (from the GitHub API) if it matches exactly;
    the real section holding the first failure marker; the last real section with an
    error-looking line; otherwise the last real section.
    """
    real = [s for s in secs if not s.noise] or secs
    if step_hint:
        for s in real:
            if s.name == step_hint or s.name == f"Run {step_hint}":
                return s
    for i, line in enumerate(lines):
        if MARKER.match(line):
            for s in real:
                if i in s:
                    return s
    for s in reversed(real):
        if any(is_generic_error(lines[i]) for i in range(s.start, s.end)):
            return s
    return real[-1]


def window(section: Section, anchor: int, size: int = 80) -> tuple[int, int]:
    """About `size` lines around the anchor, kept inside the section. Returns (start, end)."""
    half = size // 2
    start = max(section.start, anchor - half)
    end = min(section.end, start + size)
    start = max(section.start, end - size)
    return start, end


def numbered(lines: list[str], start: int, end: int, extra: list[int] | None = None) -> str:
    """Line-numbered excerpt (1-based numbers). Extra marker lines outside the window follow a gap."""
    rows = [f"{i + 1:>5} | {lines[i]}" for i in range(start, end)]
    extra = [i for i in (extra or []) if not (start <= i < end)]
    if extra:
        rows.append("  ... | (lines omitted)")
        rows += [f"{i + 1:>5} | {lines[i]}" for i in sorted(set(extra))]
    return "\n".join(rows)
