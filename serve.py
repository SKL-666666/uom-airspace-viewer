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
import collections
import io
import json
import os
import re
import socket
import sys
import threading
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


# =====================================================================
# UOM 瓦片服务：把 4 张 256px 原始瓦片合成一张 512px，减少请求数
#
# 起因：PMTiles 原始数据是 256px 瓦片，客户端每张瓦片要发 1 个 Range 请求。
# 一屏 1911x1053 需要 40 多张，加上预取就是上百个请求，而浏览器对同一
# 域名只开 6 条连接 —— 请求数就是"瓦片刷新慢"的直接原因。
#
# 服务端合成 512px 瓦片后，同样的屏幕面积只需 12 张，请求数降到 1/3.3；
# 同时客户端不再需要在浏览器里解析 PMTiles。
#
# 坐标约定：客户端用 tileSize:512 + zoomOffset:-1，所以 URL 里的 Z 比原生
# 层级小 1。URL 的 (Z, X, Y) 对应原生 (Z+1) 层级的 (2X..2X+1, 2Y..2Y+1)。
# =====================================================================
UOM_RE = re.compile(r"^/uom/(\d+)/(\d+)/(\d+)\.png$")
UOM_PROBE_RE = re.compile(r"^/uom/probe$")

_pmtiles_lock = threading.Lock()
_pmtiles = None
_tile_cache = collections.OrderedDict()
_tile_cache_lock = threading.Lock()
TILE_CACHE_MAX = 600          # 约 600 张 512px PNG，内存占用可控


def _get_pmtiles():
    """延迟加载 PMTiles 读取器（复用 pmtiles_tool 里已验证的实现）"""
    global _pmtiles
    if _pmtiles is None:
        with _pmtiles_lock:
            if _pmtiles is None:
                sys.path.insert(0, ROOT)
                import pmtiles_tool
                _pmtiles = pmtiles_tool.PMTiles(
                    os.path.join(ROOT, "data", "uom-shifei.pmtiles"))
    return _pmtiles


def _cache_get(key):
    with _tile_cache_lock:
        data = _tile_cache.get(key)
        if data is not None:
            _tile_cache.move_to_end(key)
        return data


def _cache_put(key, data):
    with _tile_cache_lock:
        _tile_cache[key] = data
        while len(_tile_cache) > TILE_CACHE_MAX:
            _tile_cache.popitem(last=False)


def build_uom_tile(Z, X, Y):
    """合成一张 512x512 PNG。返回 bytes 或 None（该处无数据）"""
    key = (Z, X, Y)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    try:
        from PIL import Image
    except ImportError:
        return None
    pm = _get_pmtiles()
    nz = Z + 1                      # 原生层级
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    got = 0
    for i in range(2):
        for j in range(2):
            raw = pm.get_tile(nz, X * 2 + i, Y * 2 + j)
            if not raw:
                continue
            try:
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
            except Exception:
                continue
            canvas.paste(img, (i * 256, j * 256), img)
            got += 1
    if not got:
        _cache_put(key, b"")        # 缓存"无数据"，避免反复查目录
        return b""
    data = _encode_binary_png(canvas)
    _cache_put(key, data)
    return data


# UOM 数据只有两种像素：全透明 与 固定蓝色 RGBA(41,128,185,255)。
# 用 2 色调色板 PNG8 编码，比全彩 RGBA PNG 快数倍、体积也小得多，
# 而且和原始数据格式一致（原始就是 PNG8 二值图）。
UOM_COLOR = (41, 128, 185)


def _encode_binary_png(canvas):
    from PIL import Image
    size = canvas.size
    # 用 alpha 通道做二值掩码
    alpha = canvas.getchannel("A").point(lambda v: 255 if v >= 128 else 0, "L")
    pal = Image.new("P", size, 0)
    table = [0, 0, 0, UOM_COLOR[0], UOM_COLOR[1], UOM_COLOR[2]] + [0] * 762
    pal.putpalette(table)
    pal.paste(1, (0, 0, size[0], size[1]), alpha)   # 适飞处标为索引 1
    buf = io.BytesIO()
    # transparency=0 让索引 0 全透明
    pal.save(buf, format="PNG", optimize=False, compress_level=6, transparency=0)
    return buf.getvalue()


def probe_point(lon, lat):
    """查询某点是否在适飞空域内，返回 (tile_coord, pixel_rgba)"""
    pm = _get_pmtiles()
    import pmtiles_tool as pt
    z = 13
    x, y, px, py = pt.lonlat_to_tile_pixel(lon, lat, z)
    raw = pm.get_tile(z, x, y)
    if not raw:
        return f"{z}/{x}/{y}", None
    rgba = pt.png_pixel(raw, px, py)
    return f"{z}/{x}/{y}", rgba



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
        raw_path = self.path.split("?")[0]

        # --- UOM 合成瓦片 ---
        m = UOM_RE.match(raw_path)
        if m:
            self._serve_uom_tile(int(m.group(1)), int(m.group(2)), int(m.group(3)), head_only)
            return
        if raw_path == "/uom/probe":
            self._serve_probe()
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

    def _serve_uom_tile(self, Z, X, Y, head_only):
        try:
            data = build_uom_tile(Z, X, Y)
        except Exception as e:
            sys.stdout.write("[uom] tile %s/%s/%s build failed: %s\n" % (Z, X, Y, e))
            sys.stdout.flush()
            self.send_error(500, "tile build failed")
            return
        if data is None:
            self.send_error(500, "PIL unavailable")
            return
        body = data if data else b""
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        # 合成瓦片可长期缓存：数据是静态的，客户端缓存后不再重复请求
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        if not head_only and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _serve_probe(self):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        try:
            lon = float(q.get("lon", ["0"])[0])
            lat = float(q.get("lat", ["0"])[0])
        except ValueError:
            self.send_error(400, "bad lon/lat")
            return
        try:
            tile, rgba = probe_point(lon, lat)
        except Exception as e:
            self.send_error(500, f"probe failed: {e}")
            return
        payload = json.dumps({
            "lon": lon, "lat": lat, "tile": tile,
            "rgba": list(rgba) if rgba else None,
            "suitable": bool(rgba and rgba[3] == 255),
            "hasData": rgba is not None,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

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
