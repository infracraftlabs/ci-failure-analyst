"""Deterministic rules: well-known CI failure patterns, checked before any model call.

Each rule has a category, a pattern, a plain-English hint and template next checks
(text for a person; nothing is ever run). Rules are listed in priority order: when
several match, the first one in this list wins. Infrastructure problems come first
because they often cause follow-on errors that look like build or test failures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Category = Literal[
    "test", "dependency", "infrastructure-runner", "timeout",
    "credential-permission", "build-compile", "unknown",
]
CATEGORIES: tuple[str, ...] = (
    "test", "dependency", "infrastructure-runner", "timeout",
    "credential-permission", "build-compile", "unknown",
)


@dataclass(frozen=True)
class Rule:
    id: str
    category: Category
    pattern: re.Pattern[str]
    hint: str
    next_checks: tuple[str, ...]
    flaky: bool = False


def _r(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


RULES: list[Rule] = [
    # --- infrastructure / runner -------------------------------------------------------
    Rule("runner-disk-full", "infrastructure-runner",
         _r(r"no space left on device|\bENOSPC\b|disk quota exceeded|running out of disk space"),
         "The runner ran out of disk space.",
         ("Check free disk space on the runner (for example `df -h`) at the start and end of the job.",
          "Look for large build caches, Docker images or layers that pile up between steps.",
          "Prune unused Docker data before the build, or use a runner with a larger disk.")),
    Rule("runner-lost", "infrastructure-runner",
         _r(r"runner has received a shutdown signal|lost communication with the server"
            r"|hosted runner encountered an error|agent went offline|ChannelClosedException"),
         "The runner or build agent stopped or lost its connection during the job.",
         ("Check the runner or agent status and its host's events around the failure time.",
          "Re-run the job once; if it passes, treat this as an infrastructure incident, not a code problem.")),
    Rule("runner-out-of-memory", "infrastructure-runner",
         _r(r"exit code 137\b|\bOOMKilled\b|JavaScript heap out of memory|Cannot allocate memory"),
         "A process was killed or failed for lack of memory on the runner.",
         ("Compare the job's peak memory with the runner's memory size.",
          "Reduce parallelism in the failing step or use a larger runner.")),
    Rule("docker-daemon", "infrastructure-runner",
         _r(r"Cannot connect to the Docker daemon"),
         "The Docker daemon was not reachable on the runner.",
         ("Check that the runner has Docker installed and the daemon is running.",)),
    # --- timeout ----------------------------------------------------------------------
    Rule("timeout", "timeout",
         _r(r"exceeded the maximum execution time|Cancelling nested steps due to timeout"
            r"|Timeout has been exceeded|\btimed out after\b|Build timed out"),
         "A step, stage or job ran longer than its configured timeout and was stopped.",
         ("Find which command was running when the timeout hit (the last lines before the cancel message).",
          "Compare this run's duration with recent successful runs of the same job.",
          "Check whether the step was waiting on a service that never became ready.")),
    # --- credentials / permissions ----------------------------------------------------
    Rule("cloud-access-denied", "credential-permission",
         _r(r"\((?:AccessDenied|AccessDeniedException|UnauthorizedOperation|ExpiredToken"
            r"|InvalidClientTokenId|SignatureDoesNotMatch)\)|is not authorized to perform"
            r"|Unable to locate credentials|Could not load credentials from any providers"),
         "The cloud credentials used by the job were missing, expired or lacked a permission.",
         ("Check which identity the step used (the role or user named in the error).",
          "Compare the action named in the error with the policies attached to that identity.",
          "Check that the role's trust policy still allows this repository and branch.")),
    Rule("http-auth", "credential-permission",
         _r(r"\b401 Unauthorized\b|\b403 Forbidden\b|authentication failed|Permission denied \(publickey\)"
            r"|Resource not accessible by integration|Bad credentials"
            r"|requested access to the resource is denied|unauthorized: authentication required"),
         "A request was rejected for missing or insufficient credentials.",
         ("Check that the secret or token the step uses is set and not expired.",
          "Check the token's permissions against what the step needs (for GitHub, the workflow `permissions:` block).")),
    # --- transient network (flaky) ----------------------------------------------------
    Rule("network-transient", "infrastructure-runner",
         _r(r"Connection reset by peer|\bECONNRESET\b|\bETIMEDOUT\b|\bECONNREFUSED\b|\bEAI_AGAIN\b"
            r"|Could not resolve host|Temporary failure in name resolution|TLS handshake timeout"
            r"|i/o timeout|Recv failure|\b50[234] (?:Bad Gateway|Service Unavailable|Gateway Time-?out)"),
         "A network request from the runner failed. This is often temporary (a flaky failure).",
         ("Re-run the job once; if it passes, the failure was probably transient.",
          "Check the status of the remote host named in the error.",
          "Consider adding retries with backoff to the download step, or caching the file."),
         flaky=True),
    # --- dependency -------------------------------------------------------------------
    Rule("npm-resolve", "dependency",
         _r(r"\bERESOLVE\b|npm (?:ERR!|error) code E(?:TARGET|NOTARGET)"
            r"|can only install packages when your package\.json and package-lock\.json"
            r"|Missing: \S+ from lock file|No matching version found for"),
         "npm could not resolve a dependency: a version conflict, a version that does not exist, or a lockfile out of sync.",
         ("Run `npm install` locally on the same Node.js version and read the conflict it reports.",
          "Check which recent change touched package.json or package-lock.json.",
          "Check the peer dependency ranges of the package named in the error.")),
    Rule("pip-resolve", "dependency",
         _r(r"No matching distribution found for|ResolutionImpossible"
            r"|Could not find a version that satisfies the requirement"),
         "pip could not find or resolve a required package version.",
         ("Check the pinned version exists for this Python version and platform.",
          "Run the same install locally in a clean virtual environment.")),
    Rule("other-dependency", "dependency",
         _r(r"Could not resolve dependencies for project|Could not find artifact"
            r"|failed to select a version for|Could not resolve all (?:files|dependencies) for configuration"
            r"|lockfile needs to be updated|Couldn't find any versions for"),
         "A package manager could not resolve a dependency.",
         ("Check the dependency name and version in the error against the package registry.",
          "Check recent changes to the dependency or lock files.")),
    # --- build / compile --------------------------------------------------------------
    Rule("compile-error", "build-compile",
         _r(r"error TS\d{4}:|error\[E\d{4}\]|: error: |COMPILATION ERROR|cannot find symbol"
            r"|\bSyntaxError:|ERROR: failed to solve|make: \*\*\*|Build failed with \d+ errors?"
            r"|error CS\d{4}:|undefined reference to"),
         "The code or the container image failed to build.",
         ("Open the file and line named in the first compiler error.",
          "Build the same commit locally with the same tool versions.")),
    # --- tests ------------------------------------------------------------------------
    Rule("test-failure", "test",
         re.compile(r"^E\s{2,}\S|^FAILED \S+::|=+ .*\b\d+ failed\b|^ERROR \S+::|Tests:\s+\d+ failed"
                    r"|^--- FAIL: |^\s*\d+ failing$|Tests run: \d+, Failures: [1-9]|\bAssertionError\b"),
         "One or more tests failed.",
         ("Run the failing test locally on the same commit.",
          "Read the assertion: compare the expected and actual values in the output.",
          "Check whether the test also fails on the base branch, to rule out an older problem.")),
]


@dataclass(frozen=True)
class RuleHit:
    rule: Rule
    index: int  # 0-based line index
    line: str


@dataclass
class Classification:
    category: str
    primary: RuleHit | None
    hits: list[RuleHit] = field(default_factory=list)

    @property
    def flaky_suspect(self) -> bool:
        return bool(self.primary and self.primary.rule.flaky)

    @property
    def next_checks(self) -> list[str]:
        return list(self.primary.rule.next_checks) if self.primary else [
            "Read the excerpt from the first error line and the lines just before it.",
            "Compare with the last successful run of the same job.",
        ]

    @property
    def hint(self) -> str:
        return self.primary.rule.hint if self.primary else "No known failure pattern matched."


def scan(lines: list[str], indexes: list[int]) -> list[RuleHit]:
    """First hit for each rule over the given line indexes."""
    hits: list[RuleHit] = []
    for rule in RULES:
        for i in indexes:
            if rule.pattern.search(lines[i]):
                hits.append(RuleHit(rule, i, lines[i]))
                break
    return hits


def classify(lines: list[str], indexes: list[int]) -> Classification:
    hits = scan(lines, indexes)
    if not hits:
        return Classification("unknown", None, [])
    return Classification(hits[0].rule.category, hits[0], hits)
