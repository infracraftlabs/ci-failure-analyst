"""GitHub client against recorded HTTP responses (httpx MockTransport). No network."""
import json

import httpx
import pytest

from cianalyst import cli, github
from cianalyst.github import GitHubClient, GitHubError

TOKEN = "test-token-not-real"
DOWNLOAD = "https://logs.example.com/job-logs/90002?sig=expires-in-60s"


def _transport(recorded, logs, seen):
    jobs = json.loads((recorded / "github" / "jobs-run-7001.json").read_text())
    npm_log = (logs / "gha-npm-dependency.log").read_text()
    disk_log = (logs / "gha-docker-out-of-disk.log").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = request.url
        if url.host == "api.github.com":
            if url.path == "/repos/example-org/web-shop/actions/runs/7001/jobs":
                return httpx.Response(200, json=jobs)
            if url.path == "/repos/example-org/web-shop/actions/jobs/90002/logs":
                return httpx.Response(302, headers={"Location": DOWNLOAD})
            if url.path == "/repos/example-org/web-shop/actions/jobs/90003/logs":
                return httpx.Response(302, headers={"Location": "https://logs.example.com/job-logs/90003"})
            return httpx.Response(404, json={"message": "Not Found"})
        if url.host == "logs.example.com":
            return httpx.Response(200, text=npm_log if url.path.endswith("90002") else disk_log)
        return httpx.Response(500)

    return httpx.MockTransport(handler)


def test_lists_failed_jobs_and_failed_steps(recorded, logs):
    seen = []
    c = GitHubClient(TOKEN, transport=_transport(recorded, logs, seen))
    jobs = c.failed_jobs("example-org/web-shop", 7001)
    assert [(j.id, j.name, j.failed_step) for j in jobs] == [
        (90002, "test", "Run npm ci"),
        (90003, "image", "Run docker build -t registry.example.com/web-shop:3f9a2c1 ."),
    ]
    req = seen[0]
    assert req.url.params["filter"] == "latest" and req.url.params["per_page"] == "100"
    assert req.headers["Accept"] == "application/vnd.github+json"
    assert req.headers["X-GitHub-Api-Version"] == github.API_VERSION


def test_log_download_follows_redirect_without_token(recorded, logs):
    seen = []
    c = GitHubClient(TOKEN, transport=_transport(recorded, logs, seen))
    text = c.job_log("example-org/web-shop", 90002)
    assert "npm error code ETARGET" in text
    api, dl = seen
    assert api.headers["Authorization"] == f"Bearer {TOKEN}"
    assert str(dl.url) == DOWNLOAD and "Authorization" not in dl.headers
    assert all(r.method == "GET" for r in seen)


def test_errors_are_clear_and_never_show_the_token(recorded, logs):
    c = GitHubClient(TOKEN, transport=_transport(recorded, logs, []))
    with pytest.raises(GitHubError) as e:
        c.failed_jobs("example-org/other", 1)
    assert "Actions: read" in str(e.value) and TOKEN not in str(e.value)
    with pytest.raises(GitHubError):
        c.failed_jobs("not a repo", 1)
    with pytest.raises(GitHubError):
        GitHubClient("")


def test_cli_github_mode_end_to_end(recorded, logs, monkeypatch, capsys):
    seen = []
    transport = _transport(recorded, logs, seen)
    real_init = GitHubClient.__init__
    monkeypatch.setattr(GitHubClient, "__init__",
                        lambda self, token, **kw: real_init(self, token, transport=transport))
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    assert cli.main(["--github", "example-org/web-shop", "--run", "7001", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["failed_jobs"] == 2
    assert [(j["job"], j["category"]) for j in doc["jobs"]] == [
        ("test", "dependency"), ("image", "infrastructure-runner")]
    assert doc["jobs"][0]["failing_step"] == "Run npm ci"
    assert all(r.method == "GET" for r in seen)
    assert TOKEN not in json.dumps(doc)


def test_cli_github_needs_run(capsys):
    assert cli.main(["--github", "example-org/web-shop"]) == 2
