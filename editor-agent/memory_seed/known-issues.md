# Known issues (seeded 2026-11-04 by the setup, before the first run)

- e2e/ hard-codes data values and counts (e.g. 25 conflicts, 21 economies, 20 tiles, '$3,903', 'ณ 2 พ.ย.', 'แนวรับ 3,850'). After a data update those assertions fail although the page is fine. Treat such failures as expected, list them in the run log, keep ONE open issue asking to make e2e data-driven. editor-agent/visual_check.py is the data-driven gate.
- data chokepoints have no sources[] field and gold.json `sources` holds publisher names only: the URLs and dates for these live only in editor-agent/runs/<DATE>.changes.json.
- Headlines link to conflict ids through the enum in updater/schema/headlines.schema.json (plus pseudo ids economy, world, disaster, thailand). Never remove or rename a conflict id; a new id needs an issue to extend that enum (code change, not main).
- GitHub REST from the sandbox: on 2026-11-04 an unauthenticated GET to api.github.com got 'API rate limit exceeded' (the proxy did not add the token). issue.py falls back to a file on branch agent/<DATE>-issues (ISSUE-FALLBACK); that is fine.
- Not yet verified on a real run: whether e2e.sh finds a usable Chromium for @playwright/test 1.56.1 (exit 3 = no; e2e never blocks).
- tools/splice_gold.py rewrites tools/template.html; verify.sh reverts such a diff itself and prints a NOTE - open an issue when you see it.
- Budget lesson (first test run 2026-11-04): printing whole data files and reading check.py/tests made the context ~190k tokens and the $3 budget ran out at step 5 with nothing pushed. Use brief.py / show.py / apply_changes.py / verify.sh only; never read code or tests; never git stash.
