#!/usr/bin/env python3
"""MinerU 精准解析 API 命令行封装。

子命令:
  parse <URL>            单文件 URL 解析 (POST /api/v4/extract/task)
  upload <FILE> [FILE..] 本地文件批量上传解析 (POST /api/v4/file-urls/batch + PUT)
  batch-url <URL> [URL..] 批量 URL 解析 (POST /api/v4/extract/task/batch)
  status <ID>            查询任务/批量进度 [--batch]
  download <ZIP_URL> <DIR> 下载并解压结果 zip

token 从 ../config.json 的 "token" 字段读取。

请先运行: python scripts/mineru.py --help
        python scripts/mineru.py <subcommand> --help

输出布局 (每个结果 zip 解压后):
  DIR/full.md            Markdown 正文 (图片引用 ![](images/xxx.jpg))
  DIR/images/            抽取出的图片 (hash 命名)
  DIR/*_content_list.json 内容列表 (结构化)
  DIR/layout.json        版面中间结果
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

try:
    import requests  # type: ignore
    _HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    _HAS_REQUESTS = False

try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
    _HAS_PYPDF = True
except ImportError:
    try:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore
        _HAS_PYPDF = True
    except ImportError:
        _HAS_PYPDF = False

BASE_URL = "https://mineru.net"
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

STATE_LABELS = {
    "pending": "排队中",
    "running": "解析中",
    "converting": "格式转换中",
    "waiting-file": "等待文件上传",
    "uploading": "文件下载中",
    "done": "完成",
    "failed": "失败",
}

ERROR_CODES = {
    "A0202": "Token 错误，检查是否有 Bearer 前缀或更换新 Token",
    "A0211": "Token 过期，更换新 Token",
    "-500": "传参错误，确保参数类型及 Content-Type 正确",
    "-10001": "服务异常，请稍后再试",
    "-10002": "请求参数错误，检查请求参数格式",
    "-60001": "生成上传 URL 失败，请稍后再试",
    "-60002": "获取匹配的文件格式失败，文件名/链接需带正确后缀，且为 pdf,doc,docx,ppt,pptx,xls,xlsx,png,jp(e)g",
    "-60003": "文件读取失败，请检查文件是否损坏并重新上传",
    "-60004": "空文件，请上传有效文件",
    "-60005": "文件大小超出限制 (<=200MB)",
    "-60006": "文件页数超过限制 (<=200页)",
    "-60007": "模型服务暂时不可用，请稍后重试或联系技术支持",
    "-60008": "文件读取超时，检查 URL 可访问",
    "-60009": "任务提交队列已满，请稍后再试",
    "-60010": "解析失败，请稍后再试",
    "-60011": "获取有效文件失败，请确保文件已上传",
    "-60012": "找不到任务，请确保 task_id 有效且未删除",
    "-60013": "没有权限访问该任务，只能访问自己提交的任务",
    "-60014": "删除运行中的任务，运行中的任务暂不支持删除",
    "-60015": "文件转换失败，可手动转为 pdf 再上传",
    "-60016": "文件转换失败，可尝试其他格式导出或重试",
    "-60017": "重试次数达到上限，等后续模型升级后重试",
    "-60018": "每日解析任务数量已达上限，明日再来",
    "-60019": "html 文件解析额度不足，明日再来",
    "-60020": "文件拆分失败，请稍后重试",
    "-60021": "读取文件页数失败，请稍后重试",
    "-60022": "网页读取失败，可能因网络问题或限频，请稍后重试",
}

VALID_LANGUAGES = {
    "ch", "ch_server", "en", "japan", "korean", "chinese_cht",
    "ta", "te", "ka", "el", "th",
    "latin", "arabic", "cyrillic", "east_slavic", "devanagari",
}
VALID_MODELS = {"pipeline", "vlm", "MinerU-HTML"}
VALID_EXTRA_FORMATS = {"docx", "html", "latex"}


# --------------------------- HTTP helpers ---------------------------

def _http(method, url, headers=None, json_body=None, data=None):
    if _HAS_REQUESTS:
        resp = requests.request(method, url, headers=headers, json=json_body,
                                data=data, timeout=300)
        text = resp.text
        try:
            return resp.status_code, resp.json(), text
        except Exception:
            return resp.status_code, None, text
    else:
        req = urllib.request.Request(url, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        elif data is not None:
            body = data if isinstance(data, bytes) else data
        try:
            with urllib.request.urlopen(req, data=body, timeout=300) as r:
                status = r.getcode()
                text = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status = e.code
            text = e.read().decode("utf-8", "replace")
        try:
            return status, json.loads(text), text
        except Exception:
            return status, None, text


def _get(url, headers=None):
    return _http("GET", url, headers=headers)


def _post(url, headers=None, json_body=None):
    return _http("POST", url, headers=headers, json_body=json_body)


def _put_raw(url, file_path):
    with open(file_path, "rb") as f:
        data = f.read()
    if _HAS_REQUESTS:
        resp = requests.put(url, data=data, timeout=600)
        return resp.status_code, resp.text
    else:
        req = urllib.request.Request(url, data=data, method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.getcode(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")


def _download_file(url, out_path):
    if _HAS_REQUESTS:
        resp = requests.get(url, timeout=600)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(resp.content)
    else:
        with urllib.request.urlopen(url, timeout=600) as r:
            with open(out_path, "wb") as f:
                f.write(r.read())


# --------------------------- Token ---------------------------

def load_token():
    cfg = os.path.join(SKILL_ROOT, "config.json")
    if not os.path.exists(cfg):
        die("未找到 config.json。请在 %s 中创建 config.json 并写入 {\"token\": \"你的token\"}。"
            " token 可在 MinerU 官网「API 管理页面」自行创建。" % cfg)
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        die("config.json 解析失败: %s" % e)
    token = config.get("token", "")
    if not token or token == "<YOUR_MINERU_TOKEN>":
        die("config.json 中的 token 仍为占位符。请在 MinerU 官网「API 管理页面」创建 token，"
            "然后替换 %s 里的 <YOUR_MINERU_TOKEN>。" % cfg)
    return token


def auth_headers(token):
    return {"Content-Type": "application/json", "Authorization": "Bearer %s" % token}


# --------------------------- Output helpers ---------------------------

def die(msg, code=1):
    sys.stderr.write("[mineru] 错误: %s\n" % msg)
    sys.exit(code)


def info(msg):
    print("[mineru] %s" % msg, file=sys.stderr)


def print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def err_hint(code):
    if code is None:
        return ""
    return ERROR_CODES.get(str(code), "")


def check_api_result(result, action):
    if not isinstance(result, dict):
        die("%s 响应非 JSON。" % action)
    code = result.get("code")
    if code != 0 and code != "0":
        msg = result.get("msg", "")
        hint = err_hint(code)
        die("%s 失败: code=%s msg=%s %s" % (action, code, msg, ("(" + hint + ")" if hint else "")))


# --------------------------- Polling ---------------------------

def poll_single(token, task_id, timeout, interval, download_dir):
    url = "%s/api/v4/extract/task/%s" % (BASE_URL, task_id)
    start = time.time()
    while True:
        status, result, _ = _get(url, auth_headers(token))
        if status != 200 or not isinstance(result, dict):
            die("查询任务失败: HTTP %s" % status)
        data = result.get("data", {})
        state = data.get("state", "")
        elapsed = int(time.time() - start)
        if state == "done":
            full_zip_url = data.get("full_zip_url", "")
            info("[%ds] 解析完成。" % elapsed)
            print_json(result)
            if download_dir and full_zip_url:
                download_and_unzip(full_zip_url, download_dir)
            return result
        if state == "failed":
            err = data.get("err_msg", "未知错误")
            info("[%ds] 解析失败: %s" % (elapsed, err))
            print_json(result)
            sys.exit(2)
        label = STATE_LABELS.get(state, state)
        prog = data.get("extract_progress") or {}
        extra = " (%s/%s 页)" % (prog.get("extracted_pages", "?"),
                                 prog.get("total_pages", "?")) if prog else ""
        info("[%ds] %s%s..." % (elapsed, label, extra))
        if time.time() - start >= timeout:
            info("轮询超时 (%ds)。手动查询: python mineru.py status %s" % (timeout, task_id))
            print_json(result)
            sys.exit(3)
        time.sleep(interval)


def poll_batch(token, batch_id, timeout, interval, download_dir):
    url = "%s/api/v4/extract-results/batch/%s" % (BASE_URL, batch_id)
    start = time.time()
    while True:
        status, result, _ = _get(url, auth_headers(token))
        if status != 200 or not isinstance(result, dict):
            die("查询批量任务失败: HTTP %s" % status)
        results = result.get("data", {}).get("extract_result", []) or []
        done_count = sum(1 for r in results if r.get("state") == "done")
        failed_count = sum(1 for r in results if r.get("state") == "failed")
        total = len(results)
        elapsed = int(time.time() - start)
        info("[%ds] 批量进度: %s 完成 / %s 失败 / %s 总计" % (elapsed, done_count, failed_count, total))
        if total and done_count + failed_count >= total:
            info("批量任务全部结束。")
            print_json(result)
            if download_dir:
                for r in results:
                    if r.get("state") == "done" and r.get("full_zip_url"):
                        sub = os.path.join(download_dir, _safe_name(r.get("file_name", "result")))
                        download_and_unzip(r["full_zip_url"], sub)
            if failed_count:
                sys.exit(2)
            return result
        if time.time() - start >= timeout:
            info("轮询超时 (%ds)。手动查询: python mineru.py status %s --batch" % (timeout, batch_id))
            print_json(result)
            sys.exit(3)
        time.sleep(interval)


def _safe_name(name):
    keep = "-_.()"
    return "".join(c if (c.isalnum() or c in keep) else "_" for c in name) or "result"


def download_and_unzip(zip_url, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, "_result.zip")
    info("下载结果 zip -> %s" % zip_path)
    try:
        _download_file(zip_url, zip_path)
    except Exception as e:
        die("下载失败: %s (URL=%s)" % (e, zip_url))
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out_dir)
        info("已解压到: %s (含 full.md 等)" % os.path.abspath(out_dir))
    except Exception as e:
        die("解压失败: %s" % e)
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass


# --------------------------- Pagination (foolproof) ---------------------------
# 傻瓜拆分: 单本地 PDF 若 >200MB 或 >200页, 均分 i=1,2,3... 片, 每片都满足
# <=200页 且 <=200MB 才通过, 否则删了重拆。通过后批量上传、轮询、合并 full.md+images。
MAX_SIZE_BYTES = 200 * 1024 * 1024
MAX_PAGES = 200


def _pdf_pages(fp):
    if not _HAS_PYPDF:
        return None
    try:
        return len(PdfReader(fp).pages)
    except Exception:
        return None


def _need_split(fp):
    """是否需要分页拆分: 文件超 200MB 或超 200 页。需 pypdf 探页数。"""
    sz = os.path.getsize(fp)
    if sz > MAX_SIZE_BYTES:
        return True  # 体积超标, 必须拆(逻辑上传不上去)
    if not fp.lower().endswith(".pdf"):
        return False
    n = _pdf_pages(fp)
    return n is not None and n > MAX_PAGES


def _split_foolproof(fp):
    """傻瓜循环: 均分 i 片, 每片 <=200页 且 <=200MB。返回 [(part_path, start, end), ...]。"""
    reader = PdfReader(fp)
    total = len(reader.pages)
    tmp_dir = tempfile.mkdtemp(prefix="mineru_split_")
    i = 1
    while True:
        parts = _even_split_paths(reader, total, i, tmp_dir)
        if all(_part_ok(p) for p in parts):
            info("拆分通过: %d 页 -> %d 片" % (total, i))
            return [(p,) + rng for p, rng in zip(parts, _even_ranges(total, i))]
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass
        i += 1
        if i > 200:
            die("拆分到 %d 片仍未满足双约束, 放弃。" % i)


def _even_ranges(total, i):
    base, rem = total // i, total % i
    ranges, start = [], 1
    for k in range(i):
        size = base + (1 if k < rem else 0)
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def _even_split_paths(reader, total, i, tmp_dir):
    rngs = _even_ranges(total, i)
    paths = []
    for idx, (s, e) in enumerate(rngs, 1):
        path = os.path.join(tmp_dir, "part_%03d.pdf" % idx)
        w = PdfWriter()
        for pg in reader.pages[s - 1:e]:
            w.add_page(pg)
        with open(path, "wb") as f:
            w.write(f)
        paths.append(path)
    return paths


def _part_ok(p):
    sz = os.path.getsize(p)
    if sz > MAX_SIZE_BYTES:
        info("  %s: %.1fMB [FAIL 体积]" % (os.path.basename(p), sz / 1024 / 1024))
        return False
    n = _pdf_pages(p)
    if n is None or n > MAX_PAGES:
        info("  %s: %s [FAIL 页数]" % (os.path.basename(p), n if n is not None else "?"))
        return False
    info("  %s: %d页 %.1fMB [OK]" % (os.path.basename(p), n, sz / 1024 / 1024))
    return True


def _upload_and_merge_parts(token, ns, parts_with_ranges):
    """parts_with_ranges: [(part_path, start, end)...]。批量申请链接、上传、轮询、下载合并。
       复用者注意: ns.files[0] 应指向被拆分的本地 PDF 路径(url 分片场景已预先下载)。"""
    parts = [(p, s, e) for p, s, e in parts_with_ranges]
    files_body = []
    for idx, (p, s, e) in enumerate(parts, 1):
        did = "part_%03d__p%d-%d" % (idx, s, e)
        files_body.append({"name": os.path.basename(p), "data_id": did})
    body = {"files": files_body, "model_version": ns.model}
    body.update(_global_opt_fields(ns))
    info("申请上传链接 (%d 片)..." % len(parts))
    status, result, _ = _post(BASE_URL + "/api/v4/file-urls/batch",
                              auth_headers(token), json_body=body)
    if status != 200:
        die("申请上传链接失败: HTTP %s" % status)
    check_api_result(result, "申请上传链接")
    batch_id = result["data"]["batch_id"]
    urls = result["data"]["file_urls"]
    info("batch_id = %s" % batch_id)
    if len(urls) != len(parts):
        die("返回的上传链接数量与分片数不一致")
    for idx, ((p, s, e), up_url) in enumerate(zip(parts, urls), 1):
        info("上传分片 %d/%d: p%d-%d" % (idx, len(parts), s, e))
        code, _ = _put_raw(up_url, p)
        if code not in (200, 201):
            die("上传分片 %d 失败: HTTP %s" % (idx, code))
    info("全部上传完成, 系统自动提交解析任务。")
    # 删临时拆分文件
    tmp_dir = os.path.dirname(parts[0][0])
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if not ns.poll:
        info("分页模式需轮询才能合并; 已返回 batch_id, 可稍后: python mineru.py status %s --batch" % batch_id)
        print_json(result)
        return
    res = _poll_batch_noeat(token, batch_id, ns.timeout, ns.interval)
    results = res.get("data", {}).get("extract_result", []) or []
    zip_urls = {}
    for r in results:
        if r.get("state") == "done" and r.get("full_zip_url"):
            zip_urls[r.get("data_id", "")] = r["full_zip_url"]
        elif r.get("state") == "failed":
            info("分片失败: %s -> %s" % (r.get("data_id", "?"), r.get("err_msg", "")))
    if not zip_urls:
        die("无已完成分片可合并。")
    if ns.download:
        _merge_parts(zip_urls, ns.download)
    else:
        info("未指定 --download, 仅打印结果 JSON。各分片 full_zip_url 见上方。")
        print_json(res)
    if len(zip_urls) != len(parts):
        sys.exit(2)


def _poll_batch_noeat(token, batch_id, timeout, interval):
    """轮询批量任务, 全部终态后返回 result (不下载, 不因失败退出)。"""
    url = "%s/api/v4/extract-results/batch/%s" % (BASE_URL, batch_id)
    start = time.time()
    while True:
        status, result, _ = _get(url, auth_headers(token))
        if status != 200 or not isinstance(result, dict):
            die("查询批量任务失败: HTTP %s" % status)
        results = result.get("data", {}).get("extract_result", []) or []
        done = sum(1 for r in results if r.get("state") == "done")
        fail = sum(1 for r in results if r.get("state") == "failed")
        total = len(results)
        elapsed = int(time.time() - start)
        info("[%ds] 批量进度: %s 完成 / %s 失败 / %s 总计" % (elapsed, done, fail, total))
        if total and done + fail >= total:
            info("批量任务全部结束。")
            print_json(result)
            return result
        if time.time() - start >= timeout:
            info("轮询超时 (%ds)。手动查询: python mineru.py status %s --batch" % (timeout, batch_id))
            print_json(result)
            sys.exit(3)
        time.sleep(interval)


def _find_content_list(sub):
    """在解压目录里找 *_content_list.json (文件名带随机任务 ID)。"""
    for fn in os.listdir(sub):
        if fn.endswith("_content_list.json") and os.path.isfile(os.path.join(sub, fn)):
            return os.path.join(sub, fn)
    return None


def _merge_parts(zip_urls, out_dir):
    """zip_urls: {data_id: full_zip_url}。每片解压到独立临时目录, 合并产物到 out_dir:
       - full.md          各片 Markdown 按序拼接
       - images/          各片图片去重搬运
       - full_content_list.json  各片 content_list 合并成单个数组
       - parts/part_NNN/  各片原始产物 (layout.json / *_model.json / 原始 content_list.json / 单片 full.md) 留存, 不再随临时目录删除
       临时下载/解压目录仍清理; 上述产物则是真正要保留的, 不清理。"""
    final_img = os.path.join(out_dir, "images")
    parts_dir = os.path.join(out_dir, "parts")
    os.makedirs(final_img, exist_ok=True)
    os.makedirs(parts_dir, exist_ok=True)
    md_parts = []
    content_blocks = []
    img_n = 0
    # 按 data_id (part_NNN__...) 排序
    for did in sorted(zip_urls):
        info("下载分片: %s" % did)
        sub = tempfile.mkdtemp(prefix="mineru_chunk_")
        zpath = os.path.join(sub, "_tmp.zip")
        try:
            _download_file(zip_urls[did], zpath)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(sub)
        except Exception as e:
            die("下载/解压分片 %s 失败: %s" % (did, e))
            return
        try:
            os.remove(zpath)
        except OSError:
            pass
        # Markdown 正文 (读入内存待拼接)
        fm = os.path.join(sub, "full.md")
        if os.path.exists(fm):
            md_parts.append(open(fm, "r", encoding="utf-8", errors="replace").read())
        # 合并 content_list (程序消费用)
        cl = _find_content_list(sub)
        if cl:
            try:
                with open(cl, "r", encoding="utf-8") as cf:
                    blocks = json.load(cf)
                if isinstance(blocks, list):
                    content_blocks.extend(blocks)
            except Exception as e:
                info("读取 content_list 失败 (%s): %s" % (did, e))
        # 图片搬运 (名字冲突保留首个)
        imgdir = os.path.join(sub, "images")
        if os.path.isdir(imgdir):
            for fn in os.listdir(imgdir):
                src_img = os.path.join(imgdir, fn)
                if not os.path.isfile(src_img):
                    continue
                dst_img = os.path.join(final_img, fn)
                if not os.path.exists(dst_img):
                    # os.replace 不支持跨卷 (WinError 17), 用 shutil.move 兼容跨驱动器
                    shutil.move(src_img, dst_img)
                    img_n += 1
                else:
                    os.remove(src_img)
        # 各片原始产物留存到 parts/part_NNN/ (layout.json / *_model.json / content_list.json / 单片 full.md)
        part_keep = os.path.join(parts_dir, did)
        os.makedirs(part_keep, exist_ok=True)
        for fn in os.listdir(sub):
            src = os.path.join(sub, fn)
            if fn == "images":
                continue  # 已搬运到顶层 images/
            try:
                shutil.move(src, os.path.join(part_keep, fn))
            except Exception as e:
                info("留存 %s/%s 失败: %s" % (did, fn, e))
        shutil.rmtree(sub, ignore_errors=True)
    merged = os.path.join(out_dir, "full.md")
    with open(merged, "w", encoding="utf-8") as f:
        f.write("\n\n".join(md_parts))
    if content_blocks:
        clp = os.path.join(out_dir, "full_content_list.json")
        with open(clp, "w", encoding="utf-8") as f:
            json.dump(content_blocks, f, ensure_ascii=False, indent=2)
        info("合并 content_list -> %s (%d 条)" % (clp, len(content_blocks)))
    info("分页合并完成: %s (%d 分片, %d 图); 各片原始产物留存于 %s"
         % (os.path.abspath(merged), len(md_parts), img_n, os.path.abspath(parts_dir)))


# --------------------------- Common options ---------------------------

def add_common_options(p):
    p.add_argument("--model", default="vlm", choices=sorted(VALID_MODELS),
                   help="模型版本: vlm(默认,推荐) / pipeline / MinerU-HTML(仅HTML)")
    p.add_argument("--ocr", dest="is_ocr", action="store_true", default=None,
                   help="启用 OCR (默认 false)")
    p.add_argument("--no-ocr", dest="is_ocr", action="store_false", help="禁用 OCR")
    p.add_argument("--formula", dest="enable_formula", action="store_true",
                   default=None, help="开启公式识别 (默认 true)")
    p.add_argument("--no-formula", dest="enable_formula", action="store_false",
                   help="关闭公式识别")
    p.add_argument("--table", dest="enable_table", action="store_true",
                   default=None, help="开启表格识别 (默认 true)")
    p.add_argument("--no-table", dest="enable_table", action="store_false",
                   help="关闭表格识别")
    p.add_argument("--language", default=None,
                   help="文档语言 ch/en/japan/korean/...(默认 ch)")
    p.add_argument("--page-ranges", default=None,
                   help='页码范围, 如 "1-10,2--2" (-2=倒数第二页)')
    p.add_argument("--extra-formats", nargs="*", default=None,
                   choices=sorted(VALID_EXTRA_FORMATS),
                   help="额外导出格式 docx/html/latex (markdown/json 默认含)")
    p.add_argument("--data-id", default=None, help="业务数据 ID")
    p.add_argument("--no-cache", dest="no_cache", action="store_true", help="绕过缓存")
    p.add_argument("--cache-tolerance", type=int, default=None,
                   help="缓存容忍时间(秒), 默认 900")
    p.add_argument("--no-poll", dest="poll", action="store_false", default=True,
                   help="提交后不轮询, 仅返回 task_id/batch_id")
    p.add_argument("--timeout", type=int, default=600, help="轮询超时(秒), 默认 600")
    p.add_argument("--interval", type=int, default=3, help="轮询间隔(秒), 默认 3")
    p.add_argument("--download", default=None, metavar="DIR",
                   help="完成后下载并解压结果 zip 到此目录")


def build_opt_fields(ns):
    f = _global_opt_fields(ns)
    if ns.page_ranges is not None:
        f["page_ranges"] = ns.page_ranges
    if ns.data_id is not None:
        f["data_id"] = ns.data_id
    return f


def _global_opt_fields(ns):
    """不含 page_ranges/data_id (分页里逐片设置)。"""
    f = {}
    if ns.is_ocr is not None:
        f["is_ocr"] = ns.is_ocr
    if ns.enable_formula is not None:
        f["enable_formula"] = ns.enable_formula
    if ns.enable_table is not None:
        f["enable_table"] = ns.enable_table
    if ns.language is not None:
        if ns.language not in VALID_LANGUAGES:
            die("language 取值无效: %s (允许: %s)" % (ns.language, ", ".join(sorted(VALID_LANGUAGES))))
        f["language"] = ns.language
    if ns.extra_formats:
        f["extra_formats"] = ns.extra_formats
    if ns.no_cache:
        f["no_cache"] = True
    if ns.cache_tolerance is not None:
        f["cache_tolerance"] = ns.cache_tolerance
    return f


def _is_html(name_or_url):
    return name_or_url.lower().endswith((".html", ".htm"))


# --------------------------- Subcommands ---------------------------

def _probe_url_pdf(url, tmp_dir):
    """下载 URL 的 PDF 头部以探测页数: 先试 pypdf 流式探测 (~前 50KB 不足以读全部页, 故下整文件但不落盘)。
       实际策略: 直接整文件下载到临时目录, 用 pypdf 读页数, 返回 (local_path, n_pages)。
       非 PDF 或读不出页数时返回 (None, None)。"""
    if not url.lower().split("?")[0].endswith(".pdf"):
        return None, None
    if not _HAS_PYPDF:
        return None, None  # 无 pypdf 不下载, 直接走 URL 直传
    os.makedirs(tmp_dir, exist_ok=True)
    path = os.path.join(tmp_dir, "url_src.pdf")
    info("探测 URL PDF 页数, 下载到临时目录...")
    try:
        _download_file(url, path)
    except Exception as e:
        info("下载探测失败 (%s), 改走 URL 直传。" % e)
        try:
            os.remove(path)
        except OSError:
            pass
        return None, None
    n = _pdf_pages(path)
    if n is None:
        info("pypdf 读不出页数, 改走 URL 直传。")
        try:
            os.remove(path)
        except OSError:
            pass
        return None, None
    return path, n


def cmd_parse(ns):
    token = load_token()
    model = "MinerU-HTML" if _is_html(ns.url) else ns.model
    # 本地 PDF 自动下载探测: 小文件直传 URL, 大 PDF (>200MB 或 >200页) 切片走批量分片
    if not _is_html(ns.url) and model != "MinerU-HTML" \
       and getattr(ns, "url_split_mode", "auto") == "auto":
        tmp_dir = tempfile.mkdtemp(prefix="mineru_url_")
        local_path, n_pages = _probe_url_pdf(ns.url, tmp_dir)
        if local_path is not None:
            sz = os.path.getsize(local_path)
            info("URL PDF 探测: %d 页, %.1fMB" % (n_pages, sz / 1024 / 1024))
            # 是否需要分页 (超 200MB 或 >200页)
            if sz > MAX_SIZE_BYTES or n_pages > MAX_PAGES:
                if not _HAS_PYPDF:
                    info("需分页但无 pypdf, 按 URL 直传 (超限会被 API 拒 -60005/-60006)。")
                else:
                    info("URL PDF 超限 (%d 页 / %.1fMB), 走分片..."
                         % (n_pages, sz / 1024 / 1024))
                    parts_with_ranges = _split_foolproof(local_path)
                    # 复用 upload 分片逻辑: 把 ns.files[0] 指向已下载的本地 PDF
                    ns.files = [local_path]
                    try:
                        _upload_and_merge_parts(token, ns, parts_with_ranges)
                        return
                    finally:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
            else:
                info("URL PDF 在限制内 (%d 页 / %.1fMB), URL 直传。"
                     % (n_pages, sz / 1024 / 1024))
                # 已下载的文件可删掉, 直接走 URL
                try:
                    os.remove(local_path)
                except OSError:
                    pass
                shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    # 默认路径: 提交单文件 URL
    data = {"url": ns.url, "model_version": model}
    data.update(build_opt_fields(ns))
    info("提交单文件解析: %s (model=%s)" % (ns.url, model))
    status, result, _ = _post(BASE_URL + "/api/v4/extract/task",
                             auth_headers(token), json_body=data)
    if status != 200:
        die("提交失败: HTTP %s" % status)
    check_api_result(result, "创建解析任务")
    task_id = result["data"]["task_id"]
    info("task_id = %s" % task_id)
    if ns.poll:
        poll_single(token, task_id, ns.timeout, ns.interval, ns.download)
    else:
        print_json(result)


def cmd_upload(ns):
    token = load_token()
    # 单本地 PDF 且需分页(>200MB 或 >200页): 走傻瓜拆分+合并
    if len(ns.files) == 1 and getattr(ns, "split_mode", "auto") != "none":
        fp = ns.files[0]
        if not os.path.exists(fp):
            die("文件不存在: %s" % fp)
        if os.path.getsize(fp) == 0:
            die("空文件: %s" % fp)
        if fp.lower().endswith(".pdf"):
            if not _HAS_PYPDF:
                info("未安装 pypdf(建议 pip install pypdf), 无法自动分页, 按整文件上传。")
            elif _need_split(fp):
                info("需要分页拆分 (超 200MB 或超 200页)...")
                parts_with_ranges = _split_foolproof(fp)
                _upload_and_merge_parts(token, ns, parts_with_ranges)
                return
    files = []
    for fp in ns.files:
        if not os.path.exists(fp):
            die("文件不存在: %s" % fp)
        if os.path.getsize(fp) == 0:
            die("空文件: %s" % fp)
        if os.path.getsize(fp) > 200 * 1024 * 1024:
            die("文件超出 200MB 限制: %s" % fp)
        name = os.path.basename(fp)
        files.append({"name": name, "data_id": ns.data_id or name})
    if len(files) > 50:
        die("单次申请链接不能超过 50 个")
    data = {"files": files, "model_version": ns.model}
    data.update(build_opt_fields(ns))
    info("申请上传链接 (%d 个文件)..." % len(files))
    status, result, _ = _post(BASE_URL + "/api/v4/file-urls/batch",
                             auth_headers(token), json_body=data)
    if status != 200:
        die("申请上传链接失败: HTTP %s" % status)
    check_api_result(result, "申请上传链接")
    batch_id = result["data"]["batch_id"]
    urls = result["data"]["file_urls"]
    info("batch_id = %s" % batch_id)
    if len(urls) != len(files):
        die("返回的上传链接数量与文件数不一致 (%s vs %s)" % (len(urls), len(files)))
    for fp, up_url in zip(ns.files, urls):
        info("上传: %s" % fp)
        code, _ = _put_raw(up_url, fp)
        if code not in (200, 201):
            die("上传失败: %s HTTP %s" % (fp, code))
    info("全部上传完成, 系统将自动提交解析任务。")
    if ns.poll:
        poll_batch(token, batch_id, ns.timeout, ns.interval, ns.download)
    else:
        print_json(result)


def cmd_batch_url(ns):
    token = load_token()
    files = [{"url": u, "data_id": ns.data_id} for u in ns.urls] if ns.data_id \
        else [{"url": u} for u in ns.urls]
    data = {"files": files, "model_version": ns.model}
    data.update(build_opt_fields(ns))
    info("提交批量 URL 解析 (%d 个)..." % len(ns.urls))
    status, result, _ = _post(BASE_URL + "/api/v4/extract/task/batch",
                             auth_headers(token), json_body=data)
    if status != 200:
        die("批量提交失败: HTTP %s" % status)
    check_api_result(result, "批量提交解析任务")
    batch_id = result["data"]["batch_id"]
    info("batch_id = %s" % batch_id)
    if ns.poll:
        poll_batch(token, batch_id, ns.timeout, ns.interval, ns.download)
    else:
        print_json(result)


def cmd_status(ns):
    token = load_token()
    url = ("%s/api/v4/extract-results/batch/%s" % (BASE_URL, ns.id) if ns.batch
           else "%s/api/v4/extract/task/%s" % (BASE_URL, ns.id))
    status, result, _ = _get(url, auth_headers(token))
    if status != 200:
        die("查询失败: HTTP %s" % status)
    if isinstance(result, dict) and result.get("code") not in (0, "0"):
        check_api_result(result, "查询任务")
    data = result.get("data", {}) if isinstance(result, dict) else {}
    if ns.batch:
        for r in data.get("extract_result", []):
            extra = ""
            if r.get("full_zip_url"):
                extra = " -> %s" % r["full_zip_url"]
            if r.get("err_msg"):
                extra += " err=%s" % r["err_msg"]
            info("%s: %s%s" % (r.get("data_id") or r.get("file_name", "?"),
                              r.get("state", ""), extra))
    else:
        st = data.get("state", "")
        info("state=%s" % st)
        if st == "done":
            info("full_zip_url=%s" % data.get("full_zip_url", ""))
        if st == "failed":
            info("err_msg=%s" % data.get("err_msg", ""))
    print_json(result)


def cmd_download(ns):
    download_and_unzip(ns.zip_url, ns.out_dir)


# --------------------------- argparse ---------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="mineru",
        description="MinerU 精准解析 API 命令行封装。先运行 --help 查看子命令。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("parse", help="单文件 URL 解析 (PDF 先下载探页数; 在限内直传, 超限自动分片)")
    p.add_argument("url", help="文件 URL (支持 pdf/doc/docx/ppt/pptx/xls/xlsx/图片/html)")
    add_common_options(p)
    p.add_argument("--url-split-mode", default="auto", choices=["auto", "none"],
                   help="auto: PDF URL 先下载探页数, 在限内直传, 超限(>200MB/200页)本地分片(默认); none: 始终 URL 直传(超限被 API 拒 -60005/-60006)")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("upload", help="本地文件上传解析 (单本地PDF超200MB/200页自动分页合并; 多文件<=50)")
    p.add_argument("files", nargs="+", help="本地文件路径")
    add_common_options(p)
    p.add_argument("--split-mode", default="auto", choices=["auto", "none"],
                   help="auto: 单本地PDF超限自动分页拆分(默认); none: 不拆分, 按整文件上传(超200MB/页会被API拒)")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("batch-url", help="批量 URL 解析")
    p.add_argument("urls", nargs="+", help="文件 URL 列表")
    add_common_options(p)
    p.set_defaults(func=cmd_batch_url)

    p = sub.add_parser("status", help="查询任务/批量进度")
    p.add_argument("id", help="task_id 或 batch_id")
    p.add_argument("--batch", action="store_true", help="ID 为 batch_id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("download", help="下载并解压结果 zip")
    p.add_argument("zip_url", help="full_zip_url")
    p.add_argument("out_dir", help="解压目标目录")
    p.set_defaults(func=cmd_download)

    return parser


def main(argv=None):
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not getattr(ns, "cmd", None):
        parser.print_help()
        sys.exit(0)
    try:
        ns.func(ns)
    except KeyboardInterrupt:
        info("已中断。")
        sys.exit(130)


if __name__ == "__main__":
    main()