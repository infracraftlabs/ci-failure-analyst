import pytest

from cianalyst.analyse import prepare
from cianalyst.rules import RULES, classify

CASES = [
    # fixture, format, category, rule, failing step, text in first error line
    ("gha-npm-dependency.log", "github-actions", "dependency", "npm-resolve", "Run npm ci", "code ETARGET"),
    ("gha-pytest-assertion.log", "github-actions", "test", "test-failure", "Run pytest -q", "AssertionError"),
    ("gha-docker-out-of-disk.log", "github-actions", "infrastructure-runner", "runner-disk-full",
     "Run docker build -t registry.example.com/web-shop:3f9a2c1 .", "no space left on device"),
    ("jenkins-timeout.log", "jenkins", "timeout", "timeout", "Integration tests", "due to timeout"),
    ("gha-aws-access-denied.log", "github-actions", "credential-permission", "cloud-access-denied", None, "(AccessDenied)"),
    ("gha-flaky-network.log", "github-actions", "infrastructure-runner", "network-transient", "Run make lint-tools",
     "Connection reset by peer"),
    ("gha-injection-and-secrets.log", "github-actions", "test", "test-failure", "Run pytest -q", "DID NOT RAISE"),
]


@pytest.mark.parametrize("name,fmt,category,rule,step,first", CASES)
def test_fixture_is_classified(logs, name, fmt, category, rule, step, first):
    p = prepare((logs / name).read_text(), name)
    assert p.log_format == fmt
    assert p.classification.category == category
    assert p.classification.primary.rule.id == rule
    if step:
        assert p.section.name == step
    assert first in p.lines[p.error_index]


def test_setup_noise_is_skipped(logs):
    # The setup section mentions 'error-reporter-action'; it must not be taken as the first error.
    p = prepare((logs / "gha-npm-dependency.log").read_text(), "x")
    assert not p.section.noise
    assert "error-reporter-action" not in p.lines[p.error_index]
    assert "error-reporter-action" not in p.excerpt


def test_flaky_network_is_flagged(logs):
    p = prepare((logs / "gha-flaky-network.log").read_text(), "x")
    assert p.classification.flaky_suspect
    assert not prepare((logs / "gha-npm-dependency.log").read_text(), "x").classification.flaky_suspect


def test_disk_full_wins_over_follow_on_build_error(logs):
    p = prepare((logs / "gha-docker-out-of-disk.log").read_text(), "x")
    assert [h.rule.category for h in p.classification.hits] == ["infrastructure-runner", "build-compile"]


@pytest.mark.parametrize("line,category", [
    ("npm error code ERESOLVE", "dependency"),
    ("src/app.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.", "build-compile"),
    ("ERROR: No matching distribution found for example-lib==9.9.9", "dependency"),
    ("Error: The job running on runner example-runner-1 has exceeded the maximum execution time of 360 minutes.", "timeout"),
    ("remote: Permission to example-org/web-shop.git denied. fatal: unable to access: The requested URL returned error: 403 Forbidden", "credential-permission"),
    ("Killed: process exited with exit code 137", "infrastructure-runner"),
    ("--- FAIL: TestParseConfig (0.00s)", "test"),
    ("something odd happened and the script stopped", "unknown"),
])
def test_single_line_rules(line, category):
    assert classify([line], [0]).category == category


def test_every_rule_has_checks_and_known_category():
    from cianalyst.rules import CATEGORIES
    for rule in RULES:
        assert rule.category in CATEGORIES and rule.next_checks and rule.hint


def test_window_is_about_80_lines_and_stays_in_the_step(logs):
    p = prepare((logs / "gha-npm-dependency.log").read_text(), "x", window_size=80)
    start, end = p.excerpt_range
    assert end - start + 1 <= 80
    assert p.section.start < start <= p.error_index + 1 <= end


def test_long_log_is_trimmed_around_first_error():
    noise = [f"compiling module {i} ok" for i in range(5000)]
    log = "\n".join(["##[group]Run make build", *noise, "src/main.c:10: error: expected ';'",
                     *noise[:200], "##[error]Process completed with exit code 2."])
    p = prepare(log, "big.log")
    assert p.classification.category == "build-compile"
    assert len(p.excerpt.splitlines()) <= 83  # window + gap + marker line
    assert "expected ';'" in p.excerpt and "exit code 2" in p.excerpt


def test_generic_log_without_markers():
    p = prepare("step one ok\nstep two ok\nfatal: something unexpected\n", "plain.log")
    assert p.log_format == "generic" and p.classification.category == "unknown"
    assert p.lines[p.error_index] == "fatal: something unexpected"
