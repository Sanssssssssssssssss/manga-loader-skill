---
name: manga-loader
description: Search manga by title, create or update a local subscription, download chapter images from CopyManga, package chapter EPUBs, build omnibus or split-volume EPUBs, rebuild merged EPUBs from chapter EPUBs, and validate or audit outputs. Use when the user wants a specific manga, wants recurring local updates, or needs a clean EPUB pipeline from search to final files.
---

# Manga Loader

这是 agent 侧说明，不是用户手册。

用户手册在 `README.md`。

## 何时使用

当用户有以下需求时启用：

- 想找某部漫画
- 想订阅某部漫画并持续更新
- 想下载单章本和合订本
- 想把长篇按分册组织成更稳定的 EPUB
- 想重建 EPUB
- 想检查某个 EPUB 是否坏掉

## 公开入口

只使用一个入口：

```bash
python3 scripts/manga_loader.py <subcommand> ...
```

不要优先调用其他脚本，除非你正在修这个 skill 本身。

## 强约束

- 新环境先执行 `bootstrap`
- 不要假设已有 `.runtime/`、`library/`、`runs/`、`state/`
- 不要跳过 `doctor` 就直接判断仓库坏了
- 不要把其他脚本当成公开 API
- 不要自己拼输出路径后直接宣称成功，先看命令输出和 `report.json`
- 对用户交付结果时，优先引用 `library/<漫画名>/...`，不要把 `runs/` 当成最终阅读目录
- 当用户只给漫画名时，不要自己猜 `comic_id`，先 `search`
- 如果用户显式要求大书稳定性或 fixed-layout 语义，再用 `scripts/epub_audit.py` 和 `scripts/epub_pressure.py`

## 默认执行顺序

1. 新环境先跑 `bootstrap`
2. 再跑 `doctor`
3. 如果用户只给漫画名，先 `search`
4. 如果用户想长期跟踪，跑 `subscribe --run-now`
5. 如果用户只想一次性产出，跑 `download-full`
6. 产出后如有疑问，跑 `validate-epub`

## 分册合订规则

默认仍然以“单章 EPUB + 单本合订 EPUB”为主；如果目标系列过长，建议切到分册组织，而不是强行做一个超大的全集合订。

推荐规则：

- 优先按官方卷信息切分
- 没有卷信息时按章节数切分
- 章节体积差异很大时，再叠加大小上限
- 只在章节边界切分，不切半章
- 长篇默认优先保证可读性和稳定性，不优先追求单文件全集

推荐命名：

- 单章：`<漫画名> <章节名>.epub`
- 分册：`<漫画名> 第XX册.epub`
- 全书合订：`<漫画名> 全书合订版.epub`

如果用户要求“全集”，要同时说明这可能比分册更大、更慢，也更容易触发阅读器兼容问题。

## 体检与压力测试

这套仓库里有四种检查，不能混用：

- `doctor`：检查运行时、依赖和网络，回答“能不能跑”
- `compare-pages`：对账单章页数和合并后页数，回答“有没有丢页或多算封面页”
- `validate-epub`：检查单个 EPUB 的 XML 与引用完整性，回答“文件坏没坏”
- `scripts/epub_audit.py`：检查漫画语义和 fixed-layout 语义，回答“像不像能正常当漫画读”
- `scripts/epub_pressure.py`：反复、多进程、重复检查，回答“稳不稳”

推荐顺序：

1. 先 `doctor`
2. 再做下载或重建
3. 如果怀疑页数不对，先 `compare-pages`
4. 再 `validate-epub`
5. 若要确认阅读器行为，再 `scripts/epub_audit.py`
6. 若要验证大书稳定性，再 `scripts/epub_pressure.py`

## 最常用命令

初始化：

```bash
python3 scripts/manga_loader.py bootstrap
```

体检：

```bash
python3 scripts/manga_loader.py doctor --check-network
```

搜索：

```bash
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
```

订阅并立即产出：

```bash
python3 scripts/manga_loader.py subscribe \
  --query "葬送的芙莉莲" \
  --run-now
```

一次性产出：

```bash
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲"
```

一次性产出并同时做分册：

```bash
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲" \
  --split-chapters-per-volume 40
```

刷新所有订阅：

```bash
python3 scripts/manga_loader.py subscriptions run --all
```

校验 EPUB：

```bash
python3 scripts/manga_loader.py validate-epub --path <epub-path>
```

## 意图到命令的映射

- 想找漫画：`search --query <title>`
- 想一次性拿结果：`download-full --query <title>` 或 `--comic-id <id>`
- 想一次性拿结果并切分多册：`download-full --query <title> --split-chapters-per-volume <N>`
- 想持续更新：`subscribe --query <title> --run-now`
- 想刷新现有订阅：`subscriptions run --all` 或 `--subscription <id>`
- 想重建合订本：`rebuild-merged --chapter-epub-dir <dir> --output <file> --title <title>`，默认会同步发布到 `library/`
- 想从现有单章 EPUB 重建多册：`rebuild-split --chapter-epub-dir <dir> --output-dir <dir> --title <title>`，默认会同步发布到 `library/`
- 想先看切分计划：`plan-volumes --chapter-epub-dir <dir> --title <title>`
- 想核对有没有丢页或多算：`compare-pages --chapter-epub-dir <dir> [--merged <file>] [--volumes-dir <dir>]`
- 想检查 EPUB 是否坏掉：`validate-epub --path <file>`
- 想检查 fixed-layout / 大书稳定性：`scripts/epub_audit.py` 或 `scripts/epub_pressure.py`

## 输出约定

最终结果在：

- `library/<漫画名>/chapters/`
- `library/<漫画名>/merged/`
- `library/<漫画名>/volumes/`

任务细节在：

- `runs/<job-name>/report.json`

订阅状态在：

- `state/subscriptions.json`

最重要的机读结果是：

- `runs/<job-name>/report.json`

如果你需要判断任务是否真的完成，不要只看终端文本，优先看：

- `report.json`
- `validation.valid`
- `library/<漫画名>/merged/*.epub` 是否存在
- 如果用户要找最终成品，直接去 `library/`，不要让用户自己去 `runs/` 里翻

如果是分册模式，还要确认每一卷的 `report.json` 条目、卷名和实际文件名一致。

## agent 友好性

- 单入口，低歧义
- 子命令语义稳定
- 输出 JSON 结构化，适合后续 agent 消费
- 订阅状态在本地文件，不依赖聊天历史
- 失败排查路径固定：`doctor -> report.json -> validate-epub`
- 审计和压力测试脚本只在需要验证阅读器语义、长篇稳定性或回归时调用，不当作默认下载入口

## 成功标准

在一次下载或订阅执行后，至少满足：

- 命令返回成功
- 生成了 `runs/<job-name>/report.json`
- `report.json` 中有 `merged_epub`
- `validation.valid` 为 `true`
- 如果用户要求的是分册结果，还应满足每卷命名清楚、切分边界可追溯、总卷数与计划一致

如果用户明确要求的是“可阅读结果”，再补确认：

- `library/<漫画名>/merged/` 下存在合订本
- `library/<漫画名>/chapters/` 下存在单章 EPUB

## 失败处理

如果命令失败或 EPUB 不合法，按这个顺序排查：

1. 重新跑 `doctor`
2. 查看对应 `runs/<job-name>/report.json`
3. 对失败文件执行 `validate-epub`
4. 必要时查看 `state/subscriptions.json`

不要在没有证据的情况下宣称“下载成功”或“文件已可读”。

## 边界

当前只支持：

- CopyManga 数据源
- 本地订阅
- 本地文件产出
- 分册组织后的本地文件产出

当前不支持：

- webhook 推送
- 聊天平台回传
- 多源聚合
- 云端调度

## 推荐调用边界

- 正常用户流程只走 `python3 scripts/manga_loader.py ...`
- `doctor` 只负责环境体检，不负责最终产物判定
- `validate-epub` 只负责单文件结构校验
- `scripts/epub_audit.py` 只负责语义审计
- `scripts/epub_pressure.py` 只负责重复验证和稳定性测试
- `scripts/simple_epub.py`、`scripts/merge_epub.py`、`vendor/postprocess/*` 不当作面向用户的稳定 API

## 需要进一步查看时

- 运行布局和排查口径：`references/workflow.md`
- 用户用法和发布说明：`README.md`
