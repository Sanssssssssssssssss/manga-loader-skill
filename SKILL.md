---
name: manga-loader
description: Search manga by title or comic_id, create local subscriptions, download chapters from CopyManga, build chapter EPUBs, merged EPUBs, and split-volume EPUBs, then validate page counts and fixed-layout output quality. Use when the user wants a manga delivered to a stable local library or needs to debug a manga EPUB workflow.
---

# Manga Loader

这是这个技能的主操作文件。
如果当前任务发生在这个仓库内，优先遵守本文件；用户手册和发布说明在 `README.md`。

## 何时使用

当用户有这些需求时启用：

- 想搜索某部漫画
- 想订阅并持续刷新某部漫画
- 想下载单章 EPUB、合订本 EPUB 或分册 EPUB
- 想从现有单章 EPUB 重建合订本或分册
- 想检查页数不对、分页异常、Apple Books 兼容性差、fixed-layout 语义缺失
- 想让 Agent 在本地稳定地产出一个可交付、可验证、可回放的漫画结果

## 仓库定位

- 这是一个本地执行型 skill / workflow 仓库，不是 Web 服务，也不是云端调度系统
- 正式交付物在 `library/`，不是在 `runs/`
- `runs/` 只保存过程产物和 `report.json`，用于调试、回放和排障
- `state/` 只保存订阅状态

## 非协商约束

- **先 `bootstrap`，再 `doctor`**。新环境不要直接跑下载。
- **只把 `scripts/manga_loader.py` 当成正式入口**。除非你正在维护这个 skill 本身，否则不要绕过它直接把其他脚本当 API。
- **不要猜 `comic_id`**。用户只给标题时，先 `search`。
- **不要把 `runs/` 当成最终阅读目录**。对用户交付结果时，优先引用 `library/<漫画名>/...`。
- **不要只看终端输出就宣称成功**。至少确认文件存在，并检查结构化结果。
- **不要默认把超长系列做成一个巨大合订本**。长篇优先考虑分册。
- **不要混用体检和产物审计命令**。`doctor`、`compare-pages`、`validate-epub`、`epub_audit.py`、`epub_pressure.py` 解决的是不同问题。
- **不要把 helper 脚本暴露成上层稳定接口**。`scripts/simple_epub.py`、`scripts/merge_epub.py`、`vendor/postprocess/*` 属于内部实现。

## 宿主兼容边界

- 这个仓库是“通用 Agent 可挂载 skill”，不是某个宿主私有模板
- 不要假设存在特定聊天平台、Webhook、任务队列或外部 orchestrator
- 不要假设仓库外已经存在 `.runtime/`、`library/`、`runs/`、`state/`
- 不要假设必须有 `.worktrees/`、CI、分支策略或额外测试框架，除非用户明确要求
- 如果宿主环境还有 `AGENTS.md`、`CLAUDE.md` 一类入口文件，应先通过它们跳转回本文件

## 正式入口

只使用这一条公开入口：

```bash
python3 scripts/manga_loader.py <subcommand> ...
```

所有面向用户或上层 Agent 的正式动作都应由它发起。

## 默认执行顺序

1. 新环境先 `bootstrap`
2. 再 `doctor`
3. 用户只给标题时先 `search`
4. 长期跟踪用 `subscribe --run-now`
5. 一次性结果用 `download-full`
6. 如需重建现有产物，用 `rebuild-merged` 或 `rebuild-split`
7. 如需确认结果质量，再按问题类型选择 `compare-pages` / `validate-epub` / `epub_audit.py` / `epub_pressure.py`

## 意图到命令

- 想找漫画：`search --query <title>`
- 想下载一次：`download-full --query <title>` 或 `--comic-id <id>`
- 想边下载边做分册：`download-full --query <title> --split-chapters-per-volume <N>`
- 想长期更新：`subscribe --query <title> --run-now`
- 想刷新订阅：`subscriptions run --all` 或 `--subscription <id>`
- 想从现有单章 EPUB 重建合订本：`rebuild-merged --chapter-epub-dir <dir> --output <file> --title <title>`
- 想从现有单章 EPUB 重建分册：`rebuild-split --chapter-epub-dir <dir> --output-dir <dir> --title <title>`
- 想先看分册方案：`plan-volumes --chapter-epub-dir <dir> --title <title>`
- 想核对页数是否异常：`compare-pages --chapter-epub-dir <dir> [--merged <file>] [--volumes-dir <dir>]`
- 想查 XML/manifest/spine 是否坏掉：`validate-epub --path <file>`
- 想检查漫画 fixed-layout 语义：`scripts/epub_audit.py --path <file>`
- 想做重复验证或大书稳定性验证：`scripts/epub_pressure.py --path <file>`

## 推荐命令

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

一次性下载：

```bash
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲"
```

一次性下载并做分册：

```bash
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲" \
  --split-chapters-per-volume 40
```

订阅并立即产出：

```bash
python3 scripts/manga_loader.py subscribe \
  --query "葬送的芙莉莲" \
  --run-now
```

## 分册策略

默认产物仍然是：

- 单章 EPUB
- 单本合订 EPUB

当系列很长、文件很大，或阅读器兼容性容易变差时，再切换到分册。

推荐规则：

- 优先按官方卷信息切分
- 没有卷信息时按章节数切分
- 章节大小波动很大时叠加体积上限
- 只在章节边界切分，不切半章
- 不为了“全集单文件”牺牲可读性和稳定性

推荐命名：

- 单章：`<漫画名> <章节名>.epub`
- 合订：`<漫画名> 合订版.epub`
- 分册：`<漫画名> 第XX册.epub`

## 调试口径

这几种检查解决的是不同层面的问题，不要混用：

- `doctor`：环境、依赖、网络是否可跑
- `compare-pages`：单章页数和合并后页数是否一致
- `validate-epub`：XML、manifest、spine、引用是否损坏
- `scripts/epub_audit.py`：fixed-layout、作者、导航、页面语义是否像漫画 EPUB
- `scripts/epub_pressure.py`：重复执行下是否稳定

推荐排障顺序：

1. 先 `doctor`
2. 看 `runs/<job-name>/report.json`
3. 如果怀疑丢页或分页错乱，先 `compare-pages`
4. 再 `validate-epub`
5. 如果是 Apple Books / fixed-layout 体验差，再 `scripts/epub_audit.py`
6. 如果要证明大书稳定性，再 `scripts/epub_pressure.py`

## 输出契约

最终结果在：

- `library/<漫画名>/chapters/`
- `library/<漫画名>/merged/`
- `library/<漫画名>/volumes/`

过程索引在：

- `runs/<job-name>/report.json`

订阅状态在：

- `state/subscriptions.json`

如果你要判断任务是否真的完成，优先检查：

- 命令退出码
- `report.json`
- `validation.valid`
- `audit.reader_ready`
- `library/<漫画名>/...` 对应文件是否真的存在

## 成功标准

一次下载、订阅或重建完成后，至少要满足：

- 命令成功退出
- 生成了 `runs/<job-name>/report.json`
- 结构化结果里包含目标产物路径
- 产物文件实际存在
- `validation.valid = true`

如果用户要的是“可阅读交付物”，再补确认：

- 合订本在 `library/<漫画名>/merged/`
- 分册在 `library/<漫画名>/volumes/`
- 单章在 `library/<漫画名>/chapters/`

## 失败处理

如果失败，不要直接重试一切，按这个顺序排查：

1. 先 `doctor`
2. 再看 `runs/<job-name>/report.json`
3. 对失败文件执行 `compare-pages` 或 `validate-epub`
4. 必要时跑 `scripts/epub_audit.py`
5. 如果是长篇、大书或偶发问题，再跑 `scripts/epub_pressure.py`

不要在没有证据的情况下声称“下载成功”或“阅读器应该没问题”。

## 边界

当前支持：

- CopyManga 数据源
- 本地搜索、订阅、下载、打包
- 单章 EPUB、合订 EPUB、分册 EPUB
- 本地结构校验、语义审计、页数对账、压力测试

当前不支持：

- 多漫画源聚合
- Webhook 推送
- 聊天平台回传
- 云端调度

## 需要继续查看时

- 仓库级入口说明：`AGENTS.md`、`CLAUDE.md`
- 用户视角说明：`README.md`
- 运行与排障口径：`references/workflow.md`
