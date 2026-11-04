#!/usr/bin/env python3
"""Queue a GitHub issue for the owner, printing only the outcome.

  python3 -I editor-agent/issue.py --date "$DATE" --title "[editor-agent] ..." --body-file /tmp/issue.md

The REST API cannot be used from the sandbox (the git proxy does not add the token to REST calls: 403 rate
limit), so this writes the issue as editor-agent/issues/<DATE>-<slug>.md and pushes it to branch
agent/<DATE>-issues. The workflow .github/workflows/agent-issues.yml then opens it as a real issue labelled
editor-agent with GITHUB_TOKEN (one issue per file; a changed file becomes a comment; an open issue with the same
title gets a comment instead of a duplicate).

The commit is built from origin/main plus the issue files already on that branch, with plumbing commands only:
HEAD, the index and the working tree are not touched. Same date + same title = same file (its update becomes a
comment). Prints: "ISSUE-QUEUED <branch> <file> ..." or "ISSUE-FAILED ...".
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ISSUES_DIR = "editor-agent/issues"


def git(*args: str, env: dict | None = None, inp: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, env=env, input=inp)


def slug_for(title: str) -> str:
    plain = title.replace("[editor-agent]", "")
    s = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:40]
    return s or "issue-" + hashlib.sha1(plain.strip().encode("utf-8")).hexdigest()[:8]


def report(line: str) -> None:
    """Print the outcome; in the Managed Agents sandbox also append it to /mnt/session/outputs/issues.txt."""
    print(line)
    if pathlib.Path("/mnt/session").is_dir():
        out = pathlib.Path("/mnt/session/outputs")
        out.mkdir(parents=True, exist_ok=True)
        with (out / "issues.txt").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def queue(date: str, title: str, body: str, remote: str = "origin") -> int:
    branch = "agent/%s-issues" % date
    rel = "%s/%s-%s.md" % (ISSUES_DIR, date, slug_for(title))
    text = "# %s\n\n%s\n" % (title, body.strip())

    r = git("fetch", "-q", remote, "+refs/heads/main:refs/remotes/%s/main" % remote)
    if r.returncode != 0:
        report("ISSUE-FAILED cannot fetch %s/main: %s" % (remote, r.stderr.strip()[:200]))
        return 1
    git("fetch", "-q", remote, "+refs/heads/%s:refs/remotes/%s/%s" % (branch, remote, branch))
    tip = git("rev-parse", "-q", "--verify", "refs/remotes/%s/%s" % (remote, branch)).stdout.strip()

    idx = pathlib.Path(tempfile.mkdtemp(prefix="issue-idx-")) / "index"
    env = dict(os.environ, GIT_INDEX_FILE=str(idx))
    steps = [git("read-tree", "refs/remotes/%s/main" % remote, env=env)]   # current main: workflow + scripts
    if tip:  # keep the issue files already queued on the branch
        for line in git("ls-tree", "-r", tip, "--", ISSUES_DIR).stdout.splitlines():
            meta, path = line.split("\t", 1)
            mode, _, sha = meta.split()
            steps.append(git("update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, sha, path), env=env))
    blob = git("hash-object", "-w", "--stdin", inp=text).stdout.strip()
    steps.append(git("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, rel), env=env))
    tree = git("write-tree", env=env).stdout.strip()
    bad = [s for s in steps if s.returncode != 0]
    if bad or not tree:
        report("ISSUE-FAILED could not build the commit: %s" % (bad[0].stderr.strip()[:200] if bad else "no tree"))
        return 1
    if tip and git("rev-parse", tip + "^{tree}").stdout.strip() == tree:
        report("ISSUE-QUEUED %s %s (unchanged, already queued)" % (branch, rel))
        return 0
    parents = ["-p", tip] if tip else ["-p", "refs/remotes/%s/main" % remote]
    c = git("commit-tree", tree, *parents, "-m", "chore(editor): queue issue %s" % title[:60])
    if c.returncode != 0:
        report("ISSUE-FAILED commit-tree: %s" % c.stderr.strip()[:200])
        return 1
    commit = c.stdout.strip()
    p = git("push", "-q", remote, "%s:refs/heads/%s" % (commit, branch))
    if p.returncode != 0:
        report("ISSUE-FAILED push of %s: %s" % (branch, p.stderr.strip()[:200]))
        return 1
    report("ISSUE-QUEUED %s %s - GitHub Actions (agent-issues.yml) will open it as an issue labelled editor-agent" % (branch, rel))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--remote", default="origin")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        ap.error("--date must be YYYY-MM-DD")
    title = a.title if a.title.startswith("[editor-agent]") else "[editor-agent] " + a.title
    return queue(a.date, title, pathlib.Path(a.body_file).read_text(encoding="utf-8"), a.remote)


if __name__ == "__main__":
    sys.exit(main())
