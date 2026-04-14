# copymanga-headless-rs

`copymanga-headless-rs` is a headless Rust CLI that reuses the upstream `copymanga-downloader` download core instead of reimplementing downloader behavior from scratch.

This app is intended for Linux-first environments such as WSL and Raspberry Pi.

## What it preserves from upstream

- fixed API request headers
- API retry middleware
- image retry middleware
- status `210` risk-control handling
- account pool persistence in `account.json`
- auto-registration when no usable account exists
- `limited_at` cooldown behavior for risk-limited accounts
- chapter retry loop with randomized waits
- chapter/image pacing controls
- `.c800x.` to `.c1500x.` image URL upgrade

## Commands

From the repo root:

```bash
cargo run --manifest-path apps/copymanga-headless-rs/Cargo.toml -- search "炎炎" --json
cargo run --manifest-path apps/copymanga-headless-rs/Cargo.toml -- comic yanyanzhixiaofangdui --json
cargo run --manifest-path apps/copymanga-headless-rs/Cargo.toml -- chapters yanyanzhixiaofangdui --group default --json
```

Download one group:

```bash
cargo run --manifest-path apps/copymanga-headless-rs/Cargo.toml -- \
  --chapter-concurrency 1 \
  --image-concurrency 2 \
  --chapter-interval-sec 1 \
  --image-interval-sec 1 \
  download-group yanyanzhixiaofangdui \
  --group default \
  --output-root runs/rust-headless-smoke/downloads \
  --limit 1 \
  --max-images 2 \
  --skip-existing
```

## Output layout

Downloaded pages are written as:

```text
<output-root>/
  <comic-name>/
    <group-name>/
      0001 <chapter-name>/
        001.webp
        002.webp
```

This output layout is intentionally compatible with the existing EPUB postprocess stage under `apps/manga-pipeline-lite/postprocess/`.

## State

By default, runtime state is stored under the local data directory:

```text
<local-data-dir>/mangaloader-epub-postprocess/copymanga-headless-rs/
  account.json
```

You can override this with `--state-dir`.

## Raspberry Pi notes

- This app is headless only.
- It requires a Rust toolchain to build locally.
- It is the correct path when you need downloader behavior to stay operationally close to upstream.
- `apps/manga-pipeline-lite` now uses this downloader as its default backend.
