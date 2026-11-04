# Daily editor run - rubric

Grade each criterion from the session transcript (commands and their output) and from the files in /workspace/global-analysis and the memory store. DATE is the run's Asia/Bangkok date. A criterion that does not apply (for example "if data changed" when nothing changed) passes when the transcript shows why it does not apply.

1. **Health checked.** The transcript shows `editor-agent/check.py --live` output and the bot commits of the last ~26 hours; the final message states whether the live data is healthy. Any unhealthy finding has an `issue.py` result line (ISSUE / COMMENTED / ISSUE-FALLBACK).
2. **Changes recorded with sources.** Every data change went through `editor-agent/apply_changes.py` (output line `apply_changes: OK`), so `editor-agent/runs/DATE.changes.json` lists each changed item with source URL and published date.
3. **No invented or undated content.** Every source URL in the patches appeared in a web_search result or a web_fetch in this session. Changed texts are Thai (proper nouns may be English), neutral, and put an explicit date next to events; no new conflict id was added on main.
4. **Verified.** The transcript shows `editor-agent/verify.sh` ending in `VERIFY: PASS` after the last data change (pytest failures marked PRE-EXISTING and e2e failures may remain and are mentioned in the run summary).
5. **Published within limits.** Either `PUBLISHED main <sha>` from `publish.sh main` after that VERIFY: PASS; or, when verify kept failing, `PUSHED branch agent/DATE-...` plus an issue; or nothing changed and only the run summary was published. No `git stash`, `reset`, `checkout -- <file>`, `restore`, `clean`, force push or edits to code, tests or tooling appear in the transcript.
6. **Context discipline.** No command printed a whole data file, `site/data/*.json`, `check.py`, tests, `tools/`, `e2e/` or schema source; items were read with `brief.py` / `show.py`.
7. **Run summary written.** `editor-agent/runs/DATE.md` exists in the published commit (or branch), in Thai, with what changed (links), what was reviewed without change, live-data health, e2e note, issues/branches.
8. **Memory updated.** The memory store's `runs/DATE.md` no longer says only IN PROGRESS: it has outcome, SHA or branch, items changed, searches/fetches used, verify summary and problems; other memory files updated when this run learned something. No secret in memory.
9. **Search budget respected.** At most 30 web_search and 15 web_fetch calls, stated in the final message.
10. **Final message.** In Thai, at most 20 lines, with DATE, result and SHA (or branch), number and keys of changed items, the verify.sh summary lines, live-data health, issue/branch URLs and decisions waiting for the owner.
