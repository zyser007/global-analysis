# Known issues (seeded 2026-11-04 by the setup, before the first run)

- e2e/ hard-codes data values and counts (e.g. 25 conflicts, 21 economies, 20 tiles, '$3,903', 'ณ 2 พ.ย.', 'แนวรับ 3,850'). After a data update those assertions fail although the page is fine. Treat such failures as expected, list them in the run log, keep ONE open issue asking to make e2e data-driven. editor-agent/visual_check.py is the data-driven gate.
- data chokepoints have no sources[] field and gold.json `sources` holds publisher names only: the URLs and dates for these live only in editor-agent/runs/<DATE>.changes.json.
- Headlines link to conflict ids through the enum in updater/schema/headlines.schema.json (plus pseudo ids economy, world, disaster, thailand). Never remove or rename a conflict id; a new id needs an issue to extend that enum (code change, not main).
- Not yet verified on a real run: (1) whether GitHub REST calls such as POST /issues work through the git proxy without an Authorization header - if not, use the branch fallback and write the HTTP code here; (2) whether e2e.sh finds a usable Chromium for @playwright/test 1.56.1 (exit 3 = no).
- tools/splice_gold.py rewrites tools/template.html; if that produces a diff on main, revert it, rebuild with tools/build.py only, and open an issue.
