#!/usr/bin/env python3
"""Run by .github/workflows/agent-issues.yml on pushes to agent/*-issues: turn each
editor-agent/issues/*.md file of the pushed commit into a GitHub issue labelled editor-agent.

- File format: first line "# <title>", the rest is the body (written by editor-agent/issue.py).
- De-duplication: every issue body carries the marker <!-- editor-agent-issue: <path> -->. A file whose marker is
  already on an issue (open or closed) is skipped, unless the file changed in this push - then its new text is
  added as a comment. A file with a new path whose title equals an OPEN editor-agent issue becomes a comment on it.
- Environment: GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo), optional GITHUB_API_URL, BEFORE / AFTER (push
  range, from github.event), BRANCH. --dry-run prints the actions without writing anything.
Stdlib only. Prints one line per file.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

ISSUES_DIR = "editor-agent/issues"
LABEL = "editor-agent"
MARK = "<!-- editor-agent-issue: %s -->"
ZERO = re.compile(r"^0+$")


class Api:
    def __init__(self, base: str, repo: str, token: str):
        self.base, self.repo, self.token = base.rstrip("/"), repo, token

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        url = "%s/repos/%s%s" % (self.base, self.repo, path)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer %s" % self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "editor-agent-issues"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8")
                return r.status, json.loads(txt) if txt else None
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:300]


def changed_files(root: pathlib.Path, before: str, after: str) -> set[str] | None:
    """Files under ISSUES_DIR changed in this push; None when the range is unknown (new branch)."""
    if not before or ZERO.match(before) or not after:
        return None
    r = subprocess.run(["git", "diff", "--name-only", before, after, "--", ISSUES_DIR], cwd=root, capture_output=True, text=True)
    return set(r.stdout.split()) if r.returncode == 0 else None


def parse(path: pathlib.Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    first, _, rest = text.partition("\n")
    title = first.lstrip("#").strip() or path.stem
    return title[:250], rest.strip()


def existing(api: Api) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 11):
        code, data = api.call("GET", "/issues?state=all&labels=%s&per_page=100&page=%d" % (LABEL, page))
        if code != 200 or not isinstance(data, list):
            raise RuntimeError("listing issues failed: HTTP %s %s" % (code, str(data)[:200]))
        out += [i for i in data if "pull_request" not in i]
        if len(data) < 100:
            break
    return out


def run(root: pathlib.Path, api: Api | None, before: str, after: str, branch: str, dry: bool) -> int:
    files = sorted((root / ISSUES_DIR).glob("*.md"))
    if not files:
        print("no issue files in %s" % ISSUES_DIR)
        return 0
    changed = changed_files(root, before, after)
    issues = existing(api) if api else []
    by_mark = {}
    for i in issues:
        m = re.search(r"<!-- editor-agent-issue: (\S+) -->", i.get("body") or "")
        if m:
            by_mark.setdefault(m.group(1), i)
    open_by_title = {i.get("title"): i for i in issues if i.get("state") == "open"}
    label_ok = dry or api is None
    failed = 0
    for f in files:
        rel = f.relative_to(root).as_posix()
        title, body = parse(f)
        footer = "\n\n---\nQueued by the editor agent on branch `%s`, file `%s`.\n%s" % (branch or "?", rel, MARK % rel)
        hit = by_mark.get(rel)
        if hit:
            if changed is not None and rel in changed:
                action, target = "comment", hit
            else:
                print("skip %s: already issue #%s" % (rel, hit.get("number")))
                continue
        elif title in open_by_title:
            action, target = "comment", open_by_title[title]
        else:
            action, target = "create", None
        if dry or api is None:
            print("would %s %s%s" % (action, rel, " on #%s" % target.get("number") if target else ""))
            continue
        if action == "comment":
            code, res = api.call("POST", "/issues/%s/comments" % target["number"], {"body": body + footer})
            ok = code == 201
            print(("commented on #%s for %s" % (target["number"], rel)) if ok else ("FAILED comment for %s: HTTP %s %s" % (rel, code, str(res)[:200])))
        else:
            if not label_ok:
                code, _ = api.call("GET", "/labels/%s" % LABEL)
                if code == 404:
                    api.call("POST", "/labels", {"name": LABEL, "color": "5319e7", "description": "Opened by the editor agent"})
                label_ok = True
            code, res = api.call("POST", "/issues", {"title": title, "body": body + footer, "labels": [LABEL]})
            ok = code == 201
            if ok:
                by_mark[rel] = res
                open_by_title[title] = res
            print(("opened #%s for %s" % (res.get("number"), rel)) if ok else ("FAILED create for %s: HTTP %s %s" % (rel, code, str(res)[:200])))
        failed += 0 if ok else 1
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    api = Api(os.environ.get("GITHUB_API_URL", "https://api.github.com"), repo, token) if token and repo else None
    if api is None and not a.dry_run:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY are required (or use --dry-run)")
        return 2
    try:
        return run(pathlib.Path(a.root).resolve(), api, os.environ.get("BEFORE", ""), os.environ.get("AFTER", ""),
                   os.environ.get("BRANCH", ""), a.dry_run)
    except RuntimeError as e:
        print("ERROR %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
