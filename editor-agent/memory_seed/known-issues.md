# Known issues (seeded 2026-11-04 by the setup, before the first run)

- e2e/ runs on frozen fixture data (e2e/fixtures/), so data updates do not break it; it is not part of the daily verify. editor-agent/visual_check.py checks the page with today's data.
- data chokepoints have no sources[] field and gold.json `sources` holds publisher names only: the URLs and dates for these live only in editor-agent/runs/<DATE>.changes.json.
- Headlines link to conflict ids through the enum in updater/schema/headlines.schema.json (plus pseudo ids economy, world, disaster, thailand). Never remove or rename a conflict id; a new id needs an issue to extend that enum (code change, not main).
- GitHub REST does not work from the sandbox (the git proxy adds no token to REST calls). issue.py queues the issue as a file on branch agent/<DATE>-issues (ISSUE-QUEUED) and GitHub Actions (agent-issues.yml) opens it.
- e2e is not part of the daily verify (verify.sh --e2e runs it, informational only).
- The sandbox re-signs outgoing TLS: visual_check ignores HTTPS certificate errors there (only there) and still fails on real console/page errors and failed same-origin requests; every problem line names its URL.
- tools/splice_gold.py rewrites tools/template.html; verify.sh reverts such a diff itself and prints a NOTE - open an issue when you see it.
- Budget lesson (first test run 2026-11-04): printing whole data files and reading check.py/tests made the context ~190k tokens and the $3 budget ran out at step 5 with nothing pushed. Use brief.py / show.py / apply_changes.py / verify.sh only; never read code or tests; never git stash.
