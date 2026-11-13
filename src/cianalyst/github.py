"""Read-only GitHub REST client for failed workflow runs.

Endpoints used (both GET, see docs.github.com/en/rest/actions/workflow-jobs):
- List jobs for a workflow run:      GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs
- Download job logs for a workflow run: GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs
  This answers 302 with a Location URL that expires after about a minute.

The token is sent only to the API host. The log download URL is fetched without it.
This client has no method that writes anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"
MAX_LOG_BYTES = 20 * 1024 * 1024
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FAILED = {"failure", "timed_out"}


class GitHubError(RuntimeError):
    pass


@dataclass
class FailedJob:
    id: int
    name: str
    conclusion: str
    failed_step: str | None
    html_url: str | None = None


class GitHubClient:
    def __init__(self, token: str, api_url: str = API_URL, transport: httpx.BaseTransport | None = None):
        if not token:
            raise GitHubError("GITHUB_TOKEN is not set. A token with Actions: read is needed.")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION,
                   "User-Agent": "cianalyst", "Authorization": f"Bearer {token}"}
        self._api = httpx.Client(base_url=api_url, headers=headers, transport=transport,
                                 timeout=30, follow_redirects=False)
        self._download = httpx.Client(headers={"User-Agent": "cianalyst"}, transport=transport,
                                      timeout=60, follow_redirects=False)

    def close(self) -> None:
        self._api.close()
        self._download.close()

    @staticmethod
    def check_repo(repo: str) -> str:
        if not _REPO.match(repo):
            raise GitHubError(f"Repository must look like owner/name, got {repo!r}.")
        return repo

    def _get(self, path: str, **params) -> httpx.Response:
        r = self._api.get(path, params=params or None)
        if r.status_code in (401, 403, 404):
            raise GitHubError(f"GitHub API answered {r.status_code} for {path}. Check the repository, "
                              "the run id, and that the token has Actions: read on this repository.")
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API answered {r.status_code} for {path}.")
        return r

    def failed_jobs(self, repo: str, run_id: int) -> list[FailedJob]:
        """Jobs from the latest attempt of the run whose conclusion is failure or timed_out."""
        self.check_repo(repo)
        jobs: list[dict] = []
        for page in range(1, 11):
            data = self._get(f"/repos/{repo}/actions/runs/{int(run_id)}/jobs",
                             filter="latest", per_page=100, page=page).json()
            batch = data.get("jobs", [])
            jobs += batch
            if not batch or len(jobs) >= data.get("total_count", 0):
                break
        out = []
        for job in jobs:
            if job.get("conclusion") not in FAILED:
                continue
            step = next((s.get("name") for s in job.get("steps") or []
                         if s.get("conclusion") in FAILED), None)
            out.append(FailedJob(id=int(job["id"]), name=str(job.get("name", "")),
                                 conclusion=job["conclusion"], failed_step=step,
                                 html_url=job.get("html_url")))
        return out

    def job_log(self, repo: str, job_id: int) -> str:
        """Plain-text log of one job. Follows the 302 by hand so the token never leaves api.github.com."""
        self.check_repo(repo)
        r = self._get(f"/repos/{repo}/actions/jobs/{int(job_id)}/logs")
        if r.status_code in (301, 302, 303, 307, 308):
            location = r.headers.get("location", "")
            if not location.startswith("https://"):
                raise GitHubError("Log download redirect was not an https URL.")
            r = self._download.get(location)
            if r.status_code >= 400:
                raise GitHubError(f"Log download answered {r.status_code} (the link expires after about a minute).")
        content = r.content
        if len(content) > MAX_LOG_BYTES:  # errors are near the end of a log, so keep the tail
            content = content[-MAX_LOG_BYTES:]
        return content.decode("utf-8", errors="replace")
