#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="$SCRIPT_DIR/manga_loader.py"
JOB_NAME="${1:-manga-loader-verify}"
QUERY="${2:-葬送的芙莉莲}"
CHAPTER_LIMIT="${3:-1}"

python3 "$ENTRYPOINT" bootstrap
python3 "$ENTRYPOINT" doctor --check-network
python3 "$ENTRYPOINT" subscribe --query "$QUERY" --run-now --chapter-limit "$CHAPTER_LIMIT"
python3 "$ENTRYPOINT" subscriptions list
python3 "$ENTRYPOINT" download-full --query "$QUERY" --job-name "$JOB_NAME" --chapter-limit "$CHAPTER_LIMIT"
python3 "$ENTRYPOINT" validate-epub \
  --path "$SCRIPT_DIR/../runs/$JOB_NAME/merged/omnibus.epub"
