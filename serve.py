"""UOM 查看器本地服务器。

要点：
  1. HTTP Range 支持 —— PMTiles 靠它按需拉字节。Python 自带的
     SimpleHTTPRequestHandler 不支持 Range，所以这里自己实现。
  2. HTTP/1.1 keep-alive —— 减少连接开销，Range 请求会很频繁。
  3. 双栈监听（IPv4 + IPv6）—— Windows 上 localhost 可能解析到 ::1，
     只绑 IPv4 会等超时。
  4. 多线程 —— 瓦片并发请求。

用法: python serve.py [端口]
"""
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
ROOT = os.path.dirname(os.path.abspath(__file__))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".geojson": "application/geo+json; charset=utf-8",
    ".pmtiles": "application/octet-stream",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


_pmtiles_lock = __import__("threading").Lock()
_pmtiles = None


def _get_pmtiles():
    """延迟加载 PMTiles 读取器（复用已验证的 pmtiles_tool）。"""
    global _pmtiles
    if _pmtiles is None:
        with _pmtiles_lock:
            if _pmtiles is None:
                sys.path.insert(0, ROOT)
                import pmtiles_tool
                _pmtiles = pmtiles_tool.PMTiles(
                    os.path.join(ROOT, "data", "uom-shifei.pmtiles"))
    return _pmtiles


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "UOMViewer/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        pass  # PMTiles 会发大量 Range 请求，静默

    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        return MIME.get(ext) or super().guess_type(path)

    def do_HEAD(self):
        self._serve(head_only=True)

    def do_GET(self):
        self._serve(head_only=False)

    def do_POST(self):
        """接收前端诊断上报，追加写入 diag.log。

        这么做的原因：排查时只能拿到截图，而截图里的文字无法被程序读取。
        让页面把诊断文本直接回传落盘，就能直接查看浏览器里的真实状态。
        """
        if self.path.split("?")[0] != "/__diag":
            self.send_error(404, "Not found")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        body = self.rfile.read(n) if n else b""
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            text = repr(body)
        try:
            with open(os.path.join(ROOT, "diag.log"), "a", encoding="utf-8") as f:
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")
            sys.stdout.write("[diag] " + text.strip()[:400] + "\n")
            sys.stdout.flush()
        except OSError:
            pass
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _serve(self, head_only):
        if self.path.split("?")[0] == "/diag/probe":
            self._serve_basemap_probe()
            return
        if self.path.split("?")[0] == "/diag/view":
            self._serve_view_truth()
            return
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return

        ext = os.path.splitext(path)[1].lower()
        # 代码文件不许缓存，否则改完刷新还是旧版（PMTiles 的 Range 响应
        # 反过来要允许缓存，否则每次缩放都重新拉字节）
        no_cache = ext in (".html", ".js", ".css", ".json", ".geojson")

        with f:
            st = os.fstat(f.fileno())
            size = st.st_size
            ctype = self.guess_type(path)
            rng = self.headers.get("Range")
            start = end = None
            if rng:
                m = RANGE_RE.match(rng.strip())
                if m:
                    g1, g2 = m.group(1), m.group(2)
                    if g1 == "" and g2 != "":          # bytes=-500 末尾 N 字节
                        n = int(g2)
                        start = max(0, size - n)
                        end = size - 1
                    elif g1 != "":
                        start = int(g1)
                        end = int(g2) if g2 != "" else size - 1
                        end = min(end, size - 1)
                    if start is not None and (start > end or start >= size):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return

            if start is None:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self._cache_headers(no_cache, st, size)
                self.end_headers()
                if not head_only:
                    self._pump(f, size)
            else:
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self._cache_headers(no_cache, st, size)
                self.end_headers()
                if not head_only:
                    f.seek(start)
                    self._pump(f, length)

    def _serve_view_truth(self):
        """列出某个矩形范围内，哪些瓦片在档案里确实有数据。

        用途：客户端可以把它与自己实际拿到的结果比对，从而判断
        "界面上白掉的那一片"到底是「本来就没有适飞数据」还是
        「客户端取数出了问题」。用已验证的 Python 读取器算，与客户端
        各走一条独立路径。
        """
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        try:
            z = int(q.get("z", ["13"])[0])
            x0 = int(q.get("x0", ["0"])[0]); x1 = int(q.get("x1", ["-1"])[0])
            y0 = int(q.get("y0", ["0"])[0]); y1 = int(q.get("y1", ["-1"])[0])
        except ValueError:
            self.send_error(400, "bad params")
            return
        if x1 < x0 or y1 < y0 or (x1 - x0 + 1) * (y1 - y0 + 1) > 4000:
            self.send_error(400, "range too large or invalid")
            return
        try:
            pm = _get_pmtiles()
        except Exception as e:
            self.send_error(500, "pmtiles unavailable: %s" % e)
            return
        have, lack = [], []
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if pm.get_tile(z, x, y):
                    have.append([x, y])
                else:
                    lack.append([x, y])
        payload = json.dumps({
            "z": z, "count": len(have) + len(lack),
            "have": len(have), "lack": len(lack),
            "haveList": have[:1500],
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    # 允许代查的图源域名（避免变成任意 URL 代理）
    PROBE_HOSTS = (
        "tianditu.gov.cn", "autonavi.com", "map.gtimg.com",
        "arcgisonline.com", "openstreetmap.de", "openstreetmap.fr",
        "bdimg.com",
    )

    def _serve_basemap_probe(self):
        """代查一条瓦片地址，回报真实状态码。

        为什么需要：浏览器里 <img> 加载失败只能知道"失败了"，跨域图片读不到
        状态码。而 418(WAF拦截) / 403(key被拒) / 429(配额用尽) / 200(正常)
        的区别正是定位问题的关键。服务端发请求没有跨域限制。
        只允许代查白名单内的图源域名。
        """
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        target = (q.get("u", [""])[0] or "").strip()
        if not target.startswith("https://"):
            self.send_error(400, "only https")
            return
        host = urlparse(target).hostname or ""
        if not any(host == h or host.endswith("." + h) for h in self.PROBE_HOSTS):
            self.send_error(403, "host not allowed")
            return
        out = {"url": target, "host": host}
        try:
            req = urllib.request.Request(target, headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"),
                "Referer": "http://127.0.0.1:8080/",
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                d = r.read()
                out["status"] = r.status
                out["contentType"] = r.headers.get("Content-Type", "")
                out["bytes"] = len(d)
                # PNG 魔数 89 50 4E 47 或 JPEG 魔数 FF D8
                out["looksLikeImage"] = (d[:4] == bytes((0x89, 0x50, 0x4E, 0x47))) or (d[:2] == bytes((0xFF, 0xD8)))
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            out["status"] = e.code
            out["contentType"] = e.headers.get("Content-Type", "") if e.headers else ""
            out["bytes"] = len(body)
            out["looksLikeImage"] = False
        except Exception as e:
            out["error"] = "%s: %s" % (type(e).__name__, e)
        payload = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _cache_headers(self, no_cache, st=None, size=None):
        if no_cache:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            return
        self.send_header("Cache-Control", "public, max-age=86400")
        # 分片(206)响应要被浏览器正确缓存，必须有校验器：
        # 否则 Chrome 拼接分片时无法判断一致性，可能拿到错位数据
        # （pmtiles 库因此在 Windows+Chromium 上强制 no-store 绕开该问题）。
        # 这里给出 Last-Modified + ETag，让分片缓存变得可靠，
        # 客户端也就可以安全地关闭 no-store。
        if st is not None:
            self.send_header("Last-Modified", self.date_time_string(st.st_mtime))
            self.send_header(
                "ETag", '"%x-%x"' % (int(st.st_mtime), size or 0))

    def _pump(self, f, length):
        remaining = length
        while remaining > 0:
            chunk = f.read(min(262144, remaining))
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return
            remaining -= len(chunk)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256
    disable_nagle_algorithm = True


class ServerV6(Server):
    address_family = socket.AF_INET6


def main():
    try:
        srv = ServerV6(("::", PORT), RangeHandler)
        srv.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except OSError:
        srv = Server(("0.0.0.0", PORT), RangeHandler)
    print("UOM 查看器已启动")
    print(f"  http://127.0.0.1:{PORT}/index.html")
    print(f"根目录: {ROOT}")
    print("Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()
