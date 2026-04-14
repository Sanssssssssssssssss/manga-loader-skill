# Manga Loader Skill

一个面向通用 agent 和 CLI 用户的自包含漫画工作流仓库。

目标很单一：用户只需要给出漫画标题或 `comic_id`，系统就能在本地完成搜索、订阅、章节下载、单章 EPUB 打包、合订本 EPUB 打包，以及后续的结构校验与重建。

当前内置的数据源适配器是 CopyManga。

## 这个仓库保证什么

- 单一公开入口：所有正式操作统一走 `scripts/manga_loader.py`
- 本地可运行：不依赖某个聊天平台、某个 webhook、某个专用 runtime
- 仓库自包含：下载器源码、预编译二进制、EPUB 打包脚本都放在仓库内
- 输出稳定：最终产物固定落到 `library/`、`runs/`、`state/`
- 可验证：内置 `doctor`、`validate-epub`、`smoke_test.sh`、`verify_skill.sh`
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
- Linux/macOS 优先

可选但推荐：

- Rust / Cargo
  当 `vendor/bin/copymanga-headless-rs` 不适配当前平台时，项目会自动尝试从 `vendor/copymanga-headless-rs-src` 本地构建下载器

### 2. 初始化运行时

```bash
python3 scripts/manga_loader.py bootstrap
```

这一步会：

- 创建 `.runtime/python-venv`
- 安装 `requirements.txt` 中的最小 Python 依赖
- 准备 `copymanga-headless-rs` 运行二进制
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
    "chapter_name_template": "{series_title} {chapter_label}.epub",
    "merged_name_template": "{title} 合订版.epub",
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
- `packaging.chapter_name_template`：章节 EPUB 文件名模板
- `packaging.merged_name_template`：合订本默认文件名模板
- `packaging.jpeg_quality`：EPUB 内部 JPEG 质量
- `packaging.page_background`：页面补边时使用的背景色

如果你想看更偏“工程流水线配置”的旧版说明，可以参考你原来的项目：

- `https://github.com/Sanssssssssssssssss/mangaloader-epub-postprocess`

但这个 skill 刻意没有沿用那套更重的 job 配置，而是收敛成更适合 agent 调用的单入口和轻配置模型。

## Agent 集成契约

对 agent 来说，最重要的是不要“猜”脚本入口，而是遵守这套固定动作：

- 用户只给标题：先 `search`
- 用户要长期跟踪：用 `subscribe --run-now`
- 用户只要这次下载：用 `download-full`
- 用户怀疑 EPUB 有问题：用 `validate-epub`
- 用户手头已有单章 EPUB：用 `rebuild-merged`

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

对上层 agent 最关键的是 `runs/<job-name>/report.json`。这是最稳定的结果索引，适合继续做自动化判断、排障和二次处理。

## 常用命令

搜索：

```bash
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
```

按 `comic_id` 下载：

```bash
python3 scripts/manga_loader.py download-full --comic-id zangsongdefulilian
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

校验 EPUB：

```bash
python3 scripts/manga_loader.py validate-epub \
  --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub
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
- `library/`：最终给用户阅读的本地漫画库
- `runs/`：每次任务的下载、打包和 `report.json`
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

## Apple Books 兼容性说明

当前默认产出的单章 EPUB 和合订本 EPUB 都按 fixed-layout 漫画思路生成：

- 写入作者元数据
- 写入 `rendition:layout = pre-paginated`
- 写入 `rendition:spread = none`
- 每一页使用独立 XHTML
- 每页写入明确的 `viewport` 宽高

这样做的目的，是尽量减少 Apple Books 把漫画当成普通可重排图文 EPUB 来处理，从而出现作者信息缺失、分页异常、把每张图当成独立可滚动内容的情况。

## GitHub 发布建议

建议保留这些内容：

- `README.md`
- `SKILL.md`
- `agents/openai.yaml`
- `scripts/`
- `references/`
- `vendor/`
- `config/settings.example.json`
- `requirements.txt`
- `.gitignore`

不要把这些生成目录提交到仓库：

- `.runtime/`
- `runs/`
- `library/`
- `state/`
- `config/settings.json`

## 许可证

本仓库使用 MIT License，见 `LICENSE`。
