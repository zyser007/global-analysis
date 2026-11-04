#!/usr/bin/env bash
# Rebuild the page and run every check, printing only a short summary (full logs in /tmp/verify/).
#
#   bash editor-agent/verify.sh "$BASE" "$DATE" [--e2e]
#
# Takes about 1-3 minutes without --e2e. In the Managed Agents sandbox (/mnt/session exists) the summary is also
# written to /mnt/session/outputs/verify.txt and the full check.py output to /mnt/session/outputs/check.txt,
# which is what the outcome grader reads.
#
# Gates (any failure -> "VERIFY: FAIL", exit 1, do not publish to main):
#   build      tools/splice_gold.py + tools/build.py
#   check      editor-agent/check.py --all --base BASE --run-date DATE  (0 errors)
#   pytest     updater/tests + editor-agent/tests; a failure that also happens at BASE is reported as
#              PRE-EXISTING (not caused by this run) and does not block
#   visual     editor-agent/visual_check.py (0 errors)
# Informational, only with --e2e (never blocks, takes several minutes): editor-agent/e2e.sh.
set -u
BASE="${1:?usage: verify.sh BASE DATE [--e2e]}"
DATE="${2:?usage: verify.sh BASE DATE [--e2e]}"
E2E="${3:-}"
cd "$(dirname "$0")/.." || exit 2
LOG=/tmp/verify
rm -rf "$LOG"; mkdir -p "$LOG"
OUT=""; if [ -d /mnt/session ]; then OUT=/mnt/session/outputs; mkdir -p "$OUT"; fi

run_checks() {
  local fail=() code bcode n START
  START=$(date +%s)
  echo "verify.sh BASE=$BASE DATE=$DATE ($(date -u +%Y-%m-%dT%H:%MZ))"

  # ---- build
  if python3 -I tools/splice_gold.py >"$LOG/build.log" 2>&1; then
    if ! git diff --quiet -- tools/template.html; then
      git checkout -q -- tools/template.html
      echo "NOTE    splice_gold.py changed tools/template.html (out of sync with gold_module.js on main): reverted it; open an issue"
    fi
    if python3 -I tools/build.py >>"$LOG/build.log" 2>&1; then echo "build   OK"; else echo "build   FAIL: $(tail -2 "$LOG/build.log" | tr '\n' ' ')"; fail+=(build); fi
  else
    echo "build   FAIL: $(tail -2 "$LOG/build.log" | tr '\n' ' ')"; fail+=(build)
  fi

  # ---- check.py
  python3 -I editor-agent/check.py --all --base "$BASE" --run-date "$DATE" >"$LOG/check.log" 2>&1
  code=$?
  echo "check   $(tail -1 "$LOG/check.log")"
  grep -E '^ERROR' "$LOG/check.log" | head -20 | sed 's/^/        /'
  grep -E '^WARN' "$LOG/check.log" | grep -v 'e2e suite expects' | head -8 | sed 's/^/        /'
  [ "$code" = 0 ] || fail+=(check)

  # ---- pytest (compare with BASE on failure)
  python3 -m pytest updater/tests editor-agent/tests -q -p no:cacheprovider >"$LOG/pytest.log" 2>&1
  code=$?
  echo "pytest  $(tail -1 "$LOG/pytest.log")"
  if [ "$code" != 0 ]; then
    grep -E '^FAILED|^ERROR' "$LOG/pytest.log" | head -10 | sed 's/^/        /'
    local wt="$LOG/base-tree"
    if git worktree add -q --detach "$wt" "$BASE" >/dev/null 2>&1; then
      (cd "$wt" && python3 -m pytest updater/tests editor-agent/tests -q -p no:cacheprovider >"$LOG/pytest-base.log" 2>&1)
      bcode=$?
      git worktree remove --force "$wt" >/dev/null 2>&1
      if [ "$bcode" != 0 ]; then
        echo "        PRE-EXISTING: the same suite also fails at BASE (not caused by this run; open/comment an issue, does not block)"
      else
        echo "        CAUSED BY THIS RUN: the suite passes at BASE; fix the data (read only the FAILED lines above)"
        fail+=(pytest)
      fi
    else
      echo "        could not create a BASE worktree to compare; treating as blocking"; fail+=(pytest)
    fi
  fi

  # ---- visual check
  python3 -I editor-agent/visual_check.py >"$LOG/visual.log" 2>&1
  code=$?
  echo "visual  $(tail -1 "$LOG/visual.log")"
  grep -E '^(ERROR|WARN)' "$LOG/visual.log" | head -12 | sed 's/^/        /'
  [ "$code" = 0 ] || fail+=(visual)

  # ---- e2e (informational, opt-in)
  if [ "$E2E" = "--e2e" ]; then
    bash editor-agent/e2e.sh >"$LOG/e2e.log" 2>&1
    code=$?
    case "$code" in
      0) echo "e2e     OK (informational)";;
      3) echo "e2e     SKIPPED: no usable Chromium for @playwright/test (environment, informational)";;
      2) echo "e2e     SKIPPED: npm ci failed (informational)";;
      *) n=$(grep -cE '^\s+[0-9]+\) ' "$LOG/e2e.log"); echo "e2e     $n failing test(s) (informational; list them in the run log)"
         grep -E '^\s+[0-9]+\) ' "$LOG/e2e.log" | head -12 | sed 's/^ */        /' | cut -c1-160;;
    esac
  else
    echo "e2e     not run (add --e2e; informational only)"
  fi

  echo "time    $(( $(date +%s) - START )) s"
  if [ "${#fail[@]}" = 0 ]; then echo "VERIFY: PASS"; return 0; fi
  echo "VERIFY: FAIL (${fail[*]}) - full logs in $LOG/"
  return 1
}

run_checks 2>&1 | tee "$LOG/summary.txt"
status=${PIPESTATUS[0]}
if [ -n "$OUT" ]; then cp "$LOG/summary.txt" "$OUT/verify.txt"; cp "$LOG/check.log" "$OUT/check.txt" 2>/dev/null; fi
exit "$status"
