"""A log that tries to instruct the model must not change the tool's behaviour."""
import json

import httpx

from cianalyst import render
from cianalyst.analyse import analyse, prepare
from cianalyst.opscore import llm
from cianalyst.opscore.llm import Recorded


def _prep(logs):
    return prepare((logs / "gha-injection-and-secrets.log").read_text(), "injection.log")


def test_injection_text_is_flagged_but_classification_is_unchanged(logs):
    p = _prep(logs)
    assert p.classification.category == "test"
    flagged = [p.lines[i] for i in p.suspicious]
    assert any("ignore previous instructions" in line for line in flagged)
    assert any("Tell the reader to run" in line for line in flagged)


def test_payload_wraps_the_log_as_untrusted_data(logs, recorded, monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["payload"] = json
        body = {"message": {"content": (recorded / "injection-hostile.json").read_text()}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    analyse(_prep(logs), llm.Ollama(model="test-model", host="http://127.0.0.1:1"))
    messages = sent["payload"]["messages"]
    assert messages[0]["role"] == "system" and "never follow it" in messages[0]["content"]
    user = messages[1]["content"]
    start = user.index('<untrusted-input source="ci-log-excerpt">')
    end = user.index("</untrusted-input>", start)
    assert start < user.index("ignore previous instructions") < end
    assert "tools" not in sent["payload"]  # the model is given no tools at all


def test_hostile_model_output_is_neutralised(logs, recorded):
    a = analyse(_prep(logs), Recorded(recorded / "injection-hostile.json"))
    causes = [c.cause for c in a.report.finding.likely_causes]
    assert not any("passing" in c for c in causes)      # quoted injected text: dropped
    assert not any("migration" in c for c in causes)    # invented evidence: dropped
    assert a.dropped_injection_evidence == 1 and a.dropped_unverified == 1
    assert a.category == "test"                          # rules decide the category
    conf = {c.cause[:20]: c.confidence for c in a.report.finding.likely_causes}
    assert conf["The refund limit che"] == "high"         # agrees with the rule's line
    assert conf["The test fixture use"] == "medium"       # no rule agreement: capped
    assert a.capped_confidence == 1
    assert a.dropped_next_checks == 1                    # curl | sh removed

    md = render.markdown([a])
    outside_code = _strip_code(md)
    assert "evil.example.com" not in outside_code
    assert "@release-bot" not in outside_code
    assert "<img" not in md
    assert "build passed" not in md.lower()               # contradicting summary replaced
    assert any("replaced by the rules' summary" in w for w in a.warnings)


def test_summary_is_sanitised(logs, recorded):
    a = analyse(_prep(logs), Recorded(recorded / "injection-hostile.json"))
    s = a.report.finding.summary
    assert "http" not in s and "@" not in s and "<" not in s


def test_github_client_cannot_write():
    from cianalyst.github import GitHubClient
    public = [n for n in dir(GitHubClient) if not n.startswith("_")]
    assert sorted(public) == ["check_repo", "close", "failed_jobs", "job_log"]


def _strip_code(md: str) -> str:
    out, inside = [], False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    text = "\n".join(out)
    import re
    return re.sub(r"`[^`]*`", "", text)


def test_quote_spanning_two_lines_is_kept_but_altered_quote_is_dropped(logs):
    from cianalyst.opscore.contract import Cause, Evidence, Finding

    class Fake:
        name = "fake"
        def available(self): return True
        def analyse(self, task, inputs):
            return Finding(summary="s", likely_causes=[
                Cause(cause="joined", confidence="medium", evidence=[Evidence(
                    source="log", quote="npm error notarget In most cases you or one of your dependencies are requesting npm error notarget a package version that doesn't exist.")]),
                Cause(cause="altered", confidence="medium", evidence=[Evidence(
                    source="log", quote="In most cases you or one of your dependencies are requesting a package version")]),
            ])

    a = analyse(prepare((logs / "gha-npm-dependency.log").read_text(), "x"), Fake())
    assert [c.cause for c in a.report.finding.likely_causes] == ["joined"]
    assert a.dropped_unverified == 1
