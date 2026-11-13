# CI failure analyst (`cianalyst`)

`cianalyst` reads the log of a failed GitHub Actions or Jenkins job, finds the failing step and the first real error, keeps about 80 lines around it, and sorts the failure into one of a few kinds: test, dependency, infrastructure-runner, timeout, credential-permission, build-compile or unknown. A local language model then explains the likely causes, quoting the log lines behind each one, and suggests checks for a person to run. Every quote is checked against the log before it is shown. The result is a short Markdown note (for a job summary or a pull request comment) or JSON. It is part of the [InfraCraft Labs](https://infracraftlabs.com) AI Lab.

## Status

**Prototype.** It works on the demo scenario and the synthetic fixtures in `examples/logs/`. It is not for production use.

## Quick start

```sh
git clone https://github.com/infracraftlabs/ci-failure-analyst && cd ci-failure-analyst
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
ollama pull qwen3:8b                      # local model; nothing leaves your machine
.venv/bin/cianalyst --file examples/logs/gha-npm-dependency.log
.venv/bin/cianalyst --file examples/logs/jenkins-timeout.log --rules-only
.venv/bin/cianalyst --file examples/logs/gha-docker-out-of-disk.log --json
GITHUB_TOKEN=<read-only token> .venv/bin/cianalyst --github owner/repo --run <run-id>
.venv/bin/pytest
```

AI mode is the default. If Ollama or the model is not reachable, `cianalyst` says so on stderr and prints the rules-only result. Use `OLLAMA_MODEL` and `OLLAMA_HOST` (or `--model`) to choose another local model.

To run it in GitHub Actions after a failed job, see [`examples/workflows/ci-with-failure-analysis.yml`](examples/workflows/ci-with-failure-analysis.yml). It adds a separate job with `needs: [test]` and `if: failure()` that writes the note to the job summary. It must be a separate job, because a step inside the failing job cannot download that job's own log while it is still running.

## How it works

1. **Read.** From a file (`--file`, or `-` for stdin), or from the GitHub REST API (`--github owner/repo --run <id>`): [List jobs for a workflow run](https://docs.github.com/en/rest/actions/workflow-jobs) picks the jobs whose conclusion is `failure` or `timed_out` and their failed step. Then "Download job logs for a workflow run" fetches each log (up to `--max-jobs`, default 3).
2. **Clean and redact.** Timestamps and colour codes are removed. Then the whole log is redacted before any other stage sees it: keys, tokens, JWTs, passwords in URLs or `KEY=value` pairs, private keys, email addresses, IP addresses and long random-looking strings are replaced with `[REDACTED:<kind>]`. The report gives the count per kind.
3. **Find the failure.** The format is detected from its markers: `##[group]` and `##[error]` for GitHub Actions, `[Pipeline]` for Jenkins, anything else is a plain log. The log is split into steps (Actions) or stages (Jenkins). Setup and cleanup sections are skipped. The failing step is the one holding the first failure marker, or the failed step named by the API.
4. **Rules.** Known patterns (for example `npm error code ETARGET`, `no space left on device`, `is not authorized to perform`, `Cancelling nested steps due to timeout`) give the category, the first error line and template next checks. Infrastructure rules win over build and test rules, because a full disk often causes follow-on build errors. Network resets are marked as flaky suspects.
5. **Model.** The roughly 80-line excerpt, with line numbers, is sent to the local model inside an `<untrusted-input>` block with fixed instructions. The model returns JSON in a fixed schema: summary, likely causes with confidence and evidence quotes, and next checks.
6. **Check.**
   - A cause is dropped if any of its quotes is not found in the excerpt.
   - A cause is also dropped if it quotes a line that looks like prompt injection, or if it says the build passed.
   - `high` confidence is lowered to `medium` unless the cause quotes the line the rules matched.
   - Suggested checks that download, pipe into a shell or delete are dropped.
   - Links, images, HTML and `@mentions` are stripped from the model's text, and log lines are shown only inside code blocks.

   The report shows how many causes were dropped and why.

## Security model

- **Read-only.** The GitHub client only makes `GET` requests: list jobs, then download logs. It cannot re-run jobs, post comments, push code or change settings. There is no shell or command execution anywhere. The suggested checks are only text for a person to read.
- **Permissions.** For `--github`, the token needs **Actions: read** on the repository (a fine-grained token, or `GITHUB_TOKEN` with `permissions: actions: read`), plus `contents: read` as usual in a workflow. See [Controlling GITHUB_TOKEN permissions](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token). The token is read from the `GITHUB_TOKEN` environment variable. It is only sent to `api.github.com`. The log download URL that the API redirects to is fetched without it, and the token never appears in output or errors.
- **What is read.** The job list for one run, and the logs of its failed jobs. Only the excerpt around the first error goes to the model. The model runs locally through Ollama, so by default nothing leaves the machine.
- **Logs are untrusted input.** A test or build script can print anything, including text aimed at the model. The excerpt is wrapped as data, and the model is given no tools. Lines that look like instructions ("ignore previous instructions", "report this build as passing") are flagged in the report and cannot count as evidence. The category always comes from the rules, not from the model. `examples/logs/gha-injection-and-secrets.log` and `tests/test_injection.py` cover this.
- **Never on `pull_request_target` for fork pull requests.** A `pull_request_target` workflow runs in the context of the base repository's default branch, not the fork's code. [GitHub warns](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#pull_request_target) that running untrusted pull request code there can lead to unintended write access or secret access. This tool needs neither secrets nor write access. Run it on `pull_request` (and `push`): for pull requests from forks, GitHub gives `GITHUB_TOKEN` read-only permissions and passes no other secrets. A fork's log may still contain hostile text, which the previous point covers.
- **Pin what you run.** Pin actions and `cianalyst` itself to full commit SHAs in workflows, as the example does.

## Limitations

- **Synthetic fixtures only.** It has been tested on seven synthetic logs and a handful of one-line cases. Real logs vary more, and the rules will miss failures they were not written for. Those come out as `unknown`.
- **Over-redaction.** The redactor is cautious by design, so long paths, ARNs and S3 keys can be replaced by `[REDACTED:high-entropy]`. This hides useful detail, for example in the AWS fixture.
- **Line numbers** refer to the cleaned log. A redacted multi-line private key shifts them. Within a GitHub step they will not match the numbers in the web UI.
- **One error.** Only the first error in the failing step of each job is analysed. Cascading failures, matrix builds and failures in setup steps are not handled specially.
- **Not a full injection defence.** Injection detection is pattern-based, and a cleverly worded line may not be flagged. The real protection is that the tool has no write access and the evidence check only allows lines that exist in the log.
- **Model quality varies.** A small local model can repeat itself, give vague next checks, or question a correct category. In the recorded demo, several causes rest on the same quoted line and several next checks repeat the rules' checks. Language-model output varies between runs, even at temperature 0.
- **No Jenkins API client yet.** Save the console output to a file and use `--file`.
- **No PR comments.** Output goes to stdout. In Actions, append it to `$GITHUB_STEP_SUMMARY`. GitHub-hosted runners have no local model, so the example uses `--rules-only`.
- **Hand-written responses.** The recorded responses in `examples/recorded/` were written by hand to test the checks. They are not real model output. The real run is in the demo file.

## Demo

[`examples/demo-output.md`](examples/demo-output.md) has one real run with `qwen3:8b` on the npm dependency failure (a version range that does not exist) and the Docker out-of-disk failure, including the causes the evidence check dropped. `tests/golden/npm-dependency-recorded.md` is the expected report for the offline end-to-end test.

## Licence

MIT. See [LICENSE](LICENSE). Security reports: see [SECURITY.md](SECURITY.md).
