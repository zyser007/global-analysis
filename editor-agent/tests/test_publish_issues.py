"""publish.sh, issue.py, open_issues.py, the three.js copy check and the build placeholders.
Hermetic: throwaway git repos with a local bare remote, a fake GitHub API on 127.0.0.1, fixture data."""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import pathlib
import shutil
import socketserver
import subprocess
import sys
import threading

import pytest

HERE = pathlib.Path(__file__).resolve().parent
EA = HERE.parent
FIX = HERE / "fixtures"
REPO = EA.parent
DATE = "2026-11-05"
ENV = dict(os.environ, EDITOR_OUTPUT_DIR="", PATH=str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")


def sh(cwd, *args, check=True):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=ENV)
    if check:
        assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r


@pytest.fixture()
def clone(tmp_path):
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    (work / "data").mkdir(parents=True)
    (work / "site").mkdir()
    (work / "editor-agent" / "runs").mkdir(parents=True)
    shutil.copy(FIX / "world-data.json", work / "data" / "world-data.json")
    shutil.copy(FIX / "gold.json", work / "data" / "gold.json")
    (work / "site" / "index.html").write_text("<!doctype html>page v1\n")
    for name in ("check.py", "publish.sh", "issue.py", "open_issues.py"):
        shutil.copy(EA / name, work / "editor-agent" / name)
    (work / ".github" / "workflows").mkdir(parents=True)
    (work / ".github" / "workflows" / "agent-issues.yml").write_text("name: x\n")
    sh(work, "git", "init", "-q", "-b", "main")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-q", "-m", "base")
    sh(work, "git", "remote", "add", "origin", str(remote))
    sh(work, "git", "push", "-q", "origin", "main")
    return work, remote


def edit_data(work):
    p = work / "data" / "world-data.json"
    p.write_text(p.read_text(encoding="utf-8").replace('"sample": false', '"sample": false', 1) + "\n", encoding="utf-8")
    (work / "editor-agent" / "runs" / ("%s.md" % DATE)).write_text("# สรุป\n", encoding="utf-8")


# ----------------------------------------------------------------------------- publish.sh
def test_publish_branch_keeps_working_tree(clone):
    work, remote = clone
    edit_data(work)
    head = sh(work, "git", "rev-parse", "HEAD").stdout.strip()
    before = sh(work, "git", "status", "--porcelain").stdout
    out = sh(work, "bash", "editor-agent/publish.sh", "branch", DATE, "data-blocked", "why").stdout
    assert "PUSHED branch agent/%s-data-blocked" % DATE in out
    assert sh(work, "git", "rev-parse", "HEAD").stdout.strip() == head            # still on the same commit
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    assert sh(work, "git", "status", "--porcelain").stdout == before              # edits still uncommitted
    br = "agent/%s-data-blocked" % DATE
    files = sh(remote, "git", "ls-tree", "-r", "--name-only", br).stdout.split()
    assert "editor-agent/runs/%s.md" % DATE in files
    # same topic again: one more commit on top of the branch, no "name taken"
    (work / "editor-agent" / "runs" / ("%s.md" % DATE)).write_text("# สรุป 2\n", encoding="utf-8")
    out = sh(work, "bash", "editor-agent/publish.sh", "branch", DATE, "data-blocked", "again").stdout
    assert "PUSHED branch" in out
    assert sh(remote, "git", "rev-list", "--count", "main.." + br).stdout.strip() == "2"
    assert sh(remote, "git", "show", "%s:editor-agent/runs/%s.md" % (br, DATE)).stdout == "# สรุป 2\n"
    # and the same edits can still go to main afterwards
    out = sh(work, "bash", "editor-agent/publish.sh", "main", DATE, "chore(editor): update", "body").stdout
    assert "PUBLISHED main" in out


def test_publish_main_rebases_over_a_bot_push(clone, tmp_path):
    work, remote = clone
    bot = tmp_path / "bot"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(bot))
    (bot / "site" / "data").mkdir(parents=True)
    (bot / "site" / "data" / "status.json").write_text("{}\n")
    sh(bot, "git", "add", "-A")
    sh(bot, "git", "commit", "-q", "-m", "chore(data): bot")
    sh(bot, "git", "push", "-q", "origin", "main")
    edit_data(work)
    out = sh(work, "bash", "editor-agent/publish.sh", "main", DATE, "chore(editor): update", "body").stdout
    assert "PUBLISHED main" in out
    assert sh(remote, "git", "log", "--format=%s", "-2", "main").stdout.split("\n")[:2] == ["chore(editor): update", "chore(data): bot"]


def test_publish_refuses_files_outside_scope(clone):
    work, _ = clone
    edit_data(work)
    (work / "editor-agent" / "check.py").write_text((work / "editor-agent" / "check.py").read_text() + "\n# x\n")
    r = sh(work, "bash", "editor-agent/publish.sh", "main", DATE, "s", "b", check=False)
    assert r.returncode == 1 and "REFUSED" in r.stdout


# ----------------------------------------------------------------------------- issue.py -> branch, open_issues.py -> API
def test_issue_queues_file_on_branch_without_touching_the_tree(clone, tmp_path):
    work, remote = clone
    edit_data(work)
    before = sh(work, "git", "status", "--porcelain").stdout
    body = tmp_path / "i.md"
    body.write_text("รายละเอียด\n", encoding="utf-8")
    out = sh(work, sys.executable, "-I", "editor-agent/issue.py", "--date", DATE, "--title", "ทดสอบ", "--body-file", str(body)).stdout
    assert out.startswith("ISSUE-QUEUED agent/%s-issues editor-agent/issues/%s-issue-" % (DATE, DATE)) and "GitHub Actions" in out
    out2 = sh(work, sys.executable, "-I", "editor-agent/issue.py", "--date", DATE, "--title", "second one", "--body-file", str(body)).stdout
    assert "%s-second-one.md" % DATE in out2
    assert sh(work, "git", "status", "--porcelain").stdout == before
    br = "agent/%s-issues" % DATE
    files = sh(remote, "git", "ls-tree", "-r", "--name-only", br).stdout.split()
    assert len([f for f in files if f.startswith("editor-agent/issues/")]) == 2
    assert ".github/workflows/agent-issues.yml" in files          # the branch carries main's workflow
    out3 = sh(work, sys.executable, "-I", "editor-agent/issue.py", "--date", DATE, "--title", "second one", "--body-file", str(body)).stdout
    assert "unchanged, already queued" in out3


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    issues: list = []
    calls: list = []

    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self.calls.append(("GET", self.path, self.headers.get("Authorization")))
        if "/issues?" in self.path:
            return self.reply(200, self.issues if "page=1" in self.path else [])
        if self.path.endswith("/labels/editor-agent"):
            return self.reply(404, {"message": "Not Found"})
        self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(("POST", self.path, body))
        if self.path.endswith("/issues"):
            n = len(self.issues) + 1
            issue = {"number": n, "title": body["title"], "body": body["body"], "state": "open", "html_url": "x/%d" % n}
            self.issues.append(issue)
            return self.reply(201, issue)
        if self.path.endswith("/comments"):
            return self.reply(201, {"html_url": "c"})
        if self.path.endswith("/labels"):
            return self.reply(201, {})
        self.reply(404, {})


@pytest.fixture()
def fake_api():
    FakeGitHub.issues, FakeGitHub.calls = [], []
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeGitHub)   # no getfqdn() (slow on macOS)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def run_open(work, api, before, after):
    env = dict(ENV, GITHUB_TOKEN="test-token", GITHUB_REPOSITORY="o/r", GITHUB_API_URL=api, BEFORE=before, AFTER=after,
               BRANCH="agent/%s-issues" % DATE)
    r = subprocess.run([sys.executable, "-I", "editor-agent/open_issues.py"], cwd=work, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


def test_open_issues_creates_once_and_comments_on_change(clone, fake_api):
    work, _ = clone
    d = work / "editor-agent" / "issues"
    d.mkdir()
    (d / ("%s-a.md" % DATE)).write_text("# [editor-agent] เรื่อง A\n\nเนื้อหา A\n", encoding="utf-8")
    (d / ("%s-b.md" % DATE)).write_text("# [editor-agent] เรื่อง B\n\nเนื้อหา B\n", encoding="utf-8")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-q", "-m", "issues")
    first = sh(work, "git", "rev-parse", "HEAD").stdout.strip()
    code, out = run_open(work, fake_api, "0" * 40, first)                     # new branch
    assert code == 0, out
    assert [i["title"] for i in FakeGitHub.issues] == ["[editor-agent] เรื่อง A", "[editor-agent] เรื่อง B"]
    assert all("<!-- editor-agent-issue: editor-agent/issues/" in i["body"] for i in FakeGitHub.issues)
    assert ("POST", "/repos/o/r/labels", {"name": "editor-agent", "color": "5319e7", "description": "Opened by the editor agent"}) in FakeGitHub.calls
    assert all(c[2] == "Bearer test-token" for c in FakeGitHub.calls if c[0] == "GET")
    # re-push without changes: nothing new
    code, out = run_open(work, fake_api, first, first)
    assert code == 0 and len(FakeGitHub.issues) == 2 and out.count("skip") == 2
    # file A changed in the next push -> comment on its issue, B untouched
    (d / ("%s-a.md" % DATE)).write_text("# [editor-agent] เรื่อง A\n\nเนื้อหา A ใหม่\n", encoding="utf-8")
    sh(work, "git", "commit", "-qam", "update a")
    second = sh(work, "git", "rev-parse", "HEAD").stdout.strip()
    code, out = run_open(work, fake_api, first, second)
    assert code == 0 and "commented on #1" in out and len(FakeGitHub.issues) == 2
    # a new file whose title matches an open issue -> comment, not a duplicate
    (d / "2026-11-06-a.md").write_text("# [editor-agent] เรื่อง B\n\nยังเป็นอยู่\n", encoding="utf-8")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-qm", "again")
    code, out = run_open(work, fake_api, second, sh(work, "git", "rev-parse", "HEAD").stdout.strip())
    assert code == 0 and "commented on #2 for editor-agent/issues/2026-11-06-a.md" in out and len(FakeGitHub.issues) == 2


def test_open_issues_dry_run_without_token(clone):
    work, _ = clone
    d = work / "editor-agent" / "issues"
    d.mkdir()
    (d / "x.md").write_text("# T\n\nB\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "editor-agent/open_issues.py", "--dry-run"], cwd=work, capture_output=True, text=True, env=ENV)
    assert r.returncode == 0 and "would create editor-agent/issues/x.md" in r.stdout


def test_workflow_file():
    wf = (REPO / ".github" / "workflows" / "agent-issues.yml").read_text(encoding="utf-8")
    assert 'branches: ["agent/*-issues"]' in wf
    assert "issues: write" in wf and "contents: read" in wf
    assert "python3 -I editor-agent/open_issues.py" in wf and "secrets.GITHUB_TOKEN" in wf


# ----------------------------------------------------------------------------- visual check helper, build placeholders
def test_visual_sandbox_detection(monkeypatch):
    spec = importlib.util.spec_from_file_location("vc", EA / "visual_check.py")
    vc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vc)
    monkeypatch.setenv("VISUAL_IGNORE_HTTPS_ERRORS", "1")
    assert vc.in_sandbox() is True
    monkeypatch.delenv("VISUAL_IGNORE_HTTPS_ERRORS")
    assert vc.in_sandbox() == (pathlib.Path("/opt/pw-browsers").is_dir() and pathlib.Path("/mnt/session").is_dir())


def test_build_requires_placeholders(tmp_path):
    root = tmp_path / "r"
    (root / "tools").mkdir(parents=True)
    (root / "data").mkdir()
    for f in ("build.py", "template.html", "land_dots.json", "live_indicators.json"):
        shutil.copy(REPO / "tools" / f, root / "tools" / f)
    shutil.copy(FIX / "world-data.json", root / "data" / "world-data.json")
    shutil.copy(FIX / "gold.json", root / "data" / "gold.json")
    r = subprocess.run([sys.executable, "-I", "tools/build.py"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (root / "site" / "index.html").read_text(encoding="utf-8")
    assert "__WORLD_DATA__" not in html and '"label":"น้ำมันดิบ Brent"' in html
    tpl = root / "tools" / "template.html"
    assert '"updated":"2026-10-31"' not in tpl.read_text(encoding="utf-8")       # no stale copy of the data
    tpl.write_text(tpl.read_text(encoding="utf-8").replace("__WORLD_DATA__", '{"meta":{}}'), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "tools/build.py"], cwd=root, capture_output=True, text=True)
    assert r.returncode != 0 and "__WORLD_DATA__" in (r.stderr + r.stdout)


def test_outputs_only_when_asked(clone, tmp_path):
    work, _ = clone
    edit_data(work)
    out = tmp_path / "outputs"
    env = dict(ENV, EDITOR_OUTPUT_DIR=str(out))
    r = subprocess.run(["bash", "editor-agent/publish.sh", "branch", DATE, "x", "y"], cwd=work, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "PUSHED branch" in (out / "publish.txt").read_text()
    body = tmp_path / "b.md"
    body.write_text("b\n")
    subprocess.run([sys.executable, "-I", "editor-agent/issue.py", "--date", DATE, "--title", "t", "--body-file", str(body)],
                   cwd=work, capture_output=True, text=True, env=env, check=True)
    assert "ISSUE-QUEUED" in (out / "issues.txt").read_text()
    # with EDITOR_OUTPUT_DIR="" (how every test runs) nothing is written anywhere
    (out / "publish.txt").unlink(); (out / "issues.txt").unlink()
    subprocess.run(["bash", "editor-agent/publish.sh", "branch", DATE, "z", "y"], cwd=work, capture_output=True, text=True, env=ENV, check=True)
    assert not (out / "publish.txt").exists() and os.environ.get("EDITOR_OUTPUT_DIR") == ""
