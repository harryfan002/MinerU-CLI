---
name: mineru
description: Parse PDF/Office/image/HTML documents into structured Markdown, JSON, and optional docx/html/latex via the MinerU precise API. Use when the user wants to extract text/tables/formulas from a document URL or local file, convert a PDF to Markdown, or batch-parse files. Reads token from config.json.
---

# MinerU 文档解析 Skill

把 PDF / 图片 / Word / PPT / Excel / HTML 文档解析成结构化 **Markdown + JSON**（可选 docx/html/latex）。封装的是 MinerU 的 **🎯 精准解析 API**（需 token、≤200MB、≤200 页、支持表格/公式/多栏/扫描件、单文件与批量均支持）。

## 首次使用：配置 token

精准解析 API 需要 token。在 MinerU 官网「**API 管理页面**」自行创建 token，然后编辑本 skill 的 `config.json`，把里面的 `<YOUR_MINERU_TOKEN>` 替换为真实值：

```json
{ "token": "你的真实token" }
```

未配置或仍是占位符时，脚本会报清晰错误并提示。

## 输出布局

每个结果 zip 解压后长这样：

```
DIR/full.md                # Markdown 正文, 图片写相对路径 ![](images/xxx.jpg)
DIR/images/                # 抽取出的图片 (hash 命名)
DIR/*_content_list.json    # 结构化内容列表 (程序消费用)
DIR/layout.json            # 版面中间结果 (很大)
DIR/*_model.json           # 模型推理结果
```

**关键**：`full.md` 和 `images/` 在同一目录并排，md 里写的是相对路径。移动 `full.md` 时要把 `images/` 一起带走，否则图片链接会断。json 文件名带的是每任务随机 ID，不是你的文件名。

**分页合并后**（见下）：顶层 `DIR/full.md` 是拼接后的完整 Markdown，`DIR/images/` 是所有分片图片合并的结果。中间拆分/下载的临时文件运行结束自动清理，只留 `full.md` + `images/`。

## 黑盒用法：先 --help

所有交互通过 `scripts/mineru.py`。**先跑 `--help`，不要读源码**：

```bash
python scripts/mineru.py --help
python scripts/mineru.py parse --help
python scripts/mineru.py upload --help
```

子命令：

| 子命令 | 用途 | 端点 |
|--------|------|------|
| `parse <URL>` | 单文件 URL 解析（PDF URL 先下载探页数；在限内直传 URL，超限自动下载分片合并） | POST /api/v4/extract/task（+ batch） |
| `upload <FILE> [FILE..]` | 本地文件上传解析（单本地 PDF 超 200MB/200页自动分页合并；≤50 个） | POST /api/v4/file-urls/batch + PUT |
| `batch-url <URL> [URL..]` | 多 URL 批量解析 | POST /api/v4/extract/task/batch |
| `status <ID> [--batch]` | 查询任务进度 | GET /api/v4/extract/task/{id} 或 batch |
| `download <ZIP_URL> <DIR>` | 下载并解压结果 zip | full_zip_url |

## 超过 200 页 / 200MB：自动分页（傻瓜物理拆分）

API 单任务上限：文件 ≤200MB **且** ≤200 页。本脚本对下列场景自动处理：

- **单本地 PDF（`upload`）**：超 200MB 或超 200 页自动拆分合并。
- **PDF URL（`parse`）**：先下载到临时目录用 `pypdf` 探测页数——在限内（≤200MB 且 ≤200页）则丢弃临时文件、URL 直传；超限则本地傻瓜拆分、批量上传、轮询、合并（与 `upload` 同一套合并逻辑）。

流程（本地 PDF 和 URL 分片共用）：

1. 用 `pypdf` 探测页数（建议 `pip install pypdf`；未装则 `parse` URL 直传 / `upload` 按整文件上传，超限被 API 拒）。
2. **傻瓜拆分循环**：从 `i=1`（不拆）开始尝试，把 PDF 均分成 i 个子文件；每个子文件都须同时满足 ≤200页 且 ≤200MB 才通过，否则删了重拆、`i+=1`，直到全部通过。
3. N 个子文件批量上传（`file-urls/batch`）→ 轮询 → 每片解压到独立临时目录 → 合并产物到 `--download DIR`（见下）→ 清理拆分子文件与临时目录。
4. `--split-mode none`（`upload`）/ `--url-split-mode none`（`parse`）强制不拆分，超限被 API 拒。

### 分页合并的输出布局

```
DIR/full.md                  # 各片 Markdown 按序拼接 (正文)
DIR/images/                  # 各片图片去重搬运
DIR/full_content_list.json   # 各片 *_content_list.json 合并为单个数组 (程序消费用)
DIR/parts/part_NNN/           # 各片原始产物留存 (原 single full.md / layout.json / *_model.json / 原始 *_content_list.json)
```

即：**顶层只放合并后的成品**（`full.md` + `images/` + `full_content_list.json`），各片原始中间产物**留存**在 `parts/part_NNN/` 不再删除；真正被自动清理的只是临时下载/解压目录与拆分子文件。非分页路径下无 `parts/`。

**不支持分页**：HTML（`MinerU-HTML` 模型）、非 PDF、`batch-url` 多 URL、`upload` 多文件——这些超限会被 API 报错 -60005/-60006。

```bash
# 本地大 PDF: 自动探测、傻瓜拆分、上传、轮询、合并出 full.md + images/ + full_content_list.json
python scripts/mineru.py upload ./big.pdf --download ./out

# 大 PDF URL: 先下载探页数, 超限则自动本地分片合并 (在限内则 URL 直传)
python scripts/mineru.py parse https://example.com/big.pdf --download ./out
```

分页模式**必须开了轮询**（默认开启）才会合并；`--no-poll` 只返回 batch_id，分片结果需自行 `status <batch_id> --batch` 查询后再下载。

## 决策树

```
用户想解析文档 →
  ├─ 有现成的可访问 URL?     → parse <URL>  (HTML 须 --model MinerU-HTML; PDF 先下载探页数, 在限内 URL 直传, 超限自动分片合并)
  ├─ 只有本地文件?           → upload <FILE...>  (单本地 PDF 超 200MB/200页自动分页合并)
  ├─ 多个 URL 一起解析?       → batch-url <URL...>  (不自动分页)
  └─ 只想查已有任务进度?       → status <task_id>  /  status <batch_id> --batch
```

**模型选择**：默认 `vlm`（推荐，复杂版式/表格/公式最强）。解析 **HTML** 文件必须显式 `--model MinerU-HTML`（脚本对 .html/.htm 会自动转 MinerU-HTML，但建议显式指定）。`pipeline` 为非 vlm 轻量模型。**HTML 不支持分页**。

## 典型示例

单文件 URL 解析到 Markdown（提交 + 轮询 + 下载解压）：

```bash
python scripts/mineru.py parse https://cdn-mineru.openxlab.org.cn/demo/example.pdf \
  --model vlm --download ./out
# 完成后 ./out/full.md 即 Markdown 结果，另有 layout.json / content_list.json 等
```

仅提交不轮询（只要 task_id，稍后自行查询）：

```bash
python scripts/mineru.py parse https://example.com/doc.pdf --no-poll
python scripts/mineru.py status <task_id>
```

本地文件上传解析（系统自动提交，按 batch 轮询）：

```bash
python scripts/mineru.py upload ./a.pdf ./b.pdf --model vlm --download ./out
```

带额外导出格式 / 页码范围 / OCR：

```bash
python scripts/mineru.py parse https://example.com/scan.pdf \
  --ocr --page-ranges "1-10" --extra-formats docx html --download ./out
```

批量 URL 解析：

```bash
python scripts/mineru.py batch-url https://x.com/a.pdf https://x.com/b.pdf --download ./out
```

## 限制与注意

- 文件 ≤ **200MB**；单任务 ≤ **200 页**（`upload` 单本地 PDF、`parse` PDF URL 超限均自动分页合并，见上；HTML/非PDF/`batch-url`/多文件超限不自动分页会被 API 拒 -60005/-60006）。每账号每日 1000 页最高优先级，超出降级。
- 国外 URL（github、aws 等）可能因网络限制请求超时 → 建议先把文件下载到国内 CDN 或本地上传。
- 限频：提交类接口 50 文件/分钟，查询类 1000 次/分钟；超出返回错误码或 429。
- HTML 文件解析额度独立（每日有限）。
- 输出 zip 内容参考 MinerU 文档：`full.md`=Markdown，`layout.json`=中间结果，`*_content_list.json`=内容列表。

## 速查

完整端点、参数、`language` 取值、错误码见 `references/api-reference.md`。