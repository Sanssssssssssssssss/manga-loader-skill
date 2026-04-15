# Manga Loader Skill

一个面向通用 agent 和 CLI 用户的自包含漫画工作流仓库。

目标很单一：用户只需要给出漫画标题或 `comic_id`，系统就能在本地完成搜索、订阅、章节下载、单章 EPUB 打包、合订本 EPUB 打包，以及后续的结构校验、重建与分册组织。

当前内置的数据源适配器是 CopyManga。

## 这个仓库保证什么

- 单一公开入口：所有正式操作统一走 `scripts/manga_loader.py`
- 本地可运行：不依赖某个聊天平台、某个 webhook、某个专用 runtime
- 仓库自包含：下载器源码、预编译二进制、EPUB 打包脚本都放在仓库内
- 输出稳定：最终产物固定落到 `library/`，`runs/` 只保留调试和中间过程，重复执行默认覆盖稳定结果
- 可验证：内置 `doctor`、`validate-epub`、`scripts/epub_audit.py`、`scripts/epub_pressure.py`、`smoke_test.sh`、`verify_skill.sh`
- 易于被 agent 集成：输入清楚、命令清楚、输出路径清楚、排障路径清楚

这意味着它适合被发布成一个通用 skill，而不是绑定某个特定平台的“内部脚本”。

## 致谢

这个项目建立在优秀的开源工作之上。

特别感谢：

- Ciro Mattia Gonano 和 Pawel Jastrzebski，提供 Kindle Comic Converter（KCC）
- lanyeeee，提供 copymanga-downloader
- YuxuanHan0326，提供 MangaEpubAutomation

这些工作让这个轻量、实用的漫画工作流能更快落地。

## 适用场景

- 用户只知道漫画标题，想先搜索再下载
- 用户想长期订阅某部漫画，并定期刷新本地库
- 用户想同时拿到单章 EPUB 和合订本 EPUB
- 用户已经有单章 EPUB，想重新生成一个合订本
- 用户需要一个 agent 容易调用、容易 debug、结果落盘稳定的漫画技能仓库

## 新环境快速开始

### 1. 环境要求

- Python 3.11+
- 网络可访问 CopyManga API
- 当前最稳的是 Linux x86_64

这不是一个“纯 Python 包”。当前仓库的正式运行方式是：

```bash
python3 scripts/manga_loader.py bootstrap
```

而不是：

```bash
pip install .
```

原因很直接：

- Python 侧依赖很少，当前 `requirements.txt` 只需要 `Pillow`
- 但下载能力依赖仓库内自带的 `copymanga-headless-rs`
- 这个下载器是 Rust 项目，源码位于 `vendor/copymanga-headless-rs-src`

Rust / Cargo 不是“永远必装”，而是“平台相关依赖”：

- 如果仓库里的预编译 `vendor/bin/copymanga-headless-rs` 适配你的平台，可以不装 Rust
- 如果这个预编译二进制不适配当前平台，项目会在 `bootstrap` 时尝试用本地 `cargo build --release` 从源码构建
- 这时就必须有 Rust / Cargo

当前结论是：

- `requirements.txt` 只覆盖 Python 层依赖
- Rust 依赖由 vendored 下载器承担
- 仓库目前没有可作为正式安装入口的 `pyproject.toml`
- 所以“clone 后只装 Python 依赖就一定能跑通”这个说法并不准确

### 2. 初始化运行时

```bash
python3 scripts/manga_loader.py bootstrap
```

这一步会：

- 创建 `.runtime/python-venv`
- 安装 `requirements.txt` 中的最小 Python 依赖
- 准备 `copymanga-headless-rs` 运行二进制
- 在默认 `kcc_postprocess` 打包后端下准备本地 `KCC` 运行时
- 在缺省情况下生成 `config/settings.json`

### 3. 体检

```bash
python3 scripts/manga_loader.py doctor --check-network
```

### 4. 搜索漫画

```bash
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
```

### 5. 直接产出单章本和合订本

```bash
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲"
```

### 6. 建立订阅并立即产出

```bash
python3 scripts/manga_loader.py subscribe \
  --query "葬送的芙莉莲" \
  --run-now
```

后续更新：

```bash
python3 scripts/manga_loader.py subscriptions run --all
```

## 配置

这个 skill 的默认配置文件是 `config/settings.json`。

新环境首次执行 `bootstrap` 时，会自动根据 `config/settings.example.json` 生成它。

当前配置结构保持尽量简单，只暴露运行这个 skill 真正需要的几个维度：

```json
{
  "source": "copymanga",
  "default_group": "default",
  "language": "zh-Hans",
  "downloader": {
    "api_domain": "api.2025copy.com",
    "download_format": "webp",
    "api_retries": 5,
    "retry_base_sec": 1.0,
    "retry_jitter_sec": 0.5,
    "risk_wait_sec": 60.0,
    "chapter_concurrency": 1,
    "image_concurrency": 2,
    "chapter_interval_sec": 0.0,
    "image_interval_sec": 0.0
  },
  "packaging": {
    "backend": "kcc_postprocess",
    "chapter_name_template": "{series_title} {chapter_label}.epub",
    "merged_name_template": "{title} 合订版.epub",
    "split_name_template": "{title} 第{volume_index:02d}册.epub",
    "split_chapters_per_volume": 40,
    "reading_direction": "ltr",
    "kcc_cmd": "",
    "kcc_profile": "KS",
    "kcc_extra_args": [],
    "jpeg_quality": 90,
    "page_background": "#000000"
  }
}
```

字段说明：

- `source`：当前固定为 `copymanga`
- `default_group`：默认漫画分组，通常保持 `default`
- `language`：EPUB 语言标签，中文建议用 `zh-Hans` 或 `zh-Hant`
- `downloader.*`：下载节奏、重试和并发控制
- `packaging.backend`：打包后端，默认 `kcc_postprocess`，保留 `python_fixed` 作为 fallback
- `packaging.chapter_name_template`：章节 EPUB 文件名模板
- `packaging.merged_name_template`：合订本默认文件名模板
- `packaging.split_name_template`：分册 EPUB 文件名模板
- `packaging.split_chapters_per_volume`：默认每册章节上限
- `packaging.reading_direction`：`python_fixed` 后端使用的阅读方向
- `packaging.kcc_cmd`：显式指定系统里的 `kcc-c2e` 或 `comic2ebook`
- `packaging.kcc_profile`：KCC 设备配置，默认 `KS`
- `packaging.kcc_extra_args`：额外透传给 KCC 的参数
- `packaging.jpeg_quality`：EPUB 内部 JPEG 质量
- `packaging.page_background`：页面补边时使用的背景色

如果你想看更偏“工程流水线配置”的旧版说明，可以参考你原来的项目：

- `https://github.com/Sanssssssssssssssss/mangaloader-epub-postprocess`

但这个 skill 刻意没有沿用那套更重的 job 配置，而是收敛成更适合 agent 调用的单入口和轻配置模型。

## 分册合订

当前仓库的默认产物仍然是“单章 EPUB + 单本合订 EPUB”。如果某个系列特别长，推荐在上层 workflow 里采用“分册合订”，把同一系列拆成多个阅读上限更合理的册，而不是把所有章节硬塞进一个超大文件。

推荐切分规则是：

- 先按官方卷信息切分，如果源数据能提供
- 如果没有官方卷信息，优先按章节数切分
- 如果章节长度差异很大，再叠加文件大小上限
- 切分边界只落在章节边界，不切半章
- 默认保留一个可选的“全书合订版”，但不把它当成唯一交付物

推荐命名规则是：

- 单章：`<漫画名> <章节名>.epub`
- 分册：`<漫画名> 第XX册.epub`
- 总合订：`<漫画名> 全书合订版.epub`

如果后续把分册结果也写进 `report.json`，建议至少加这些字段：

- `split_strategy`
- `volume_count`
- `volumes[]`
- `total_size_bytes`
- `reader_ready`

这样 agent 能直接判断当前产物是单本、分册还是全集，不需要猜最终阅读文件。

## 体检、审计与压力测试

这套仓库里有四种常见检查，作用不一样，建议不要混用：

- `doctor`：检查运行时、依赖、仓库布局和网络连通性，回答“当前环境能不能跑”
- `compare-pages`：对账“单章页数”和“合并后页数”，回答“有没有丢页或多算封面页”
- `validate-epub`：检查单个 EPUB 的结构完整性，回答“这个文件是否坏了”
- `scripts/epub_audit.py`：对真实输出做语义审计，回答“这本书是不是漫画式 fixed-layout”
- `scripts/epub_pressure.py`：重复、多进程或大样本地反复审计，回答“这个产物是否稳定”

推荐顺序是：

1. 先 `doctor`
2. 再 `download-full`、`rebuild-merged` 或 `rebuild-split`
3. 如果怀疑页数不对，先跑 `compare-pages`
4. 再 `validate-epub`
5. 如果要确认阅读器语义，再跑 `scripts/epub_audit.py`
6. 如果要验证大书稳定性，再跑 `scripts/epub_pressure.py`

## Agent 集成契约

对 agent 来说，最重要的是不要“猜”脚本入口，而是遵守这套固定动作：

- 用户只给标题：先 `search`
- 用户要长期跟踪：用 `subscribe --run-now`
- 用户只要这次下载：用 `download-full`
- 用户要一次性下载并同时输出分册：用 `download-full --split-chapters-per-volume <N>`
- 用户怀疑 EPUB 有问题：用 `validate-epub`
- 用户要确认 fixed-layout、导航和大书稳定性：用 `scripts/epub_audit.py` 和 `scripts/epub_pressure.py`
- 用户怀疑页数不对：用 `compare-pages`
- 用户手头已有单章 EPUB：用 `rebuild-merged` 或 `rebuild-split`

执行时建议顺序：

1. 新环境先 `bootstrap`
2. 再 `doctor`
3. 再根据意图选择 `search`、`subscribe`、`download-full`
4. 最后在需要时补 `validate-epub`

## 输出契约

### 漫画库

```text
library/<漫画名>/
  chapters/
  merged/
  volumes/
  series.json
```

### 任务运行记录

```text
runs/<job-name>/
  downloads/
  epubs/
  merged/
  report.json
```

### 订阅状态

```text
state/subscriptions.json
```

对用户最稳定的阅读结果是 `library/<漫画名>/`。
对上层 agent 最关键的是 `runs/<job-name>/report.json`。这是最稳定的过程索引，适合继续做自动化判断、排障和二次处理。

`download-full` 默认会复用稳定的 `job-name` 并覆盖 `library/` 下的旧结果；如果只是想重建最终成品，也可以直接跑 `rebuild-merged` 或 `rebuild-split`，它们默认同样会把结果发布到 `library/`。

## 常用命令

搜索：

```bash
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
```

按 `comic_id` 下载：

```bash
python3 scripts/manga_loader.py download-full --comic-id zangsongdefulilian
```

按 `comic_id` 下载并同时产出分册：

```bash
python3 scripts/manga_loader.py download-full \
  --comic-id zangsongdefulilian \
  --split-chapters-per-volume 40
```

创建订阅但先不下载：

```bash
python3 scripts/manga_loader.py subscribe --query "葬送的芙莉莲"
```

运行单个订阅：

```bash
python3 scripts/manga_loader.py subscriptions run --subscription zangsongdefulilian:default
```

列出订阅：

```bash
python3 scripts/manga_loader.py subscriptions list
```

重建合订本：

```bash
python3 scripts/manga_loader.py rebuild-merged \
  --chapter-epub-dir library/葬送的芙莉蓮/chapters \
  --output library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub \
  --title "葬送的芙莉莲" \
  --author "山田钟人, アベツカサ"
```

预生成分册计划：

```bash
python3 scripts/manga_loader.py plan-volumes \
  --chapter-epub-dir runs/frieren-full-kcc/epubs \
  --title "葬送的芙莉蓮" \
  --chapters-per-volume 40
```

从现有单章 EPUB 重建分册：

```bash
python3 scripts/manga_loader.py rebuild-split \
  --chapter-epub-dir library/葬送的芙莉蓮/chapters \
  --output-dir library/葬送的芙莉蓮/volumes \
  --title "葬送的芙莉蓮" \
  --author "山田钟人, アベツカサ" \
  --chapters-per-volume 40
```

对账单章页数和合并后页数：

```bash
python3 scripts/manga_loader.py compare-pages \
  --chapter-epub-dir runs/frieren-full-kcc/epubs \
  --merged runs/frieren-full-kcc-fxl/merged/葬送的芙莉蓮\ 合订版.epub \
  --volumes-dir runs/frieren-full-kcc-split/volumes
```

校验 EPUB：

```bash
python3 scripts/manga_loader.py validate-epub \
  --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub
```

语义审计：

```bash
python3 scripts/epub_audit.py --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub
```

压力测试：

```bash
python3 scripts/epub_pressure.py \
  --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub \
  --repeat 10 \
  --workers 4
```

## 仓库结构

```text
.
├── SKILL.md
├── README.md
├── agents/
├── config/
├── library/
├── references/
├── runs/
├── scripts/
├── state/
└── vendor/
```

关键目录说明：

- `scripts/`：唯一公开 CLI 入口与辅助验证脚本
- `vendor/`：仓库自带运行资产，包含下载器源码、预编译二进制和后处理脚本
- `config/`：默认配置与样例配置
- `library/`：最终给用户阅读的稳定本地漫画库，重复执行默认覆盖
- `runs/`：每次任务的下载、打包和 `report.json`，主要用于调试与审计
- `state/`：本地订阅状态

## 一键验证

轻量烟雾测试：

```bash
scripts/smoke_test.sh "manga-loader-smoke" "葬送的芙莉莲" 1
```

完整技能验证：

```bash
scripts/verify_skill.sh "manga-loader-verify" "葬送的芙莉莲" 1
```

## 对 agent 友好的地方

- 指令面收敛：agent 只需要记住一条入口 `scripts/manga_loader.py`
- 参数面稳定：搜索、订阅、执行、校验是明确子命令，不是模糊自然语言动作
- 结果可机读：命令输出 JSON，`report.json` 也固定落盘
- 排查路径固定：`doctor -> report.json -> validate-epub`
- 状态可复用：订阅状态写在本地 JSON，不依赖聊天历史
- 不绑宿主：不假设某个聊天平台、某个 webhook、某个 agent runtime
- 不偷用外部目录：仓库内已经带了必要运行资产，不需要再去调用别处脚本

## 边界

这个项目当前不做：

- 站点推送或 webhook 通知
- 聊天平台消息回传
- DRM 内容处理
- 多漫画源统一聚合
- 云端任务调度

当前明确支持：

- CopyManga 搜索与下载
- 本地订阅
- 单章 EPUB
- 合订本 EPUB
- 合订本重建
- EPUB 结构校验

推荐的调用边界是：

- 正常用户流程只走 `python3 scripts/manga_loader.py ...`
- `doctor` 只负责环境体检，不负责最终产物判定
- `validate-epub` 只负责单文件结构校验
- `scripts/epub_audit.py` 只负责语义审计
- `scripts/epub_pressure.py` 只负责重复验证和稳定性测试
- `scripts/simple_epub.py`、`scripts/merge_epub.py`、`vendor/postprocess/*` 不当作面向用户的稳定 API

## 许可证

本仓库使用 MIT License，见 `LICENSE`。
