from __future__ import annotations

import argparse
import subprocess
import sys
import time

PLAN = [
    ("exact", "full"),
    ("scenarios", "full"),
    ("scenarios", "single_agent"),
    ("scenarios", "no_devils_advocate"),
    ("scenarios", "small_models"),
    ("exact", "no_sql_correction"),
    ("exact", "single_agent"),
    ("exact", "small_models"),
]
RUNNERS = {"exact": "evals.runners.run_exact", "scenarios": "evals.runners.run_scenarios"}


def run(suite: str, config: str, retries: int, wait: int) -> bool:
    for attempt in range(1, retries + 1):
        cmd = [sys.executable, "-m", RUNNERS[suite], "--config", config]
        print(f"=== {suite}/{config} (attempt {attempt})", flush=True)
        if subprocess.run(cmd).returncode == 0:
            return True
        print(f"--- {suite}/{config} stopped; waiting {wait}s before resuming", flush=True)
        time.sleep(wait)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run every NBA-Bench suite and ablation, resuming after failures"
    )
    parser.add_argument("--only", nargs="*", help="suite/config pairs, e.g. scenarios/full")
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--wait", type=int, default=120)
    args = parser.parse_args()
    plan = [p for p in PLAN if not args.only or f"{p[0]}/{p[1]}" in args.only]
    failed = [f"{s}/{c}" for s, c in plan if not run(s, c, args.retries, args.wait)]
    print("done" if not failed else f"unfinished: {failed}")


if __name__ == "__main__":
    main()
