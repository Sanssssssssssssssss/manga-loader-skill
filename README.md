# Manga Loader Skill

面向通用 Agent 的漫画搜索、订阅、下载、EPUB 打包与分册合订技能。

<div>
  <img src="https://img.shields.io/badge/Agent%20Skill-CLI%20First-2563eb?style=flat-square" alt="Agent Skill" />
  <img src="https://img.shields.io/badge/Source-CopyManga-16a34a?style=flat-square" alt="Source" />
  <img src="https://img.shields.io/badge/EPUB-Fixed%20Layout-f59e0b?style=flat-square" alt="EPUB" />
  <img src="https://img.shields.io/badge/Output-Stable%20Library-7c3aed?style=flat-square" alt="Output" />
  <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="License" />
</div>

---

**Manga Loader Skill** 把“我想看这部漫画”变成一条可执行、可恢复、可审计的本地工作流。
它不是某个平台私有脚本，也不是一次性 demo，而是一个面向任意 Agent / CLI 环境的通用技能仓库。

给定漫画标题或 `comic_id`，它可以完成：

- 搜索漫画并解析目标
- 建立本地订阅并重复刷新
- 下载章节图片
- 生成单章 EPUB
- 生成合订本 EPUB
- 按章节数或体积限制生成分册合订
- 校验页数、结构、fixed-layout 语义与大书稳定性
- 把最终结果稳定发布到 `library/<漫画名>/`

## 最近更新

`2026-04-16`

- 合订本与分册默认发布到 `library/`，重复执行直接覆盖稳定结果，不再要求用户去 `runs/` 里找最终文件。
- Apple Books 兼容性继续收敛：补齐 fixed-layout 元数据、作者信息、逐页导航和页数对账逻辑。
- 新增 `compare-pages`、`scripts/epub_audit.py`、`scripts/epub_pressure.py` 与基础回归测试，便于 agent 和人工一起 debug。
- `rebuild-merged`、`rebuild-split` 已接入稳定发布逻辑，可从现有单章 EPUB 重新生成最终交付物。

## 安装

这个仓库默认以“可被 Agent 调用的本地技能”方式使用，而不是传统 Python 包。

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git
cd manga-loader-skill
python3 scripts/manga_loader.py bootstrap
```

如果你的 Agent 平台支持基于 Git 仓库挂载技能，只要它能：

- 读取 `SKILL.md`
- 执行 shell / Python 命令
- 访问本地文件系统

就可以直接复用这套技能。

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

## 常用命令

```bash
# 搜索
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"

# 直接下载
python3 scripts/manga_loader.py download-full --comic-id zangsongdefulilian

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
```

## 配置

默认配置模板在 `config/settings.example.json`。
第一次执行 `bootstrap` 时，会自动生成本地 `config/settings.json`。

配置主要分成两层：

- `downloader.*`：数据源域名、重试、节奏和并发控制
- `packaging.*`：命名模板、打包后端、阅读方向、KCC 参数、分册策略

当前默认命名：

- 单章：`<漫画名> <章节名>.epub`
- 合订：`<漫画名> 合订版.epub`
- 分册：`<漫画名> 第XX册.epub`

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
```

含义很明确：

- `library/`：最终给用户阅读的稳定结果
- `runs/`：本次任务的过程数据、调试信息和过程索引
- `state/`：订阅状态

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

## License

[MIT](LICENSE)
