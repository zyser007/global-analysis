#!/usr/bin/env python3
"""Open (or comment on) a GitHub issue for the owner, printing only the outcome.

  python3 -I editor-agent/issue.py --date "$DATE" --title "[editor-agent] ..." --body-file /tmp/issue.md

- Uses the GitHub REST API on zyser007/global-analysis with no Authorization header: the Managed Agents git
  proxy adds the repository token. Label: editor-agent.
- If an open editor-agent issue with the same title exists, it adds the body as a comment instead.
- If the API cannot be used (HTTP 401/403/404/5xx or no connection), it writes the issue as
  editor-agent/issues/<DATE>-<slug>.md on branch agent/<DATE>-issues (through a separate worktree, so the
  working tree on main is not touched) and pushes that branch.
Prints one line: "ISSUE <url>", "COMMENTED <url>" or "ISSUE-FALLBACK <branch> <file> (api: <reason>)".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = "zyser007/global-analysis"
API = "https://api.github.com/repos/%s" % REPO
ROOT = pathlib.Path(__file__).resolve().parent.parent


def curl(method: str, url: str, body: dict | None = None) -> tuple[int, object]:
    cmd = ["curl", "-sS", "-m", "30", "-o", "-", "-w", "\n%{http_code}", "-X", method, url,
           "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(body, ensure_ascii=False)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return 0, r.stderr.strip()[:200]
    text, _, code = r.stdout.rpartition("\n")
    try:
        return int(code), json.loads(text) if text.strip() else None
    except (ValueError, json.JSONDecodeError):
        return int(code) if code.isdigit() else 0, text[:200]


def git(*args: str, cwd: pathlib.Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def fallback(date: str, title: str, body: str, reason: str) -> int:
    plain = title.replace("[editor-agent]", "")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:40] or "issue-" + hashlib.sha1(plain.encode("utf-8")).hexdigest()[:8]
    branch = "agent/%s-issues" % date
    rel = "editor-agent/issues/%s-%s.md" % (date, slug)
    wt = pathlib.Path(tempfile.mkdtemp(prefix="issue-wt-")) / "wt"
    git("fetch", "-q", "origin")
    exists = git("ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0
    if exists:
        git("fetch", "-q", "origin", "%s:refs/remotes/origin/%s" % (branch, branch))
        r = git("worktree", "add", "-q", "-B", branch, str(wt), "origin/%s" % branch)
    else:
        r = git("worktree", "add", "-q", "-b", branch, str(wt), "origin/main")
    if r.returncode != 0:
        print("ISSUE-FAILED could not create a worktree for %s: %s (api: %s)" % (branch, r.stderr.strip()[:200], reason))
        return 1
    try:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# %s\n\n%s\n" % (title, body.strip()), encoding="utf-8")
        git("add", rel, cwd=wt)
        git("commit", "-q", "-m", "chore(editor): issue note %s" % title[:60], cwd=wt)
        r = git("push", "-q", "-u", "origin", branch, cwd=wt)
        if r.returncode != 0:
            print("ISSUE-FAILED push of %s: %s (api: %s)" % (branch, r.stderr.strip()[:200], reason))
            return 1
        print("ISSUE-FALLBACK %s %s (api: %s)" % (branch, rel, reason))
        return 0
    finally:
        git("worktree", "remove", "--force", str(wt))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    a = ap.parse_args(argv)
    title = a.title if a.title.startswith("[editor-agent]") else "[editor-agent] " + a.title
    body = pathlib.Path(a.body_file).read_text(encoding="utf-8")

    code, data = curl("GET", API + "/issues?state=open&labels=editor-agent&per_page=100")
    if code != 200 or not isinstance(data, list):
        return fallback(a.date, title, body, "list HTTP %s %s" % (code, str(data)[:80] if code != 200 else ""))
    same = [i for i in data if i.get("title") == title and "pull_request" not in i]
    if same:
        code, res = curl("POST", API + "/issues/%d/comments" % same[0]["number"], {"body": body})
        if code == 201 and isinstance(res, dict):
            print("COMMENTED %s" % res.get("html_url"))
            return 0
        return fallback(a.date, title, body, "comment HTTP %s" % code)
    code, res = curl("POST", API + "/issues", {"title": title, "body": body, "labels": ["editor-agent"]})
    if code == 201 and isinstance(res, dict):
        print("ISSUE %s" % res.get("html_url"))
        return 0
    return fallback(a.date, title, body, "create HTTP %s" % code)


if __name__ == "__main__":
    sys.exit(main())
