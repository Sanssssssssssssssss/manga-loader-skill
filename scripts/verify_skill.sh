#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="$SCRIPT_DIR/manga_loader.py"
JOB_NAME="${1:-manga-loader-verify}"
QUERY="${2:-葬送的芙莉莲}"
CHAPTER_LIMIT="${3:-1}"
REPORT_JSON="$(mktemp)"

python3 "$ENTRYPOINT" bootstrap
python3 "$ENTRYPOINT" doctor --check-network
python3 "$ENTRYPOINT" subscribe --query "$QUERY" --run-now --chapter-limit "$CHAPTER_LIMIT"
python3 "$ENTRYPOINT" subscriptions list
python3 "$ENTRYPOINT" download-full --query "$QUERY" --job-name "$JOB_NAME" --chapter-limit "$CHAPTER_LIMIT" > "$REPORT_JSON"
MERGED_EPUB="$(python3 - <<'PY' "$REPORT_JSON"
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(payload["report"]["merged_epub"])
PY
)"
python3 "$ENTRYPOINT" validate-epub \
  --path "$MERGED_EPUB"
rm -f "$REPORT_JSON"
