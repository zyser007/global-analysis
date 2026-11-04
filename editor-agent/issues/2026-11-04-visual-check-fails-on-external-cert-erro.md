# [editor-agent] visual check fails on external cert error; data on branch agent/2026-11-04-data-blocked

## What
`editor-agent/verify.sh` for 2026-11-04 ended `VERIFY: FAIL (visual)`. The only errors (4, one per viewport) are `console: Failed to load resource: net::ERR_CERT_AUTHORITY_INVALID`. three.js is served from the curl copy (INFO line), so another external resource fails with a certificate error in the sandbox. check.py: 0 errors, 0 warnings; pytest: 188 passed, 2 skipped.

## Evidence
- /tmp/verify/visual.log: four `ERROR <viewport>: console: Failed to load resource: net::ERR_CERT_AUTHORITY_INVALID`, no URL printed.
- The data changes (22 items) pass check and pytest, so the failure is not from the data.

## Result
Per the rules the update was pushed to branch `agent/2026-11-04-data-blocked` (8a0247d), not to main.

## Proposal / needed from the owner
1. Have visual_check.py print the failing URL and serve or ignore every external asset (fonts, CDNs) like three.js.
2. Review and merge the branch (or tell me to publish to main after the fix).
3. Decision: Black Sea chokepoint (index 3) is level 2; CNN (3 Nov) reports Russian drones struck >=12 merchant ships in recent weeks, killing more seafarers than the Iran war. Consider level 3.
