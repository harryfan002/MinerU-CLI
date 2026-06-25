# MinerU CLI

> English | [简体中文](./README.md)

Turn PDF / image / Word / PPT / Excel / HTML into **Markdown + JSON** in one command.
Wraps [MinerU](https://mineru.net)'s precise-parsing API — handles tables / formulas / multi-column / scanned docs.

---

## 🎯 One command, any file size

MinerU's API caps a single task at ≤ **200 MB / 200 pages**. This tool sweeps past it for you:

```bash
python scripts/mineru.py parse https://example.com/big.pdf --download ./out
```

A >200-page PDF? It's auto-**split → upload → poll → merged** into one complete `full.md`. You do nothing.
Same for local files: `upload ./big.pdf`. **No manual paging, no picking split points, no stitching back.**

---

## 🚀 How to use (3 steps)

**1. Fill in your token**

Create a token on MinerU's [**API Management page**](https://mineru.net/apiManage/token), then edit `config.json`:

```json
{ "token": "your-real-token" }
```

> `config.json` is gitignored, so your token never enters version control. Confirm it's still the placeholder before committing.

**2. Install deps**

```bash
pip install requests pypdf
```

- `requests`: more robust uploads/downloads (works without it, falls back to stdlib)
- `pypdf`: **required** for auto-chunking — without it, files >200 pp are rejected outright by the API (-60005)

**3. Run it**

```bash
# Have a URL — just parse it
python scripts/mineru.py parse https://xxx.com/doc.pdf --download ./out

# Only a local file
python scripts/mineru.py upload ./file.pdf --download ./out

# Many URLs at once
python scripts/mineru.py batch-url https://a.com/x.pdf https://b.com/y.pdf --download ./out
```

When it finishes, `./out/full.md` is the result, images sit beside it in `./out/images/`.
For HTML you must add `--model MinerU-HTML`.

---

## 📋 Command cheat sheet

| Command | What for |
|---------|----------|
| `parse <URL>` | Parse one URL (oversized PDF auto-chunked + merged) |
| `upload <FILE> [FILE..]` | Parse local files (single oversized PDF auto-chunked; ≤50 files) |
| `batch-url <URL> [URL..]` | Batch URLs (no auto-chunk — oversized is rejected) |
| `status <ID> [--batch]` | Check progress |
| `download <ZIP_URL> <DIR>` | Download & unzip a known result zip |

Common flags: `--model {vlm,pipeline,MinerU-HTML}` (default vlm), `--ocr`, `--page-ranges "1-10"`, `--extra-formats docx html latex`, `--no-poll` (submit without waiting).

Full endpoints / params / `language` values / error codes in [`references/api-reference.md`](./references/api-reference.md),
more examples in [`examples/README.md`](./examples/README.md).

## 🧩 How the merge looks (skippable)

```
out/full.md                  # the parts' Markdown, stitched in order
out/images/                  # deduped images from all parts
out/full_content_list.json   # structured content for programs
out/parts/part_NNN/          # each part's raw artifacts kept for reference
```

- No auto-chunk for: HTML, non-PDF, `batch-url` multi-URL, `upload` multi-file — oversized is API-rejected.
- Force no split: `--split-mode none` (upload) / `--url-split-mode none` (parse).
- Chunking needs polling on (on by default) to merge; `--no-poll` only returns the batch_id.

## ⚙️ Use as a Skill

The layout follows the [Claude Code Skills](https://docs.claude.com/en/docs/claude-code/skills) spec. Drop the whole `mineru/` dir into `~/.claude/skills/mineru/`, then type `/mineru <URL> output to some folder` in Claude Code.

## 🚧 Notes

- Foreign URLs (github, aws) may time out → download to a domestic CDN or upload locally first.
- Rate limits: 50 files/min for submissions, 1000/min for queries.
- 1000 pages/day at top priority per account (downgraded beyond that); HTML has a separate quota.

## 📄 License

[MIT](./LICENSE) · Parsing power and quota come from [MinerU / OpenXLab](https://mineru.net); this tool is only a wrapper around their API.
