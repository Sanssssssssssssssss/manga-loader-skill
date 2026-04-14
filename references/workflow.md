# Workflow

## 核心流程

这个 skill 的主链路是：

1. `bootstrap`
2. `search`
3. `subscribe --run-now` 或 `download-full`
4. 生成单章 EPUB
5. 生成合订本 EPUB
6. `validate-epub`

## 运行资产

项目内自带三类资产：

1. 下载器
- `vendor/bin/copymanga-headless-rs`
- `vendor/copymanga-headless-rs-src/`

2. 打包脚本
- `scripts/simple_epub.py`
- `scripts/merge_epub.py`

3. 合订本重建脚本
- `vendor/postprocess/make_merge_plan.py`
- `vendor/postprocess/merge_epub_by_order.py`

## 目录约定

```text
config/
  settings.json
  settings.example.json

library/<漫画名>/
  chapters/
  merged/
  series.json

runs/<job-name>/
  downloads/
  epubs/
  merged/
  report.json

state/
  subscriptions.json
```

## 排查顺序

1. `python3 scripts/manga_loader.py doctor`
2. 看 `runs/<job>/report.json`
3. 看 `python3 scripts/manga_loader.py validate-epub --path <file>`
4. 检查 `state/subscriptions.json`

## 常见问题

### 1. 新环境直接运行失败

先执行：

```bash
python3 scripts/manga_loader.py bootstrap
```

### 2. 找不到下载器

项目会优先使用：

- `vendor/bin/copymanga-headless-rs`

如果该二进制不适配当前平台，会尝试从：

- `vendor/copymanga-headless-rs-src`

本地构建。

### 3. EPUB 结构异常

用：

```bash
python3 scripts/manga_loader.py validate-epub --path <epub-path>
```

看这些字段：

- `xml_errors`
- `missing_spine_refs`
- `missing_manifest_hrefs`

### 4. 订阅已经存在但没有更新

先看：

- `state/subscriptions.json`
- 对应 `runs/subscriptions/<subscription-id>/report.json`

再手动执行：

```bash
python3 scripts/manga_loader.py subscriptions run --subscription <subscription-id>
```
