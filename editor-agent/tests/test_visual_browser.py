"""Opt-in browser test (needs Playwright for Python, Chromium and network for the CDN assets):
EDITOR_BROWSER_TESTS=1 python -m pytest editor-agent/tests/test_visual_browser.py
Proves that ignoring HTTPS certificate errors (sandbox mode) does not hide real page problems."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

EA = pathlib.Path(__file__).resolve().parents[1]
REPO = EA.parent

pytestmark = pytest.mark.skipif(os.environ.get("EDITOR_BROWSER_TESTS") != "1", reason="set EDITOR_BROWSER_TESTS=1")


def run_visual(site, tmp_path, sandbox=False):
    env = dict(os.environ, VISUAL_IGNORE_HTTPS_ERRORS="1" if sandbox else "0")
    r = subprocess.run([sys.executable, "-I", str(EA / "visual_check.py"), "--site", str(site), "--only", "desktop-light",
                        "--shots", str(tmp_path / "shots")], capture_output=True, text=True, timeout=240, env=env)
    return r.returncode, r.stdout


@pytest.mark.parametrize("sandbox", [False, True])
def test_clean_page_passes(tmp_path, sandbox):
    code, out = run_visual(REPO / "site", tmp_path, sandbox)
    assert code == 0, out
    assert ("certificate errors ignored" in out) == sandbox


@pytest.mark.parametrize("sandbox", [False, True])
def test_real_page_errors_still_fail(tmp_path, sandbox):
    site = tmp_path / "site"
    shutil.copytree(REPO / "site", site)
    p = site / "index.html"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "</body>", '<img src="does-not-exist.png" alt=""><script>console.error("injected console error");setTimeout(function(){throw new Error("injected page error")},100)</script></body>', 1),
        encoding="utf-8")
    code, out = run_visual(site, tmp_path, sandbox)
    assert code == 1
    assert "console: injected console error @ " in out and "pageerror: injected page error" in out
    assert "HTTP 404" in out and "does-not-exist.png" in out          # failed same-origin request
