"""UOM 适飞空域查询 —— 桌面版（WebView 外壳）。

用一个内嵌 WebView 加载本地的 index.html，并起一个轻量本地 HTTP 服务
（PMTiles 依赖 HTTP Range 请求，file:// 下读不到数据）。

为什么自带服务而不是让用户手工跑 serve.py：
  单文件分发的意义就是"双击即用"。为了不依赖 Python 环境，
  这里用的服务只依赖标准库（与 serve.py 同一套 Range 实现）。
"""
import os
import socket
import sys
import threading
import time
import webbrowser

import webview

# 打包后资源在 sys._MEIPASS；直接运行时就是脚本所在目录
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = BASE if os.path.exists(os.path.join(BASE, "index.html")) else APP_DIR

PORT = 0          # 0 = 让系统分配空闲端口，避免和已有服务冲突


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_server(port):
    """复用 serve.py 的实现（打包时已一并打进包里）"""
    sys.path.insert(0, ROOT)
    import serve as srv

    from http.server import HTTPServer
    from socketserver import ThreadingMixIn

    class S(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        request_queue_size = 256
        disable_nagle_algorithm = True

    httpd = S(("127.0.0.1", port), srv.RangeHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


class Api:
    """暴露给页面的接口（可选，用于打开外部链接）"""

    def open_external(self, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            webbrowser.open(url)


def main():
    port = free_port()
    httpd = start_server(port)
    # 关窗时不要打印 socketserver 的异常堆栈：
    # webview.start() 返回后仍有连接在收尾，shutdown() 会让它们抛
    # ConnectionAbortedError，看起来像崩溃，其实是正常退出。
    import socketserver
    socketserver.BaseServer.handle_error = lambda self, request, client_address: None

    # 等服务真正可连（避免窗口先打开、资源还没就绪）
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)

    url = "http://127.0.0.1:%d/index.html" % port
    webview.create_window(
        "UOM 适飞空域查询",
        url,
        width=1280,
        height=820,
        min_size=(820, 560),
        js_api=Api(),
        text_select=True,
    )
    try:
        webview.start()
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
