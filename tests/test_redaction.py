"""Planted fake secrets in a CI log never reach the model payload."""
import json

import httpx

from cianalyst.analyse import analyse, prepare
from cianalyst.opscore import llm

SECRETS = ["PlantedFakePass123", "AKIAFAKEPLANTED00001", "FakePlantedSecretKeyValue",
           "ghp_FAKEplantedTOKEN", "ops-team@example.com"]


def _capture_ollama(monkeypatch, recorded):
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["url"], sent["payload"] = url, json
        body = {"message": {"content": recorded.joinpath("injection-hostile.json").read_text()}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return sent


def test_secrets_are_in_the_fixture(logs):
    raw = (logs / "gha-injection-and-secrets.log").read_text()
    assert all(s in raw for s in SECRETS)


def test_planted_secrets_never_reach_the_model(logs, recorded, monkeypatch):
    sent = _capture_ollama(monkeypatch, recorded)
    p = prepare((logs / "gha-injection-and-secrets.log").read_text(), "x")
    result = analyse(p, llm.Ollama(model="test-model", host="http://127.0.0.1:1"))
    payload = json.dumps(sent["payload"])
    for secret in SECRETS:
        assert secret not in payload
    assert result.report.redactions["aws-access-key"] >= 0  # counts are reported
    assert sum(result.report.redactions.values()) >= 5


def test_report_output_has_no_secrets(logs):
    from cianalyst import render
    p = prepare((logs / "gha-injection-and-secrets.log").read_text(), "x")
    out = render.markdown([analyse(p, None)]) + render.to_json([analyse(p, None)])
    for secret in SECRETS:
        assert secret not in out
