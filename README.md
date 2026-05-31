# CopyManga EPUB Downloader Skill / 拷贝漫画 EPUB 下载 Skill

面向 Agent 和 CLI 的拷贝漫画下载器：搜索 CopyManga / 拷贝漫画，下载章节图片，生成 fixed-layout EPUB、合订本和分册，并把结果发布到稳定本地书库。

An agent-friendly CopyManga downloader and EPUB packaging workflow. Search manga, download chapters, build fixed-layout EPUB files, merge or split volumes, validate the output, and publish everything into a stable local library.

<div>
  <img src="https://img.shields.io/badge/Agent%20Skill-CLI%20First-2563eb?style=flat-square" alt="Agent Skill" />
  <img src="https://img.shields.io/badge/CopyManga-Downloader-16a34a?style=flat-square" alt="CopyManga Downloader" />
  <img src="https://img.shields.io/badge/EPUB-Fixed%20Layout-f59e0b?style=flat-square" alt="EPUB" />
  <img src="https://img.shields.io/badge/Output-EPUB%20%7C%20Omnibus%20%7C%20Volumes-7c3aed?style=flat-square" alt="Output Formats" />
  <img src="https://img.shields.io/badge/Output-Stable%20Library-7c3aed?style=flat-square" alt="Output" />
  <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="License" />
</div>

---

**Manga Loader Skill** 把“我想看这部漫画”变成一条可执行、可恢复、可审计的本地工作流。
它既可以当普通命令行工具使用，也可以作为 Codex、Claude Code 或其他本地 Agent 的 skill 仓库使用。

关键词 / Keywords: 拷贝漫画下载器, 拷贝漫画 EPUB, CopyManga downloader, manga downloader, manga EPUB, fixed-layout EPUB, agent skill, Codex skill.

给定漫画标题或 `comic_id`，它可以完成：

- 搜索漫画并解析目标
- 建立本地订阅并重复刷新
- 下载章节图片
- 生成单章 EPUB
- 生成合订本 EPUB
- 按章节数或体积限制生成分册合订
- 校验页数、结构、fixed-layout 语义与大书稳定性
- 把最终结果稳定发布到 `library/<漫画名>/`
- 可选发布到外部漫画书库布局：`分章/`、`合订本/完整版.epub`、`历史备份/`

## 为什么看这个项目

成熟漫画下载器通常解决“下载”和“格式转换”；这个仓库额外解决 Agent 场景最容易出错的几件事：

- CLI 入口固定，Agent 不需要猜内部脚本。
- `runs/` 和 `library/` 分离，调试产物不会混进最终书库。
- 每次任务都有 `report.json`，可以机器判定是否成功。
- EPUB 输出会做结构校验、页数对账和 fixed-layout 语义审计。
- 长篇漫画可以按章节数或体积切成分册，避免超大单文件影响阅读器稳定性。

## 最近更新

`2026-05-31`

- 合订本与分册默认发布到 `library/`，重复执行直接覆盖稳定结果，不再要求用户去 `runs/` 里找最终文件。
- 新增 `download-full --resume`，用于复用已有下载并补齐缺失章节。
- 新增 `publish-library --title <漫画名>`，可把稳定书库同步到外部漫画书库结构。
- 隐藏的 `.downloading` 临时目录会被排除，不会误当作正式章节。
- Apple Books 兼容性继续收敛：补齐 fixed-layout 元数据、作者信息、逐页导航和页数对账逻辑。
- 新增 `compare-pages`、`scripts/epub_audit.py`、`scripts/epub_pressure.py` 与基础回归测试，便于 agent 和人工一起 debug。

## 安装

这个仓库默认以“可被 Agent 调用的本地技能”方式使用，而不是传统 Python 包。

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git
cd manga-loader-skill
python3 scripts/manga_loader.py bootstrap
```

如果你要把它安装成宿主本地 skill，当前最稳的方式是直接完整 clone 到技能目录，例如：

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git \
  ~/.codex/skills/manga-loader
```

如果你的 Agent 平台支持基于 Git 仓库挂载技能，只要它能：

- 读取 `SKILL.md`
- 执行 shell / Python 命令
- 访问本地文件系统

就可以直接复用这套技能。

注意：

- 这个仓库的根目录本身就是 skill 目录
- 某些通用 GitHub skill installer 在对根目录 skill 做 sparse checkout 时，可能只拿到顶层文件，导致 `scripts/`、`vendor/` 等目录缺失
- 如果安装后发现 skill 目录里缺少这些子目录，改用完整 clone，或让安装器走 full download / full repo 模式

## 复刻后能不能直接用

可以，前提是运行环境满足下面条件：

- Linux 或类 Linux shell 环境
- Python 3.11+
- 能访问 CopyManga API
- `python3 scripts/manga_loader.py bootstrap` 能成功准备 `.runtime/`

仓库不会提交本机 `config/settings.json`、`runs/`、`library/`、`state/`。别人 clone 后第一次运行 `bootstrap` 会生成本地配置和运行目录；这也是为了避免把个人路径、订阅状态和下载产物打包进仓库。

## 核心亮点

**单一公开入口**：正式操作统一走 `python3 scripts/manga_loader.py <subcommand>`，上层 Agent 不需要猜内部脚本调用顺序。

**稳定产物发布**：最终阅读结果固定落到 `library/<漫画名>/`，`runs/` 只保留下载、中间件和 `report.json`，便于调试与回放。

**合订与分册同时支持**：既能输出单章 EPUB 和全集合订，也能按章节数或体积阈值切分成多册，适合长篇漫画。

**面向阅读器兼容性优化**：默认产出 fixed-layout 漫画式 EPUB，补齐作者、导航、viewport、page progression 等关键元数据，优先保证 Apple Books 一类阅读器的实际可读性。

**可验证、可审计、可压测**：内置 `doctor`、`validate-epub`、`compare-pages`、`epub_audit.py`、`epub_pressure.py`，不是只会“生成”，也能解释“为什么这本书有问题”。

**Agent 友好**：输入边界清晰、命令面稳定、输出落盘明确、失败排查路径固定，适合被不同平台复用，而不是绑定某个单一 runtime。

## 工作流

```text
用户标题 / comic_id
  -> search / resolve
  -> subscribe（可选）
  -> download images
  -> chapter EPUBs
  -> merged EPUB
  -> split volumes（可选）
  -> validate / compare / audit / pressure
  -> publish to library/<title>/
```

整个流程默认是 `CLI-first` 的。
对 Agent 来说，`SKILL.md` 提供调用规则；对人类用户来说，`scripts/manga_loader.py` 是唯一正式入口。

## 产物链

```text
query / comic_id
  -> downloads/
  -> chapter images
  -> chapters/*.epub
  -> merged/*.epub
  -> volumes/*.epub（可选）
  -> report.json
  -> library/<漫画名>/
```

如果你在排障，最重要的是：

- 最终交付看 `library/<漫画名>/`
- 过程索引看 `runs/<job-name>/report.json`
- 环境体检先跑 `doctor`

## 快速开始

### 1. 环境要求

- Python 3.11+
- Linux 环境优先
- 网络可访问 CopyManga API

下载链路依赖仓库内 vendored 的 `copymanga-headless-rs`。
如果预编译二进制不适配当前平台，`bootstrap` 会尝试用本地 Rust / Cargo 重新构建，所以某些环境下需要安装 Rust。

### 2. 初始化

```bash
python3 scripts/manga_loader.py bootstrap
```

### 3. 体检

```bash
python3 scripts/manga_loader.py doctor --check-network
```

### 4. 搜索漫画

```bash
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
```

### 5. 一次性下载并生成 EPUB

```bash
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲"
```

### 6. 一次性下载并同时生成分册

```bash
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲" \
  --split-chapters-per-volume 40
```

### 7. 建立订阅并立即产出

```bash
python3 scripts/manga_loader.py subscribe \
  --query "葬送的芙莉莲" \
  --run-now
```

### 8. 刷新所有订阅

```bash
python3 scripts/manga_loader.py subscriptions run --all
```

## English Quick Start

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git
cd manga-loader-skill
python3 scripts/manga_loader.py bootstrap
python3 scripts/manga_loader.py doctor --check-network
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲"
```

Install as a local Codex skill:

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git \
  ~/.codex/skills/manga-loader
```

Common commands:

```bash
# Download only the first chapter for a smoke test
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --chapter-limit 1

# Resume an incomplete download
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --resume

# Build split volumes for a long series
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --split-chapters-per-volume 40

# Validate the final EPUB
python3 scripts/manga_loader.py validate-epub --path "library/<title>/merged/<file>.epub"
```

The project is not an official CopyManga client. Use it only where you have the right to access and archive the content.
CopyManga search generally works best with Chinese titles or a known `comic_id`.

## 常用命令

```bash
# 搜索
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"

# 直接下载
python3 scripts/manga_loader.py download-full --comic-id zangsongdefulilian

# 断点续传 / 补齐缺失章节
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --resume

# 重建合订本
python3 scripts/manga_loader.py rebuild-merged \
  --chapter-epub-dir library/葬送的芙莉蓮/chapters \
  --output library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub \
  --title "葬送的芙莉蓮" \
  --author "山田钟人, アベツカサ"

# 重建分册
python3 scripts/manga_loader.py rebuild-split \
  --chapter-epub-dir library/葬送的芙莉蓮/chapters \
  --output-dir library/葬送的芙莉蓮/volumes \
  --title "葬送的芙莉蓮" \
  --author "山田钟人, アベツカサ" \
  --chapters-per-volume 40

# 对账页数
python3 scripts/manga_loader.py compare-pages \
  --chapter-epub-dir library/葬送的芙莉蓮/chapters \
  --merged library/葬送的芙莉蓮/merged/葬送的芙莉蓮\ 合订版.epub \
  --volumes-dir library/葬送的芙莉蓮/volumes

# 结构校验
python3 scripts/manga_loader.py validate-epub \
  --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub

# fixed-layout 语义审计
python3 scripts/epub_audit.py \
  --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub

# 压力测试
python3 scripts/epub_pressure.py \
  --path library/葬送的芙莉蓮/merged/葬送的芙莉蓮 合订版.epub

# 发布已有稳定书库到外部漫画书库布局
python3 scripts/manga_loader.py publish-library --title "葬送的芙莉莲"
```

## 配置

默认配置模板在 `config/settings.example.json`。
第一次执行 `bootstrap` 时，会自动生成本地 `config/settings.json`。

配置主要分成三层：

- `downloader.*`：数据源域名、重试、节奏和并发控制
- `packaging.*`：命名模板、打包后端、阅读方向、KCC 参数、分册策略
- `publish.*`：外部漫画书库根目录、合订本文件名、历史备份策略

当前默认命名：

- 单章：`<漫画名> <章节名>.epub`
- 合订：`<漫画名> 合订版.epub`
- 分册：`<漫画名> 第XX册.epub`

如果要同步到外部漫画书库，配置 `publish.mangabooks_root` 后运行：

```bash
python3 scripts/manga_loader.py publish-library --title "<漫画名>"
```

## 输出约定

```text
library/<漫画名>/
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

外部书库（可选）:
  <mangabooks_root>/<漫画名>/
    分章/
    合订本/完整版.epub
    历史备份/
```

含义很明确：

- `library/`：最终给用户阅读的稳定结果
- `runs/`：本次任务的过程数据、调试信息和过程索引
- `state/`：订阅状态
- 外部书库：给现有漫画阅读目录或同步目录使用

如果你只是想“看书在哪”，优先看 `library/`。
如果你想 debug，优先看 `runs/<job-name>/report.json`。

## Agent 使用边界

这个技能当前支持：

- CopyManga 数据源
- 本地搜索 / 订阅 / 下载 / 打包
- 单章 EPUB、合订本 EPUB、分册合订 EPUB
- 本地结构校验、语义审计、页数对账、压力测试

这个技能当前不支持：

- 多漫画源聚合
- 云端调度
- 聊天平台回传
- Webhook 推送

也就是说，它是一个可靠的“本地执行技能”，不是一个 SaaS 服务。

## 仓库结构

```text
manga-loader-skill/
├── AGENTS.md
├── CLAUDE.md
├── SKILL.md
├── README.md
├── LICENSE
├── requirements.txt
├── agents/
│   └── openai.yaml
├── config/
│   └── settings.example.json
├── references/
│   └── workflow.md
├── scripts/
│   ├── manga_loader.py
│   ├── manga_common.py
│   ├── epub_audit.py
│   ├── epub_checks.py
│   ├── epub_pressure.py
│   ├── smoke_test.sh
│   └── verify_skill.sh
├── tests/
└── vendor/
```

## 为什么它对 Agent 友好

- 有 `SKILL.md`，而不是把使用方法散落在 issue、聊天记录或代码注释里
- 正式入口单一，不需要让模型自己猜脚本和参数
- 产物链清楚，任务完成与否可以用文件和 JSON 判断，而不是靠自然语言猜测
- 失败路径可重复：`doctor -> report.json -> compare-pages / validate-epub / audit`
- 最终结果与调试结果分离，用户和 Agent 不会争用同一堆中间文件

## 致谢

这个项目建立在优秀的开源工作之上。

特别感谢：

- Ciro Mattia Gonano 和 Pawel Jastrzebski，提供 Kindle Comic Converter（KCC）
- lanyeeee，提供 copymanga-downloader
- YuxuanHan0326，提供 MangaEpubAutomation

这些工作让这个轻量、实用的漫画工作流能更快落地。

## Disclaimer

This project is an unofficial local workflow for personal archiving and EPUB packaging. It is not affiliated with CopyManga or any content provider. Respect the source site's terms, copyright law, and your local regulations.

本项目不是拷贝漫画官方客户端。请只在你有权访问和归档内容的前提下使用，并遵守源站规则、版权要求和所在地法律。

## License

[MIT](LICENSE)
