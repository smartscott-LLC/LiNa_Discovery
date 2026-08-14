#!/usr/bin/env python3
"""hf_fetch.py — fetch a file from HuggingFace using the token in the repo's .env.

The token is read from ``HUGGING_FACE_ACCESS_TOKEN`` in ``.env`` (or the
environment) so it never appears in argv, shell history, or process lists.

Usage:
    python hf_fetch.py <repo>                     # list the repo's files
    python hf_fetch.py <repo> <filename> [dest]   # stream one file to disk
"""
from __future__ import annotations

import os
import pathlib
import sys
import urllib.error
import urllib.request

API = "https://huggingface.co/api/models/{repo}"
RESOLVE = "https://huggingface.co/{repo}/resolve/main/{filename}"


def _token() -> str:
    env = os.getenv("HUGGING_FACE_ACCESS_TOKEN", "")
    if env:
        return env
    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("HUGGING_FACE_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _open(url: str):
    req = urllib.request.Request(url)
    token = _token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=60)


def list_files(repo: str) -> None:
    with _open(API.format(repo=repo)) as resp:
        import json
        data = json.load(resp)
    for sib in sorted(data.get("siblings", []), key=lambda s: s["rfilename"]):
        print(sib["rfilename"])


def fetch(repo: str, filename: str, dest: str | None) -> None:
    url = RESOLVE.format(repo=repo, filename=filename)
    target = pathlib.Path(dest) if dest else pathlib.Path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    resume_from = tmp.stat().st_size if tmp.exists() else 0
    req = urllib.request.Request(url)
    token = _token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if resume_from:
        req.add_header("Range", f"bytes={resume_from}-")
        sys.stderr.write(f"resuming {filename} from {resume_from/1e6:.1f} MB\n")
    mode = "ab" if resume_from else "wb"
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, mode) as out:
        total = resume_from + int(resp.headers.get("Content-Length") or 0)
        done = resume_from
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // max(total, 1)
                sys.stderr.write(f"\r{filename}: {done/1e6:.1f}/{total/1e6:.1f} MB ({pct}%)")
                sys.stderr.flush()
    sys.stderr.write("\n")
    tmp.rename(target)
    print(f"saved {target} ({done/1e6:.1f} MB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    repo = sys.argv[1]
    try:
        if len(sys.argv) == 2:
            list_files(repo)
        else:
            fetch(repo, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        sys.exit(1)
