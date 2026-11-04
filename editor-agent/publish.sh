#!/usr/bin/env bash
# Commit this run's allowed files and push them, printing only the outcome.
#
#   bash editor-agent/publish.sh main   "$DATE" "subject" "body"      -> commit to main, push (rebase on conflict)
#   bash editor-agent/publish.sh branch "$DATE" "topic"   "body"      -> commit a snapshot to agent/$DATE-<topic> and
#                                                                         push it; HEAD, index and working tree stay as
#                                                                         they are (edits remain uncommitted on main)
# Only these paths are ever added: data/world-data.json data/gold.json site/index.html
# editor-agent/runs/$DATE.md editor-agent/runs/$DATE.changes.json. Never force-pushes.
set -u
MODE="${1:?usage: publish.sh main|branch DATE subject|topic body}"
DATE="${2:?}"; SUBJ="${3:?}"; BODY="${4:-}"
cd "$(dirname "$0")/.." || exit 2
FILES=(data/world-data.json data/gold.json site/index.html "editor-agent/runs/$DATE.md" "editor-agent/runs/$DATE.changes.json")
# outcome lines also go to /mnt/session/outputs/publish.txt in the Managed Agents sandbox (read by the grader)
say() { echo "$*"; if [ -d /mnt/session ]; then mkdir -p /mnt/session/outputs; echo "$(date -u +%H:%MZ) $*" >> /mnt/session/outputs/publish.txt; fi; }
add_files() { for f in "${FILES[@]}"; do [ -e "$f" ] && git add -- "$f"; done; }

if ! python3 -I editor-agent/check.py --scope-only --base HEAD >/tmp/publish-scope.log 2>&1; then
  say "publish: REFUSED - files outside the allowed paths are changed:"; grep '^ERROR' /tmp/publish-scope.log | head -10
  echo "(leave them alone and report them; do not reset or stash)"; exit 1
fi

if [ "$MODE" = main ]; then
  [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "publish: not on main"; exit 1; }
  add_files
  if git diff --cached --quiet; then say "publish: nothing to commit"; exit 0; fi
  git commit -q -m "$SUBJ" ${BODY:+-m "$BODY"} || { echo "publish: commit failed"; exit 1; }
  for i in 1 2 3; do
    if git push -q origin HEAD:main 2>/tmp/publish-push.log; then
      git fetch -q origin
      if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
        say "PUBLISHED main $(git rev-parse --short HEAD)"; exit 0
      fi
    fi
    echo "publish: push rejected (attempt $i), rebasing on origin/main"
    if ! git pull -q --rebase origin main >/tmp/publish-rebase.log 2>&1; then
      git rebase --abort >/dev/null 2>&1
      say "publish: FAILED - rebase conflict: $(head -3 /tmp/publish-rebase.log | tr '\n' ' ')"; exit 1
    fi
    python3 -I tools/build.py >/dev/null 2>&1   # bot commits never touch data/, but keep the page in step
    if ! git diff --quiet -- site/index.html; then git add site/index.html && git commit -q -m "chore(editor): rebuild page after rebase"; fi
  done
  say "publish: FAILED - could not push after 3 attempts: $(tail -2 /tmp/publish-push.log | tr '\n' ' ')"; exit 1
fi

if [ "$MODE" = branch ]; then
  # Commit a snapshot of the allowed files to agent/$DATE-<topic> WITHOUT touching HEAD, the index or the working
  # tree: the agent stays on main with its uncommitted edits, and can publish them to main later or run again.
  # A second call with the same topic adds a commit on top of that branch.
  topic=$(echo "$SUBJ" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//; s/-$//' | cut -c1-40)
  br="agent/$DATE-$topic"
  idx=$(mktemp /tmp/publish-index.XXXXXX); rm -f "$idx"
  export GIT_INDEX_FILE="$idx"
  git read-tree HEAD || { echo "publish: read-tree failed"; exit 1; }
  for f in "${FILES[@]}"; do [ -e "$f" ] && git add -- "$f"; done
  tree=$(git write-tree)
  unset GIT_INDEX_FILE; rm -f "$idx"
  git fetch -q origin "+refs/heads/$br:refs/remotes/origin/$br" 2>/dev/null
  if parent=$(git rev-parse -q --verify "refs/remotes/origin/$br"); then :; else parent=$(git rev-parse HEAD); fi
  if [ "$(git rev-parse "$parent^{tree}")" = "$tree" ]; then say "publish: nothing new for $br"; exit 0; fi
  commit=$(git commit-tree "$tree" -p "$parent" -m "chore(editor): $SUBJ ($DATE, not published)" ${BODY:+-m "$BODY"}) || { echo "publish: commit-tree failed"; exit 1; }
  if git push -q origin "$commit:refs/heads/$br" 2>/tmp/publish-push.log; then
    git update-ref "refs/remotes/origin/$br" "$commit"
    say "PUSHED branch $br $(git rev-parse --short "$commit") (your working tree on $(git rev-parse --abbrev-ref HEAD) is unchanged)"; exit 0
  fi
  say "publish: FAILED to push $br: $(tail -2 /tmp/publish-push.log | tr '\n' ' ')"; exit 1
fi
echo "usage: publish.sh main|branch DATE subject|topic body"; exit 2
