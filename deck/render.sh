#!/usr/bin/env bash
# HTML 管線: HTML → PDF（headless Chrome。Playwright 不要）
# Usage: ./render.sh html/demo.html out/demo_html.pdf
set -euo pipefail
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
IN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
          --print-to-pdf="$OUT" "file://$IN" 2>/dev/null
echo "saved: $OUT"
pdfinfo "$OUT" | grep -E "Pages|Page size"
pdffonts "$OUT" | head -5   # 日本語フォントが emb=yes か確認（design §0）
