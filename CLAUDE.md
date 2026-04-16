# CLAUDE.md

这是面向 Claude Code 一类宿主的仓库入口文件。  
在这个仓库里执行任何漫画下载、订阅、EPUB 打包或排障任务前，**必须先阅读 [SKILL.md](SKILL.md)**。

## 项目概览

Manga Loader Skill 是一个通用漫画 workflow / skill 仓库，负责：

- 搜索漫画
- 建立本地订阅
- 下载章节
- 生成单章 EPUB、合订本 EPUB、分册 EPUB
- 校验页数、结构和 fixed-layout 语义
- 把最终结果稳定发布到 `library/<漫画名>/`

## 执行要求

- 只使用 `python3 scripts/manga_loader.py <subcommand> ...` 作为正式入口
- 新环境必须先 `bootstrap` 再 `doctor`
- 不要猜 `comic_id`，标题输入先走 `search`
- 最终交付看 `library/`，不是 `runs/`
- `runs/` 只用于过程索引、回放和排障

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

如果宿主环境的通用规则与本仓库冲突，优先遵守 `SKILL.md`。
