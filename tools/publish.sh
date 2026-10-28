#!/bin/bash
# Create the public GitHub repo, push the game and turn on GitHub Pages (run once, by the owner).
set -e
cd "$(dirname "$0")/.."
gh repo create BrendanJamesLynskey/Worth-Valley-Railway-Manager --public \
  --description "Heritage Railway Manager remade as the real Keighley & Worth Valley Railway, one to one from OpenStreetMap and elevation data" \
  --source . --push
gh api -X POST repos/BrendanJamesLynskey/Worth-Valley-Railway-Manager/pages -f "source[branch]=main" -f "source[path]=/" >/dev/null
echo "Pages starting: https://brendanjameslynskey.github.io/Worth-Valley-Railway-Manager/ (give it a minute or two)"
