---
name: manga-loader
description: Search manga by title, create or update a local subscription, download chapter images from CopyManga, package chapter EPUBs, build omnibus EPUBs, rebuild merged EPUBs from chapter EPUBs, and validate outputs. Use when the user wants a specific manga, wants recurring local updates, or needs a clean EPUB pipeline from search to final files.
---

# Manga Loader

这是 agent 侧说明，不是用户手册。

用户手册在 `README.md`。

## 何时使用

当用户有以下需求时启用：

- 想找某部漫画
- 想订阅某部漫画并持续更新
- 想下载单章本和合订本
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
- 当用户只给漫画名时，不要自己猜 `comic_id`，先 `search`

## 默认执行顺序

1. 新环境先跑 `bootstrap`
2. 再跑 `doctor`
3. 如果用户只给漫画名，先 `search`
4. 如果用户想长期跟踪，跑 `subscribe --run-now`
5. 如果用户只想一次性产出，跑 `download-full`
6. 产出后如有疑问，跑 `validate-epub`

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
- 想持续更新：`subscribe --query <title> --run-now`
- 想刷新现有订阅：`subscriptions run --all` 或 `--subscription <id>`
- 想重建合订本：`rebuild-merged --chapter-epub-dir <dir> --output <file> --title <title>`
- 想检查 EPUB 是否坏掉：`validate-epub --path <file>`

## 输出约定

最终结果在：

- `library/<漫画名>/chapters/`
- `library/<漫画名>/merged/`

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

## agent 友好性

- 单入口，低歧义
- 子命令语义稳定
- 输出 JSON 结构化，适合后续 agent 消费
- 订阅状态在本地文件，不依赖聊天历史
- 失败排查路径固定：`doctor -> report.json -> validate-epub`

## 成功标准

在一次下载或订阅执行后，至少满足：

- 命令返回成功
- 生成了 `runs/<job-name>/report.json`
- `report.json` 中有 `merged_epub`
- `validation.valid` 为 `true`

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

当前不支持：

- webhook 推送
- 聊天平台回传
- 多源聚合
- 云端调度

## 需要进一步查看时

- 运行布局和排查口径：`references/workflow.md`
- 用户用法和发布说明：`README.md`
