# MinerU 精准解析 API 速查

Base URL: `https://mineru.net`  ·  认证 header: `Authorization: Bearer <token>`

## 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v4/extract/task` | 单文件 URL 解析（不支持直传文件）；`parse` 在限内 PDF URL 走此端点 |
| GET  | `/api/v4/extract/task/{task_id}` | 查询单任务结果 |
| POST | `/api/v4/file-urls/batch` | 申请本地文件上传链接（≤50），PUT 上传后系统自动提交解析 |
| POST | `/api/v4/extract/task/batch` | 多 URL 批量解析 |
| GET  | `/api/v4/extract-results/batch/{batch_id}` | 批量查询结果 |

## 单文件解析参数（POST `/api/v4/extract/task`）

| 参数 | 必选 | 默认 | 说明 |
|------|------|------|------|
| `url` | 是 | — | 文件 URL |
| `model_version` | 否 | pipeline | `pipeline` / `vlm`（推荐） / `MinerU-HTML`（HTML 必选） |
| `is_ocr` | 否 | false | OCR，仅 pipeline/vlm |
| `enable_formula` | 否 | true | 公式识别（vlm 仅影响行内公式），仅 pipeline/vlm |
| `enable_table` | 否 | true | 表格识别，仅 pipeline/vlm |
| `language` | 否 | ch | 文档语言，仅 pipeline/vlm |
| `page_ranges` | 否 | — | `"2,4-6"`、`"2--2"`（-2=倒数第二页） |
| `extra_formats` | 否 | — | `["docx","html","latex"]` 之一或多个，对 HTML 无效 |
| `data_id` | 否 | — | 业务数据 ID |
| `no_cache` | 否 | false | 绕过缓存 |
| `cache_tolerance` | 否 | 900 | 缓存容忍秒数 |
| `callback`/`seed` | 否 | — | 回调通知 URL + 签名 seed |

批量上传 (`file-urls/batch`) 与批量 URL (`task/batch`) 参数结构一致：顶层 `model_version` + 各文件 `{name|url, data_id, page_ranges, is_ocr}`。

## 任务状态 `state`

| state | 含义 |
|-------|------|
| `pending` | 排队中 |
| `running` | 解析中（含 `extract_progress.extracted_pages/total_pages`） |
| `converting` | 格式转换中 |
| `waiting-file` | 等待文件上传（批量上传模式） |
| `done` | 完成（返回 `full_zip_url`） |
| `failed` | 失败（返回 `err_msg`） |

## language 取值参考

独立语言包：`ch`（默认，中英繁）、`ch_server`、`en`、`japan`、`korean`、`chinese_cht`、`ta`、`te`、`ka`、`el`、`th`。
语系包：`latin`、`arabic`、`cyrillic`、`east_slavic`、`devanagari`。

## 错误码

| 码 | 说明 |
|----|------|
| A0202 | Token 错误（检查 Bearer 前缀或更换） |
| A0211 | Token 过期，更换 |
| -500 | 传参错误（参数类型/Content-Type） |
| -10001 / -10002 | 服务异常 / 请求参数错误 |
| -60001 | 生成上传 URL 失败 |
| -60002 | 文件格式匹配失败（文件名/链接需带正确后缀） |
| -60003 / -60004 | 文件读取失败 / 空文件 |
| -60005 | 文件大小超限（>200MB） |
| -60006 | 文件页数超限（>200） |
| -60007 | 模型服务暂不可用 |
| -60008 | 文件读取超时（URL 不可访问） |
| -60009 | 提交队列已满 |
| -60010 | 解析失败 |
| -60011 | 获取有效文件失败（确保已上传） |
| -60012 | 找不到任务（task_id 无效） |
| -60013 | 无权限（只能访问自己的任务） |
| -60014 | 运行中的任务不可删 |
| -60015 / -60016 | 文件转换失败 |
| -60017 | 重试次数达上限 |
| -60018 | 每日解析额度用尽 |
| -60019 | HTML 文件解析额度不足 |
| -60020 / -60021 | 文件拆分 / 读取页数失败 |
| -60022 | 网页读取失败（网络/限频） |

## 超过 200 页 / 200MB（自动分页）

API 单任务上限：文件 ≤200MB **且** ≤200 页。本 skill 对以下场景自动分页（傻瓜物理拆分）：

- **`upload` 单本地 PDF**：超 200MB 或超 200 页 → 本地拆分上传合并。
- **`parse` PDF URL**：先下载到临时目录用 pypdf 探页数 —— 在限内（≤200MB 且 ≤200页）则丢弃临时文件、URL 直传 `/api/v4/extract/task`；超限则本地拆分，用 `/api/v4/file-urls/batch` 上传合并（与 `upload` 同一套合并逻辑）。非 PDF URL / HTML 不触发探测，直接 URL 直传。

分片流程（本地 PDF 与 URL 分片共用）：
- 用 pypdf 探测页数（需 `pip install pypdf`；未装则 `parse` URL 直传 / `upload` 按整文件上传，超限会被 API 拒 -60005/-60006）。
- 傻瓜循环：从 `i=1`（不拆）开始，把 PDF 均分成 i 个子文件，每个子文件须同时 ≤200页 且 ≤200MB 才通过；不通过则删了重拆、`i+=1`，直到全通过。
- 把通过的 N 个子文件用 `/api/v4/file-urls/batch` 一次性申请链接、各自 PUT 上传；各子文件 `data_id = "part_NNN__pSTART-END"` 用以排序。
- 轮询 `/api/v4/extract-results/batch/{batch_id}`，每片结果解压到独立临时目录，合并产物到 `--download DIR`：
  - `full.md` ← 各片 Markdown 按序拼接
  - `images/` ← 各片图片去重搬运
  - `full_content_list.json` ← 各片 `*_content_list.json` 合并为单个数组
  - `parts/part_NNN/` ← 各片原始产物（单片 full.md / layout.json / `*_model.json` / 原始 content_list.json）**留存**，不再随临时目录删除
  - 临时下载/解压目录、拆分子文件则在合并后自动清理。

- **不自动分页**的场景：HTML（MinerU-HTML 模型，不支持 `page_ranges`）、非 PDF、`batch-url` 多 URL、`upload` 多文件 —— 超限被 API 拒 -60005/-60006。`--split-mode none`（`upload`）/ `--url-split-mode none`（`parse`）强制不拆。
- 分页需开启轮询（默认开启）才合并；`--no-poll` 只返回 batch_id。

- 提交类接口：50 文件/分钟（单文件解析、file-urls/batch、task/batch 共用）。
- 查询类接口：1000 次/分钟。
- 单用户每日最多上传 5000 文件（其中 HTML 最多 100）。