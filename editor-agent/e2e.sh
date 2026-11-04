#!/usr/bin/env bash
# Run the repository's Playwright suite (e2e/) inside the Managed Agents cloud sandbox.
#
# The sandbox ships its own Chromium in /opt/pw-browsers (PLAYWRIGHT_BROWSERS_PATH), but e2e/ pins
# @playwright/test 1.56.1, which looks for its own browser revision. When that revision is not there,
# this script points Playwright at a temporary folder whose entries link the pinned revision names to
# the pre-installed Chromium. Nothing is downloaded except the npm packages of e2e/package-lock.json.
#
# Exit codes: 0 = suite passed, 1 = tests failed (read the output), 2 = npm install failed,
#             3 = no usable browser (environment problem, not a test result).
# Usage: bash editor-agent/e2e.sh [extra playwright args, e.g. tests/globe.spec.js]
set -uo pipefail
cd "$(dirname "$0")/../e2e" || exit 2

if ! PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund --loglevel=error; then
  echo "e2e.sh: npm ci failed" >&2; exit 2
fi

src="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
want=$(node -e 'const p=require("path"),fs=require("fs");const f=p.join(p.dirname(require.resolve("playwright-core/package.json")),"browsers.json");const b=JSON.parse(fs.readFileSync(f)).browsers;const g=n=>(b.find(x=>x.name===n)||{}).revision;console.log(g("chromium")+" "+g("chromium-headless-shell"))')
read -r rev_full rev_shell <<<"$want"
echo "e2e.sh: @playwright/test wants chromium-$rev_full / chromium_headless_shell-$rev_shell; browsers in $src:"
ls -1 "$src" 2>/dev/null | sed 's/^/  /'

if [ -d "$src/chromium-$rev_full" ] && [ -d "$src/chromium_headless_shell-$rev_shell" ]; then
  export PLAYWRIGHT_BROWSERS_PATH="$src"
else
  shim=$(mktemp -d /tmp/pw-shim.XXXXXX)
  pick() { ls -1d "$src"/$1 2>/dev/null | sort -V | tail -1; }
  full=$(pick 'chromium-[0-9]*'); [ -n "$full" ] || full=$(pick 'chromium')
  shell=$(pick 'chromium_headless_shell-[0-9]*')
  [ -n "$full" ] && ln -s "$full" "$shim/chromium-$rev_full"
  [ -n "$shell" ] && ln -s "$shell" "$shim/chromium_headless_shell-$rev_shell"
  for f in "$src"/ffmpeg-*; do [ -e "$f" ] && ln -s "$f" "$shim/$(basename "$f")"; done
  export PLAYWRIGHT_BROWSERS_PATH="$shim"
  echo "e2e.sh: using shim $shim -> ${full:-none} / ${shell:-none}"
fi

if ! timeout 60 node -e 'require("@playwright/test").chromium.launch({args:["--use-gl=angle","--use-angle=swiftshader"]}).then(b=>b.close()).catch(e=>{console.error(String(e).slice(0,600));process.exit(1)})'; then
  echo "e2e.sh: no usable Chromium for @playwright/test (environment problem, exit 3)" >&2
  exit 3
fi

npx playwright test --reporter=line "$@"
code=$?
echo "e2e.sh: playwright exit code $code"
[ "$code" = 0 ] && exit 0 || exit 1
