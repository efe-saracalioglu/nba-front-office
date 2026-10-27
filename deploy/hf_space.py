from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SKIP = ("docs/", "evals/results/", ".github/", "infra/", "models/notebooks/", "reports/", "deploy/")
FRONT_MATTER = """---
title: Front Office
emoji: 🏀
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 8501
pinned: false
short_description: AI analysts that propose CBA-legal NBA trades
---

# Front Office demo

A team of AI analysts that proposes NBA trades. A deterministic CBA rules engine certifies every package, a
LightGBM model values the players, and you approve or reject each proposal as the general manager.

This Space runs on a small sample of the warehouse and allows {limit} requests per session.
{repo}"""


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if not f.startswith(SKIP)]


def stage(target: Path, limit: int, repo: str) -> int:
    files = tracked_files()
    for f in files:
        dest = target / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, dest)
    project_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    (target / "PROJECT_README.md").write_text(project_readme, encoding="utf-8")
    link = f"Source code, evals and the full write-up: {repo}\n" if repo else ""
    (target / "README.md").write_text(FRONT_MATTER.format(limit=limit, repo=link), encoding="utf-8")
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the demo as a Hugging Face Docker Space")
    parser.add_argument("space", help="owner/name of the Space, e.g. efesaracalioglu/front-office")
    parser.add_argument("--limit", type=int, default=3, help="Requests allowed per browser session")
    parser.add_argument("--repo", default="", help="Link to the source repository")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Stage the files and stop")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    with tempfile.TemporaryDirectory() as tmp:
        n = stage(Path(tmp), args.limit, args.repo)
        print(f"staged {n} files in {tmp}")
        if args.dry_run:
            for p in sorted(Path(tmp).rglob("*"))[:40]:
                print(" ", p.relative_to(tmp))
            return
        api = HfApi(token=os.environ.get("HF_TOKEN"))
        api.create_repo(
            args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True
        )
        api.add_space_variable(args.space, "FRONT_OFFICE_DEMO_LIMIT", str(args.limit))
        key = os.environ.get("OLLAMA_API_KEY")
        if key:
            api.add_space_secret(args.space, "OLLAMA_API_KEY", key)
        else:
            print("OLLAMA_API_KEY is not set; add it as a Space secret before using the demo")
        api.upload_folder(folder_path=tmp, repo_id=args.space, repo_type="space",
                          commit_message="Deploy Front Office demo", delete_patterns=["*"])  # fmt: skip
    print(f"https://huggingface.co/spaces/{args.space}")


if __name__ == "__main__":
    main()
