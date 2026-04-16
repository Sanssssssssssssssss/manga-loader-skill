# AGENTS.md

这个文件是通用 AI Agent 的仓库入口。  
在这个仓库里执行漫画下载、订阅、EPUB 打包或排障任务前，**必须先阅读 [SKILL.md](SKILL.md)**。

## 仓库概览

Manga Loader Skill 是一个本地执行型漫画工作流仓库。它把漫画标题或 `comic_id` 转成：

- 搜索与解析
- 本地订阅
- 章节下载
- 单章 EPUB
- 合订本 EPUB
- 分册合订 EPUB
- 校验、审计、压力测试
- 稳定发布到 `library/<漫画名>/`

## 执行要求

- 正式入口只有 `python3 scripts/manga_loader.py <subcommand> ...`
- 新环境必须先 `bootstrap`，再 `doctor`
- 用户只给标题时不要猜 `comic_id`，先 `search`
- 最终交付优先引用 `library/`，不要把 `runs/` 当成最终阅读目录
- `runs/` 主要用于 `report.json`、排障和回放
- 内部 helper 脚本不是上层稳定 API，除非你在维护这个仓库本身

## 兼容边界

- 这是 skill / workflow 仓库，不是 Web 服务模板
- 不要默认假设有云端基础设施、Webhook、任务队列或聊天平台回传
- 不要默认假设必须有 `.worktrees/`、CI 或额外分支策略
- 如果宿主环境的通用规则与本仓库冲突，优先遵守 `SKILL.md` 与本文件

## 常用命令

```bash
python3 scripts/manga_loader.py bootstrap
python3 scripts/manga_loader.py doctor --check-network
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲"
python3 scripts/manga_loader.py subscribe --query "葬送的芙莉莲" --run-now
python3 scripts/manga_loader.py validate-epub --path <epub-path>
python3 scripts/manga_loader.py compare-pages --chapter-epub-dir <dir> [--merged <file>] [--volumes-dir <dir>]
python3 scripts/epub_audit.py --path <epub-path>
python3 scripts/epub_pressure.py --path <epub-path>
```

## 核心目录

- `SKILL.md`：主操作规则
- `README.md`：用户视角说明
- `agents/openai.yaml`：宿主 UI 元数据
- `scripts/`：正式 CLI 与验证脚本
- `references/`：补充工作流与排障说明
- `config/`：样例配置
- `library/`：最终阅读结果
- `runs/`：过程产物和 `report.json`
- `state/`：订阅状态
