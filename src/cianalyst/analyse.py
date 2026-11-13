"""The analysis pipeline for one job log.

clean -> redact -> detect format -> find the failing step -> rules -> first error
-> ~80-line excerpt -> model (AI mode) or rules-only -> evidence check -> checked report.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from . import logparse, rules, safety
from .opscore.contract import Cause, Evidence, Finding, Report, verify_evidence
from .opscore.llm import ModelUnavailable, Ollama, Recorded
from .opscore.redact import redact

NOTE = "Likely causes only, drawn from the log excerpt. Check the evidence before acting; a person decides."

TASK = """A CI job failed. Below is a redacted, line-numbered excerpt of its log and some context.
Deterministic rules classified the failure as: {category} (rule: {rule}).
The first error the rules found is on line {line}.

Explain the most likely causes of the failure, most likely first, at most 3.
For each cause, give one to three pieces of evidence: exact lines or fragments copied character for
character from the excerpt, without the line-number prefix. Do not quote the context block.
Only if the lines clearly show a different kind of failure than the rules' category, add a cause saying so.
Give up to 5 next checks: plain text a person can run or look at. Never claim you ran anything.
Keep the summary to two or three sentences."""


class Provider(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    def analyse(self, task: str, inputs: dict[str, str]) -> Finding: ...


@dataclass
class Prepared:
    """Everything known about one job log before any model call. All text is redacted."""
    source: str
    job: str | None
    lines: list[str]
    log_format: logparse.LogFormat
    section: logparse.Section
    error_index: int | None
    classification: rules.Classification
    excerpt: str
    excerpt_range: tuple[int, int]  # 1-based, inclusive
    redactions: dict[str, int]
    suspicious: list[int]           # 0-based


class JobAnalysis(BaseModel):
    """The JSON shape printed with --json (one entry per analysed job)."""
    source: str
    log_format: str
    job: str | None = None
    failing_step: str | None = None
    first_error_line: int | None = None
    first_error: str | None = None
    category: str
    rule: str | None = None
    rule_hint: str
    flaky_suspect: bool = False
    other_signals: list[str] = []
    rule_next_checks: list[str] = []
    excerpt_lines: tuple[int, int]
    excerpt: str
    suspicious_lines: list[int] = []
    dropped_unverified: int = 0
    dropped_injection_evidence: int = 0
    capped_confidence: int = 0
    dropped_next_checks: int = 0
    warnings: list[str] = []
    report: Report


def prepare(raw: str, source: str, job: str | None = None, step_hint: str | None = None,
            window_size: int = 80) -> Prepared:
    cleaned = "\n".join(logparse.clean(raw))
    red = redact(cleaned)  # before anything else, so no later stage ever sees a secret
    lines = red.text.split("\n")
    fmt = logparse.detect_format(lines)
    secs = logparse.sections(lines, fmt)
    section = logparse.failing_section(lines, secs, step_hint)

    indexes = list(range(section.start, section.end))
    markers = [i for i, line in enumerate(lines) if logparse.MARKER.match(line)]
    # Rules look at the failing section plus failure markers outside it (e.g. Jenkins
    # "Timeout has been exceeded" printed after the pipeline ends).
    scan_idx = indexes + [i for i in markers if i not in section]
    classification = rules.classify(lines, scan_idx)

    in_section = [h.index for h in rules.scan(lines, indexes)]
    if in_section:
        error_index: int | None = min(in_section)
    else:
        generic = [i for i in indexes if logparse.is_generic_error(lines[i])]
        sec_markers = [i for i in markers if i in section]
        error_index = (generic or sec_markers or [None])[0]

    anchor = error_index if error_index is not None else section.end - 1
    start, end = logparse.window(section, anchor, window_size)
    extra = [i for i in markers if i >= end][:5]
    excerpt = logparse.numbered(lines, start, end, extra)
    return Prepared(
        source=source, job=job, lines=lines, log_format=fmt, section=section,
        error_index=error_index, classification=classification, excerpt=excerpt,
        excerpt_range=(start + 1, end), redactions=red.counts,
        suspicious=safety.suspicious_lines(lines),
    )


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def rules_only_finding(p: Prepared) -> Finding:
    c = p.classification
    kind = "stage" if p.log_format == "jenkins" else "step"
    where = f"{kind} '{p.section.name}'" if p.log_format != "generic" else "the job"
    if c.primary is None:
        line = f" from line {p.error_index + 1}" if p.error_index is not None else ""
        return Finding(summary=f"The job failed in {where}. No known failure pattern matched; "
                               f"read the excerpt{line}.",
                       likely_causes=[], next_checks=c.next_checks)
    cause = Cause(cause=c.hint, confidence="medium",
                  evidence=[Evidence(source="log", quote=c.primary.line.strip())])
    return Finding(summary=f"The job failed in {where}. Rules classified it as {c.category}: {c.hint}",
                   likely_causes=[cause], next_checks=c.next_checks)


def _plain(p: Prepared) -> str:
    """The excerpt's lines without the line-number prefix."""
    return "\n".join(row.split(" | ", 1)[1] if " | " in row else row for row in p.excerpt.split("\n"))


def _context(p: Prepared) -> str:
    return (f"CI system: {p.log_format}\n"
            f"Job: {p.job or 'unknown'}\n"
            f"Failing step or stage: {p.section.name}\n"
            f"Excerpt covers lines {p.excerpt_range[0]}-{p.excerpt_range[1]} of {len(p.lines)}")


def analyse(p: Prepared, provider: Provider | None) -> JobAnalysis:
    """Run the model (if any) on the prepared excerpt and check what comes back."""
    warnings: list[str] = []
    mode: Literal["ai", "rules-only", "recorded"] = "rules-only"
    model_name = None
    finding: Finding | None = None
    c = p.classification

    if provider is not None:
        task = TASK.format(category=c.category, rule=c.primary.rule.id if c.primary else "none",
                           line=(p.error_index + 1) if p.error_index is not None else "unknown")
        inputs = {"ci-context": _context(p), "ci-log-excerpt": p.excerpt}
        try:
            finding = provider.analyse(task, inputs)
            mode = "recorded" if isinstance(provider, Recorded) else "ai"
            model_name = provider.name
        except (ModelUnavailable, ValidationError, ValueError, KeyError) as e:
            warnings.append(f"Model call failed ({type(e).__name__}); showing rules-only result.")

    dropped = dropped_inj = capped = dropped_checks = 0
    if finding is None:
        finding = rules_only_finding(p)
    else:
        # 1. Evidence must be copied from the excerpt the model saw.
        #    Quotes may span consecutive lines, so the plain text (no line numbers) counts too.
        finding, dropped = verify_evidence(finding, p.excerpt + "\n" + _plain(p))
        # 2. A quote from a line that looks like prompt injection is not evidence.
        bad = [_norm(p.lines[i]) for i in p.suspicious]
        kept = []
        for cause in finding.likely_causes:
            if safety.claims_success(cause.cause) or any(
                    _norm(e.quote) in b or (b and b in _norm(e.quote)) for e in cause.evidence for b in bad):
                dropped_inj += 1
            else:
                kept.append(cause)
        # 3. 'high' needs a rule match that the model's evidence agrees with.
        out = []
        primary = _norm(c.primary.line) if c.primary else None
        for cause in kept:
            agrees = primary is not None and any(_norm(e.quote) in primary or primary in _norm(e.quote)
                                                 for e in cause.evidence)
            if cause.confidence == "high" and not agrees:
                cause = cause.model_copy(update={"confidence": "medium"})
                capped += 1
            out.append(cause.model_copy(update={"cause": safety.sanitize(cause.cause)}))
        # 4. Suggested checks are text only; drop ones that download, pipe to a shell or delete.
        checks = [safety.sanitize(x) for x in finding.next_checks if safety.safe_check(x)]
        dropped_checks = len(finding.next_checks) - len(checks)
        summary = safety.sanitize(finding.summary)
        if not out:
            summary = rules_only_finding(p).summary
            warnings.append("No model cause survived the evidence check; the summary is the rules' summary.")
        elif safety.claims_success(finding.summary):
            summary = rules_only_finding(p).summary
            warnings.append("The model's summary claimed success or echoed instructions from the log; "
                            "it was replaced by the rules' summary.")
        finding = finding.model_copy(update={"likely_causes": out, "next_checks": checks,
                                             "summary": summary,
                                             "suggested_change": safety.sanitize(finding.suggested_change)
                                             if finding.suggested_change else None})

    if p.suspicious:
        nums = ", ".join(str(i + 1) for i in p.suspicious[:10])
        warnings.append(f"Possible prompt-injection text in the log (line {nums}); treated as data only.")

    report = Report(finding=finding, mode=mode, model=model_name, redactions=p.redactions,
                    dropped_causes=dropped + dropped_inj, note=NOTE)
    err = p.error_index
    return JobAnalysis(
        source=p.source, log_format=p.log_format, job=p.job,
        failing_step=p.section.name if p.log_format != "generic" else None,
        first_error_line=err + 1 if err is not None else None,
        first_error=p.lines[err].strip() if err is not None else None,
        category=c.category, rule=c.primary.rule.id if c.primary else None, rule_hint=c.hint,
        flaky_suspect=c.flaky_suspect,
        other_signals=[f"{h.rule.category} ({h.rule.id}, line {h.index + 1})" for h in c.hits[1:]],
        rule_next_checks=c.next_checks, excerpt_lines=p.excerpt_range, excerpt=p.excerpt,
        suspicious_lines=[i + 1 for i in p.suspicious], dropped_unverified=dropped,
        dropped_injection_evidence=dropped_inj, capped_confidence=capped,
        dropped_next_checks=dropped_checks, warnings=warnings, report=report,
    )


def pick_provider(rules_only: bool, recorded: str | None, model: str | None) -> tuple[Provider | None, str | None]:
    """Return (provider, warning). AI is the default; rules-only is the fallback."""
    if rules_only:
        return None, None
    if recorded:
        from pathlib import Path
        return Recorded(Path(recorded)), None
    ollama = Ollama(model=model) if model else Ollama()
    if ollama.available():
        return ollama, None
    return None, (f"Model {ollama.model} is not reachable at {ollama.host}; showing rules-only result. "
                  f"Start Ollama and run `ollama pull {ollama.model}` for AI mode.")
