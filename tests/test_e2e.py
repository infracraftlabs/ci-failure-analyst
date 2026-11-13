"""End-to-end: the CLI with a recorded model response produces the expected report."""
import json
import os
from pathlib import Path

from cianalyst import cli

GOLDEN = Path(__file__).parent / "golden"


def _run(capsys, *args) -> str:
    assert cli.main(list(args)) == 0
    return capsys.readouterr().out


def test_recorded_report_matches_golden(logs, recorded, capsys):
    out = _run(capsys, "--file", str(logs / "gha-npm-dependency.log"),
               "--recorded", str(recorded / "npm-dependency.json"))
    golden = GOLDEN / "npm-dependency-recorded.md"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(out)
    assert out == golden.read_text()


def test_recorded_json_contract(logs, recorded, capsys):
    out = _run(capsys, "--file", str(logs / "gha-npm-dependency.log"),
               "--recorded", str(recorded / "npm-dependency.json"), "--json")
    job = json.loads(out)["jobs"][0]
    r = job["report"]
    assert r["mode"] == "recorded"
    assert len(r["finding"]["likely_causes"]) == 2
    assert r["dropped_causes"] == 1 and job["dropped_unverified"] == 1  # invented 'registry' cause
    assert r["finding"]["likely_causes"][0]["confidence"] == "high"
    assert "root cause" not in out.lower()


def test_falls_back_to_rules_only_without_model(logs, capsys):
    assert cli.main(["--file", str(logs / "gha-docker-out-of-disk.log")]) == 0
    captured = capsys.readouterr()
    assert "rules-only" in captured.err and "ollama pull" in captured.err
    assert "Mode: rules-only" in captured.out
    assert "**infrastructure-runner**" in captured.out


def test_jenkins_report_says_stage(logs, capsys):
    out = _run(capsys, "--file", str(logs / "jenkins-timeout.log"), "--rules-only")
    assert "Failing stage: `Integration tests`" in out and "**timeout**" in out


def test_stdin_and_missing_file(logs, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO((logs / "gha-flaky-network.log").read_text()))
    assert "flaky suspect" in _run(capsys, "--file", "-", "--rules-only")
    assert cli.main(["--file", "/nonexistent/file.log", "--rules-only"]) == 2


def test_bad_model_output_falls_back(logs, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"summary": "x"}')  # missing likely_causes
    out = _run(capsys, "--file", str(logs / "gha-pytest-assertion.log"), "--recorded", str(bad))
    assert "Model call failed" in out and "Mode: rules-only" in out
