"""Markdown (job summary / PR comment style) and JSON output.

The wording around the model's text is fixed here. Model-written text has already been
sanitised (no links, images, HTML or @mentions); log lines are shown only inside code blocks.
"""
from __future__ import annotations

import json

from . import __version__
from .analyse import JobAnalysis
from .safety import code_block, inline_code

_FORMAT_NAMES = {"github-actions": "GitHub Actions", "jenkins": "Jenkins", "generic": "plain log"}


def _counts(d: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items())) if d else "none"


def markdown_job(a: JobAnalysis) -> str:
    r = a.report
    f = r.finding
    out: list[str] = []
    title = f" for job {inline_code(a.job)}" if a.job else ""
    out.append(f"### CI failure analysis{title}")
    out.append("")
    out.append("**Likely causes (advisory, check before acting)**")
    out.append("")
    facts = [f"- Log: {inline_code(a.source)} ({_FORMAT_NAMES.get(a.log_format, a.log_format)})"]
    if a.failing_step:
        kind = "stage" if a.log_format == "jenkins" else "step"
        facts.append(f"- Failing {kind}: {inline_code(a.failing_step)}")
    if a.first_error_line:
        facts.append(f"- First error: line {a.first_error_line}: {inline_code(a.first_error or '')}")
    rule = f" (rule {inline_code(a.rule)})" if a.rule else ""
    facts.append(f"- Category from rules: **{a.category}**{rule}. {a.rule_hint}")
    if a.flaky_suspect:
        facts.append("- This looks like a transient failure (flaky suspect). A single re-run is a reasonable first check.")
    if a.other_signals:
        facts.append(f"- Other signals: {'; '.join(a.other_signals)}")
    out += facts
    out.append("")
    out.append(f"**Summary:** {f.summary}")
    out.append("")

    out.append("#### Likely causes")
    out.append("")
    if not f.likely_causes:
        out.append("No cause could be backed by quoted log lines. Read the excerpt below.")
        out.append("")
    for n, cause in enumerate(f.likely_causes, 1):
        out.append(f"{n}. {cause.cause} (confidence: {cause.confidence})")
        out.append("")
        quotes = "\n".join(e.quote.strip() for e in cause.evidence)
        out.append("\n".join("   " + line for line in code_block(quotes).split("\n")))
        out.append("")

    out.append("#### Next checks (text for a person; nothing was run)")
    out.append("")
    for check in a.rule_next_checks:
        out.append(f"- {check}")
    model_checks = [c for c in f.next_checks if c not in a.rule_next_checks]
    if r.mode != "rules-only":
        for check in model_checks:
            out.append(f"- (model) {check}")
    out.append("")
    if f.suggested_change and r.mode != "rules-only":
        out.append(f"**Suggested change (model, review before use):** {f.suggested_change}")
        out.append("")

    if a.warnings:
        out.append("#### Warnings")
        out.append("")
        out += [f"- {w}" for w in a.warnings]
        out.append("")

    start, end = a.excerpt_lines
    out.append("<details><summary>Log excerpt, lines "
               f"{start}-{end} (redacted)</summary>")
    out.append("")
    out.append(code_block(a.excerpt))
    out.append("")
    out.append("</details>")
    out.append("")
    model = f", model: {r.model}" if r.model else ""
    out.append(f"Mode: {r.mode}{model}. Redactions: {_counts(r.redactions)}. "
               f"Causes dropped by the evidence check: {a.dropped_unverified}"
               f" (plus {a.dropped_injection_evidence} quoting suspected injection text). "
               f"Confidence capped: {a.capped_confidence}. Unsafe checks dropped: {a.dropped_next_checks}.")
    out.append("")
    out.append(f"_{r.note}_")
    return "\n".join(out)


def markdown(analyses: list[JobAnalysis], header: str | None = None) -> str:
    parts = [header] if header else []
    parts += [markdown_job(a) for a in analyses]
    return "\n\n---\n\n".join(parts) + "\n"


def to_json(analyses: list[JobAnalysis], extra: dict | None = None) -> str:
    doc = {"schema_version": "1", "tool": f"cianalyst {__version__}", **(extra or {}),
           "jobs": [a.model_dump(mode="json") for a in analyses]}
    return json.dumps(doc, indent=2) + "\n"
