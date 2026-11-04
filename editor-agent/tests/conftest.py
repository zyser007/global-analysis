"""Shared test setup: no test may ever write into a Managed Agents session's /mnt/session/outputs.

publish.sh, issue.py and verify.sh write their results to $EDITOR_OUTPUT_DIR, defaulting to /mnt/session/outputs
inside the sandbox; an empty value turns that off. Set it here, before any test starts a subprocess.
(Run 3 found lines from these tests - branch names with 2026-11-05 - in its publish.txt and issues.txt.)"""
import os

os.environ["EDITOR_OUTPUT_DIR"] = ""
