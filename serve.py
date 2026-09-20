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
import os
import re
import socket
import sys
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

    def _serve(self, head_only):
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
            size = os.fstat(f.fileno()).st_size
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
                self._cache_headers(no_cache)
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
                self._cache_headers(no_cache)
                self.end_headers()
                if not head_only:
                    f.seek(start)
                    self._pump(f, length)

    def _cache_headers(self, no_cache):
        if no_cache:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header("Cache-Control", "public, max-age=86400")

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
