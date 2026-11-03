#!/usr/bin/env bash
# Copies the WoWHub brand kit (nav.js, brand.css, apps.json, favicon) from a
# pinned commit of anom0ly/wowhubnet into site/wowhub/, so the dashboard only
# runs code that is reviewed in this repo. Rerun it when the brand kit changes,
# and commit the result:
#
#   scripts/vendor-wowhub.sh ../wowhubnet            # that clone's HEAD
#   scripts/vendor-wowhub.sh ../wowhubnet <commit>
#
# nav.js finds apps.json next to itself, which stays true here. Its links to
# the hub would point at this site instead of wowhub.net, so that one line is
# rewritten; the script stops if the line has changed upstream.
set -euo pipefail

src=${1:?usage: $0 <path to a wowhubnet clone> [commit]}
rev=$(git -C "$src" rev-parse --verify "${2:-HEAD}^{commit}")
out=$(cd "$(dirname "$0")/.." && pwd)/site/wowhub
mkdir -p "$out"

for f in nav.js brand.css apps.json assets/favicon.svg; do
  git -C "$src" show "$rev:public/$f" > "$out/$(basename "$f")"
done

line="var hubUrl = new URL('./', base).href;"
if ! grep -qF "$line" "$out/nav.js"; then
  echo "nav.js no longer has the hub link line; update this script." >&2
  exit 1
fi
sed -i.bak "s|var hubUrl = new URL('./', base).href;|var hubUrl = 'https://wowhub.net/';  // vendored copy: the hub stays on wowhub.net|" "$out/nav.js"
rm -f "$out/nav.js.bak"

printf 'anom0ly/wowhubnet %s\n' "$rev" > "$out/SOURCE"
echo "Copied the brand kit from wowhubnet $rev into site/wowhub/."
