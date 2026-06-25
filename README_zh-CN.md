# MinerU CLI

> [English](./README_en-US.md) | 简体中文

把 PDF / 图片 / Word / PPT / Excel / HTML 一键解析成 **Markdown + JSON**。
封装 [MinerU](https://mineru.net) 精准解析 API，支持表格 / 公式 / 多栏 / 扫描件。

---

## 🎯 一个命令，搞定超大文件

MinerU API 单任务只能 ≤ **200MB / 200 页**。本工具自动帮你绕过：

```bash
python scripts/mineru.py parse https://example.com/big.pdf --download ./out
```

超过200页的 PDF？自动**拆 → 传 → 轮询 → 合并**成一个完整的 `full.md`，你什么都不用管。
本地大文件同理：`upload ./big.pdf`。**不用手动分页、不用挑切分点、不用自己拼回来。**

---

## 🚀 怎么用（三步）

**1. 填 token**

到 MinerU 官网 [**API 管理页面**](https://mineru.net/apiManage/token)创建 token，改 `config.json`：

```json
{ "token": "你的真实token" }
```

> `config.json` 已被 `.gitignore` 忽略，密钥不会进版本库。提交前确认它还是占位符。

**2. 安装依赖**

```bash
pip install requests pypdf
```

- `requests`：上传下载更稳更快（不装也能用，自动回退 stdlib）
- `pypdf`：**必装**才能自动分片——否则超 200 页的文件会被 API 直接拒（-60005）

**3. 跑命令**

```bash
# 有 URL 直接解析
python scripts/mineru.py parse https://xxx.com/doc.pdf --download ./out

# 只有本地文件
python scripts/mineru.py upload ./file.pdf --download ./out

# 一堆 URL 一起
python scripts/mineru.py batch-url https://a.com/x.pdf https://b.com/y.pdf --download ./out
```

完成后 `./out/full.md` 就是结果，图片在 `./out/images/` 并排。
解析 HTML 必须加 `--model MinerU-HTML`。

---

## 📋 指令速查

| 指令 | 干嘛用 |
|------|--------|
| `parse <URL>` | 解析一个 URL（PDF 超限自动分片合并） |
| `upload <FILE> [FILE..]` | 解析本地文件（单 PDF 超限自动分片合并；≤50 个） |
| `batch-url <URL> [URL..]` | 批量 URL（不自动分片，超限被拒） |
| `status <ID> [--batch]` | 查进度 |
| `download <ZIP_URL> <DIR>` | 下载解压已知结果 zip |

常用参数：`--model {vlm,pipeline,MinerU-HTML}`（默认 vlm）、`--ocr`、`--page-ranges "1-10"`、`--extra-formats docx html latex`、`--no-poll`（只提交不等）。

完整端点 / 参数 / `language` 取值 / 错误码见 [`references/api-reference.md`](./references/api-reference.md)，
更多示例见 [`examples/README.md`](./examples/README.md)。

## 🧩 自动分片怎么合的（可跳过）

```
out/full.md                  # 各片 Markdown 按序拼好的完整正文
out/images/                  # 各片图片去重搬运
out/full_content_list.json   # 结构化内容，给程序消费
out/parts/part_NNN/          # 各片原始产物留存备查
```

- 不自动分页的场景：HTML、非 PDF、`batch-url` 多 URL、`upload` 多文件——超限被 API 拒。
- 强制不拆：`--split-mode none`（upload）/ `--url-split-mode none`（parse）。
- 分片必须开着轮询（默认开）才合并；`--no-poll` 只返回 batch_id。

## ⚙️ 当 Skill 用

目录结构遵循 [Claude Code Skills](https://docs.claude.com/en/docs/claude-code/skills) 规范。把整个 `mineru/` 丢进 `~/.claude/skills/mineru/`，在 Claude Code 里输入 `/mineru <URL> 输出到某文件夹` 即可。

## 🚧 注意

- 国外 URL（github、aws）可能超时 → 先下到国内 CDN 或本地上传。
- 限频：提交 50 文件/分钟，查询 1000 次/分钟。
- 每日 1000 页最高优先级，超出降级；HTML 额度独立。

## 📄 License

[MIT](./LICENSE) · 解析能力与额度由 [MinerU / OpenXLab](https://mineru.net) 提供，本工具仅是其 API 的封装。
