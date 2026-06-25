# MinerU Skill 使用示例

> 首次使用前请先在 `../config.json` 填入 token。

所有命令以本 skill 的 `scripts/mineru.py` 为入口，例如：
`python C:/Users/Fan/.claude/skills/mineru/scripts/mineru.py ...`

## 1. 解析一个在线 PDF 到 Markdown

```bash
python scripts/mineru.py parse https://cdn-mineru.openxlab.org.cn/demo/example.pdf \
  --model vlm --download ./out
# 结果: ./out/full.md (+ layout.json, content_list.json 等)
```

## 2. 仅提交，稍后查询（异步工作流）

```bash
python scripts/mineru.py parse https://example.com/doc.pdf --no-poll
# 输出 task_id, 之后:
python scripts/mineru.py status <task_id>
```

## 3. 本地文件上传解析

```bash
python scripts/mineru.py upload ./report.pdf ./slides.pptx --download ./out
# 系统自动提交, 脚本按 batch_id 轮询全部完成
```

## 4. 扫描件 + OCR + 页码范围 + 额外格式

```bash
python scripts/mineru.py parse https://example.com/scanned.pdf \
  --ocr --page-ranges "1-5" --extra-formats docx html --download ./out
```

## 5. 批量解析多个 URL

```bash
python scripts/mineru.py batch-url https://x.com/a.pdf https://x.com/b.pdf \
  --download ./out
```

## 6. 解析 HTML 页面（必须 MinerU-HTML 模型）

```bash
python scripts/mineru.py parse https://example.com/article.html \
  --model MinerU-HTML --download ./out
# 输出含 full.md 与 main.html
```

## 7. 只查已有任务进度

```bash
python scripts/mineru.py status <task_id>            # 单任务
python scripts/mineru.py status <batch_id> --batch   # 批量
```

## 8. 手动下载已得到的结果 zip

```bash
python scripts/mineru.py download https://cdn-mineru.openxlab.org.cn/pdf/xxx.zip ./out
```