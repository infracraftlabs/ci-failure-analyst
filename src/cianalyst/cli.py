"""cianalyst: explain a failed CI job from its log. Read-only; prints a report."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, render
from .analyse import JobAnalysis, analyse, pick_provider, prepare
from .github import GitHubClient, GitHubError


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cianalyst",
        description="Find the failing step and first error in a CI log, classify it, and explain "
                    "likely causes with quoted evidence. Read-only: it never re-runs, comments or changes anything.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="A GitHub Actions or Jenkins log file ('-' for stdin).")
    src.add_argument("--github", metavar="OWNER/REPO",
                     help="Fetch failed jobs of a workflow run (needs --run and GITHUB_TOKEN with Actions: read).")
    p.add_argument("--run", type=int, help="Workflow run id, with --github.")
    p.add_argument("--max-jobs", type=int, default=3, help="Analyse at most this many failed jobs (default 3).")
    p.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    p.add_argument("--rules-only", action="store_true", help="Skip the model; rules and excerpt only.")
    p.add_argument("--model", help="Ollama model (default: env OLLAMA_MODEL or qwen3:8b).")
    p.add_argument("--recorded", metavar="PATH", help="Replay a recorded model response (tests and offline demos).")
    p.add_argument("--window", type=int, default=80, help="Lines kept around the first error (default 80).")
    p.add_argument("--version", action="version", version=f"cianalyst {__version__}")
    return p


def _read_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.github and args.run is None:
        print("cianalyst: --github needs --run <id>", file=sys.stderr)
        return 2

    provider, warning = pick_provider(args.rules_only, args.recorded, args.model)
    if warning:
        print(f"cianalyst: {warning}", file=sys.stderr)

    analyses: list[JobAnalysis] = []
    extra: dict = {}
    if args.file:
        try:
            raw = _read_file(args.file)
        except OSError as e:
            print(f"cianalyst: cannot read {args.file}: {e.strerror}", file=sys.stderr)
            return 2
        name = "stdin" if args.file == "-" else Path(args.file).name
        analyses.append(analyse(prepare(raw, name, window_size=args.window), provider))
    else:
        try:
            client = GitHubClient(os.environ.get("GITHUB_TOKEN", ""))
            try:
                jobs = client.failed_jobs(args.github, args.run)
                extra = {"repository": args.github, "run_id": args.run, "failed_jobs": len(jobs)}
                if not jobs:
                    print(f"cianalyst: no failed jobs in run {args.run}.", file=sys.stderr)
                for job in jobs[: max(1, args.max_jobs)]:
                    raw = client.job_log(args.github, job.id)
                    p = prepare(raw, f"{args.github} run {args.run} job {job.id}", job=job.name,
                                step_hint=job.failed_step, window_size=args.window)
                    analyses.append(analyse(p, provider))
            finally:
                client.close()
        except GitHubError as e:
            print(f"cianalyst: {e}", file=sys.stderr)
            return 1

    if args.json:
        sys.stdout.write(render.to_json(analyses, extra))
    elif analyses:
        header = None
        if extra.get("failed_jobs", 0) > len(analyses):
            header = f"_{extra['failed_jobs']} failed jobs; showing the first {len(analyses)}._"
        sys.stdout.write(render.markdown(analyses, header))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
