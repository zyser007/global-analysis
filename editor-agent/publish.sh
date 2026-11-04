#!/usr/bin/env bash
# Commit this run's allowed files and push them, printing only the outcome.
#
#   bash editor-agent/publish.sh main   "$DATE" "subject" "body"      -> commit to main, push (rebase on conflict)
#   bash editor-agent/publish.sh branch "$DATE" "topic"   "body"      -> commit to agent/$DATE-<topic>, push the
#                                                                         branch, return to main (main is untouched)
# Only these paths are ever added: data/world-data.json data/gold.json site/index.html
# editor-agent/runs/$DATE.md editor-agent/runs/$DATE.changes.json. Never force-pushes.
set -u
MODE="${1:?usage: publish.sh main|branch DATE subject|topic body}"
DATE="${2:?}"; SUBJ="${3:?}"; BODY="${4:-}"
cd "$(dirname "$0")/.." || exit 2
FILES=(data/world-data.json data/gold.json site/index.html "editor-agent/runs/$DATE.md" "editor-agent/runs/$DATE.changes.json")
add_files() { for f in "${FILES[@]}"; do [ -e "$f" ] && git add -- "$f"; done; }

if ! python3 -I editor-agent/check.py --scope-only --base HEAD >/tmp/publish-scope.log 2>&1; then
  echo "publish: REFUSED - files outside the allowed paths are changed:"; grep '^ERROR' /tmp/publish-scope.log | head -10
  echo "(leave them alone and report them; do not reset or stash)"; exit 1
fi

if [ "$MODE" = main ]; then
  [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "publish: not on main"; exit 1; }
  add_files
  if git diff --cached --quiet; then echo "publish: nothing to commit"; exit 0; fi
  git commit -q -m "$SUBJ" ${BODY:+-m "$BODY"} || { echo "publish: commit failed"; exit 1; }
  for i in 1 2 3; do
    if git push -q origin HEAD:main 2>/tmp/publish-push.log; then
      git fetch -q origin
      if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
        echo "PUBLISHED main $(git rev-parse --short HEAD)"; exit 0
      fi
    fi
    echo "publish: push rejected (attempt $i), rebasing on origin/main"
    if ! git pull -q --rebase origin main >/tmp/publish-rebase.log 2>&1; then
      git rebase --abort >/dev/null 2>&1
      echo "publish: FAILED - rebase conflict: $(head -3 /tmp/publish-rebase.log | tr '\n' ' ')"; exit 1
    fi
    python3 -I tools/build.py >/dev/null 2>&1   # bot commits never touch data/, but keep the page in step
    if ! git diff --quiet -- site/index.html; then git add site/index.html && git commit -q -m "chore(editor): rebuild page after rebase"; fi
  done
  echo "publish: FAILED - could not push after 3 attempts: $(tail -2 /tmp/publish-push.log | tr '\n' ' ')"; exit 1
fi

if [ "$MODE" = branch ]; then
  topic=$(echo "$SUBJ" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//; s/-$//' | cut -c1-40)
  br="agent/$DATE-$topic"
  git switch -q -c "$br" || { echo "publish: cannot create $br"; exit 1; }
  add_files
  git commit -q -m "chore(editor): $SUBJ ($DATE, not published)" ${BODY:+-m "$BODY"} || { echo "publish: nothing to commit on $br"; git switch -q main; exit 1; }
  if git push -q -u origin "$br" 2>/tmp/publish-push.log; then
    echo "PUSHED branch $br $(git rev-parse --short HEAD)"; git switch -q main; exit 0
  fi
  echo "publish: FAILED to push $br: $(tail -2 /tmp/publish-push.log | tr '\n' ' ')"; git switch -q main; exit 1
fi
echo "usage: publish.sh main|branch DATE subject|topic body"; exit 2
