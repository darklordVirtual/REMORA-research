#!/usr/bin/env bash
# Render paper/experiments_explained.html to paper/experiments_explained.pdf
# with headless Chrome or Chromium. Set CHROME to override the binary.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
src="$root/paper/experiments_explained.html"
out="$root/paper/experiments_explained.pdf"
chrome="${CHROME:-}"
if [[ -z "$chrome" ]]; then
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome chromium chromium-browser; do
    if command -v "$c" >/dev/null 2>&1 || [[ -x "$c" ]]; then chrome="$c"; break; fi
  done
fi
[[ -n "$chrome" ]] || { echo "No Chrome or Chromium found; set CHROME." >&2; exit 2; }
"$chrome" --headless=new --disable-gpu --no-pdf-header-footer \
  --virtual-time-budget=10000 --print-to-pdf="$out" "file://$src" 2>/dev/null
echo "wrote $out"
