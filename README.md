# CopyManga EPUB Downloader

[English](README.md) | [简体中文](README.zh-CN.md)

An unofficial CopyManga / 拷贝漫画 downloader and fixed-layout EPUB workflow for local CLI use and agent skills.

<p>
  <img src="https://img.shields.io/badge/Source-CopyManga-16a34a?style=flat-square" alt="CopyManga" />
  <img src="https://img.shields.io/badge/Output-EPUB%20%7C%20Omnibus%20%7C%20Volumes-7c3aed?style=flat-square" alt="Output" />
  <img src="https://img.shields.io/badge/Agent%20Skill-CLI%20First-2563eb?style=flat-square" alt="Agent Skill" />
  <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="License" />
</p>

## Features

- Search CopyManga by title or `comic_id`
- Download chapter images
- Build per-chapter fixed-layout EPUB files
- Build merged omnibus EPUB files
- Split long series into volume EPUBs
- Resume partial downloads with `--resume`
- Validate EPUB structure, page counts, and fixed-layout metadata
- Publish final files into a stable local `library/`
- Optional external library layout: `分章/`, `合订本/完整版.epub`, `历史备份/`

## Installation

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git
cd manga-loader-skill
python3 scripts/manga_loader.py bootstrap
```

Requirements:

- Python 3.11+
- Linux or a Linux-like shell environment
- Network access to the CopyManga API
- Rust/Cargo only when the bundled downloader binary cannot run on your platform

The repository root is also the agent skill directory. To install it as a local Codex skill:

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git \
  ~/.codex/skills/manga-loader
```

Use a full clone. Sparse installers may miss `scripts/`, `vendor/`, or other required directories.

## Usage

```bash
# Health check
python3 scripts/manga_loader.py doctor --check-network

# Search
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"

# Download and build EPUB output
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲"

# Smoke test with one chapter
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --chapter-limit 1

# Resume an incomplete run
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --resume

# Build split volumes
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲" \
  --split-chapters-per-volume 40

# Create a subscription and run it once
python3 scripts/manga_loader.py subscribe --query "葬送的芙莉莲" --run-now

# Refresh all enabled subscriptions
python3 scripts/manga_loader.py subscriptions run --all
```

CopyManga search usually works best with Chinese titles or a known `comic_id`.

## EPUB Checks

```bash
# Validate EPUB structure
python3 scripts/manga_loader.py validate-epub \
  --path "library/<title>/merged/<file>.epub"

# Compare chapter pages with merged or split outputs
python3 scripts/manga_loader.py compare-pages \
  --chapter-epub-dir "library/<title>/chapters" \
  --merged "library/<title>/merged/<file>.epub"

# Audit fixed-layout comic metadata
python3 scripts/epub_audit.py --path "library/<title>/merged/<file>.epub"

# Repeated validation for large EPUB files
python3 scripts/epub_pressure.py --path "library/<title>/merged/<file>.epub"
```

## Rebuild

```bash
# Rebuild a merged EPUB from existing chapter EPUBs
python3 scripts/manga_loader.py rebuild-merged \
  --chapter-epub-dir "library/<title>/chapters" \
  --output "library/<title>/merged/<title> 合订版.epub" \
  --title "<title>" \
  --author "<author>"

# Rebuild split volumes
python3 scripts/manga_loader.py rebuild-split \
  --chapter-epub-dir "library/<title>/chapters" \
  --output-dir "library/<title>/volumes" \
  --title "<title>" \
  --author "<author>" \
  --chapters-per-volume 40
```

## Output Layout

```text
library/<title>/
  chapters/
  merged/
  volumes/
  series.json

runs/<job-name>/
  downloads/
  epubs/
  merged/
  volumes/
  report.json

state/subscriptions.json
```

- `library/`: stable reading output
- `runs/`: intermediate data and debug reports
- `state/`: subscription state

Local runtime directories are not committed. A fresh clone creates its own `config/settings.json`, `runs/`, `library/`, and `state/` during setup and use.

## External Library Publishing

Set `publish.mangabooks_root` in `config/settings.json`, then run:

```bash
python3 scripts/manga_loader.py publish-library --title "<title>"
```

Output:

```text
<mangabooks_root>/<title>/
  分章/
  合订本/完整版.epub
  历史备份/
```

## Agent Skill

This repository includes `SKILL.md` for Codex, Claude Code, and other local agents. The stable public entry point is:

```bash
python3 scripts/manga_loader.py <subcommand>
```

Agents should use `report.json`, `validation.valid`, and `audit.reader_ready` to decide whether a run succeeded.

## Configuration

`bootstrap` creates `config/settings.json` from `config/settings.example.json`.

Main sections:

- `downloader`: API domain, retry policy, and concurrency
- `packaging`: EPUB naming, KCC profile, reading direction, split policy
- `publish`: external library root, merged filename, archive policy

## Testing

```bash
python3 -m unittest discover -s tests
```

## Upstream References

This workflow builds on and references:

- [Kindle Comic Converter (KCC)](https://github.com/ciromattia/kcc) for comic-oriented EPUB conventions
- [copymanga-downloader](https://github.com/lanyeeee/copymanga-downloader) for CopyManga download behavior
- [MangaEpubAutomation](https://github.com/YuxuanHan0326/MangaEpubAutomation) for manga-to-EPUB workflow ideas

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for license notes.

## Disclaimer

This project is not affiliated with CopyManga or any content provider. Use it only where you have the right to access and archive the content. Respect source-site terms, copyright law, and local regulations.

## License

[MIT](LICENSE)
