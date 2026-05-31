# 拷贝漫画 EPUB 下载器

[English](README.md) | [简体中文](README.zh-CN.md)

非官方 CopyManga / 拷贝漫画下载与 fixed-layout EPUB 打包工作流，可直接作为 CLI 工具使用，也可作为本地 Agent Skill 使用。

<p>
  <img src="https://img.shields.io/badge/Source-CopyManga-16a34a?style=flat-square" alt="CopyManga" />
  <img src="https://img.shields.io/badge/Output-EPUB%20%7C%20Omnibus%20%7C%20Volumes-7c3aed?style=flat-square" alt="Output" />
  <img src="https://img.shields.io/badge/Agent%20Skill-CLI%20First-2563eb?style=flat-square" alt="Agent Skill" />
  <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="License" />
</p>

## 功能

- 按标题或 `comic_id` 搜索拷贝漫画
- 下载章节图片
- 生成单章 fixed-layout EPUB
- 生成合订本 EPUB
- 按章节数把长篇拆成分册 EPUB
- 用 `--resume` 续跑未完成下载
- 校验 EPUB 结构、页数和漫画 fixed-layout 元数据
- 发布最终结果到稳定 `library/`
- 可选发布到外部书库结构：`分章/`、`合订本/完整版.epub`、`历史备份/`

## 安装

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git
cd manga-loader-skill
python3 scripts/manga_loader.py bootstrap
```

要求：

- Python 3.11+
- Linux 或类 Linux shell 环境
- 能访问 CopyManga API
- 如果内置下载器二进制不适配当前平台，需要 Rust/Cargo 重新构建

仓库根目录本身也是 skill 目录。安装到本地 Codex skill：

```bash
git clone https://github.com/Sanssssssssssssssss/manga-loader-skill.git \
  ~/.codex/skills/manga-loader
```

请使用完整 clone。某些 sparse installer 可能漏掉 `scripts/`、`vendor/` 等必要目录。

## 用法

```bash
# 环境体检
python3 scripts/manga_loader.py doctor --check-network

# 搜索
python3 scripts/manga_loader.py search --query "葬送的芙莉莲"

# 下载并生成 EPUB
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲"

# 只下载 1 章做 smoke test
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --chapter-limit 1

# 续跑未完成任务
python3 scripts/manga_loader.py download-full --query "葬送的芙莉莲" --resume

# 生成分册
python3 scripts/manga_loader.py download-full \
  --query "葬送的芙莉莲" \
  --split-chapters-per-volume 40

# 创建订阅并立即执行
python3 scripts/manga_loader.py subscribe --query "葬送的芙莉莲" --run-now

# 刷新全部订阅
python3 scripts/manga_loader.py subscriptions run --all
```

CopyManga 搜索通常使用中文标题或已知 `comic_id` 更稳定。

## EPUB 检查

```bash
# 结构校验
python3 scripts/manga_loader.py validate-epub \
  --path "library/<title>/merged/<file>.epub"

# 页数对账
python3 scripts/manga_loader.py compare-pages \
  --chapter-epub-dir "library/<title>/chapters" \
  --merged "library/<title>/merged/<file>.epub"

# fixed-layout 漫画语义审计
python3 scripts/epub_audit.py --path "library/<title>/merged/<file>.epub"

# 大文件重复校验
python3 scripts/epub_pressure.py --path "library/<title>/merged/<file>.epub"
```

## 重建

```bash
# 从现有单章 EPUB 重建合订本
python3 scripts/manga_loader.py rebuild-merged \
  --chapter-epub-dir "library/<title>/chapters" \
  --output "library/<title>/merged/<title> 合订版.epub" \
  --title "<title>" \
  --author "<author>"

# 从现有单章 EPUB 重建分册
python3 scripts/manga_loader.py rebuild-split \
  --chapter-epub-dir "library/<title>/chapters" \
  --output-dir "library/<title>/volumes" \
  --title "<title>" \
  --author "<author>" \
  --chapters-per-volume 40
```

## 输出结构

```text
library/<title>/
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

- `library/`：稳定阅读产物
- `runs/`：过程数据和调试报告
- `state/`：订阅状态

本机运行目录不会提交到仓库。新 clone 第一次执行 `bootstrap` 和下载命令后，会生成自己的 `config/settings.json`、`runs/`、`library/`、`state/`。

## 外部书库发布

在 `config/settings.json` 配置 `publish.mangabooks_root` 后运行：

```bash
python3 scripts/manga_loader.py publish-library --title "<title>"
```

输出：

```text
<mangabooks_root>/<title>/
  分章/
  合订本/完整版.epub
  历史备份/
```

## Agent Skill

仓库包含 `SKILL.md`，可被 Codex、Claude Code 或其他本地 Agent 读取。稳定公开入口是：

```bash
python3 scripts/manga_loader.py <subcommand>
```

Agent 应通过 `report.json`、`validation.valid`、`audit.reader_ready` 判断任务是否成功。

## 配置

`bootstrap` 会基于 `config/settings.example.json` 生成 `config/settings.json`。

主要配置：

- `downloader`：API 域名、重试、并发
- `packaging`：EPUB 命名、KCC profile、阅读方向、分册策略
- `publish`：外部书库根目录、合订本文件名、历史备份策略

## 测试

```bash
python3 -m unittest discover -s tests
```

## 上游参考

这个工作流参考了以下项目：

- [Kindle Comic Converter (KCC)](https://github.com/ciromattia/kcc)：漫画 EPUB 相关约定
- [copymanga-downloader](https://github.com/lanyeeee/copymanga-downloader)：拷贝漫画下载行为
- [MangaEpubAutomation](https://github.com/YuxuanHan0326/MangaEpubAutomation)：漫画转 EPUB 工作流思路

许可证说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 声明

本项目不是拷贝漫画官方客户端，也不隶属于任何内容提供方。请只在你有权访问和归档内容的前提下使用，并遵守源站规则、版权要求和所在地法律。

## License

[MIT](LICENSE)
